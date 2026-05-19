# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic tests for the Tag-77 OTS-Live-Stamping Setup-Recipe doc and
verifier-helper.

Auftrag-Anker
-------------

Tag-77 Tomás Auftrag (Mira, 2026-05-19, Continuous-Mode Marathon-Polish):
Operator-Hand-OTS-Live-Stamping-Setup-Doc for pre-Cutover-Eve
WAKIR_OTS_LIVE_EMIT=1 activation. Predecessor: Tag-57 PR #366
(audit-only emit), Tag-58 PR #371 (Spec-Seal), Tag-59 (pre-activation
probe), Tag-76 PR #484 (Phase-3-COMPLETE-Marker).

Scope (doc + verifier-helper)
-----------------------------

This module verifies two surfaces:

* The Tag-77 setup-doc
  (``docs/operations/ots-live-stamping-operator-setup.md``):
  - frontmatter sanity (title, status, owner=tomas, tag=tag-77)
  - cross-anchor PRs and Cross-Review-Markers in frontmatter
  - required sections §1..§8 present with verbatim headings
  - §1 scope-table covers Pre-Eve / Eve / Eve+1 / T0 / T0+0.5h /
    T0..T0+6 and names 2026-06-07 + 2026-06-08
  - §2 probe verification (3 sub-sections) + PROBE-READY token
  - §3 AR-authorisation-gate (3 sub-sections) + MUST-NOT-flip pin
  - §4 toggle-export (3 sub-sections) + ots-CLI-presence-check
  - §5 first-live-stamp (4 sub-sections) + Bitcoin verify
  - §6 marker-chain (4 sub-sections) + Welle-1..7 named
  - §7 rollback (4 sub-sections) + 5 named triggers R1..R5
  - §8 sandbox-boundary (5 sub-sections) + ADR-0023a anchor

* The Tag-77 verifier-helper
  (``tooling/ci/verify_ots_live_setup_doc.py``):
  - returns 0 against the as-checked-in doc
  - returns non-zero against a doc with a missing required section
  - returns non-zero against a doc that drops the §3.3 MUST-NOT pin
  - returns non-zero against a doc that lacks the toggle-export
    line
  - returns non-zero against a doc that drops one of the five
    rollback triggers
  - tolerates a leading HTML SPDX comment before the YAML
    frontmatter (the Tag-77 doc carries one)

Hermetic posture
----------------

stdlib + unittest. No subprocess into the network. The verifier is
loaded as a module from its file path. The doc is parsed as text.

Scope discipline (ADR-0036/0044/0066)
-------------------------------------

This test pins only the Tag-77 setup-doc substrate. It does NOT
modify the OTS emit-helper (Tag-57..Tag-76 substrate), the Tag-70
HD-1 OTS-substrate-stub, the persona-engine substrate, or any
Welle-N audit-anchor wiring.

Cross-Review-Markers
--------------------

* Zone-K: WAT-Core × OTS-Substrate — the live-stamp recipe is the
  Operator-Hand consumer of every Welle-N audit-anchor marker
  Tomás emitted between Tag-69 and Tag-76. Drift between the
  recipe step-shape and the emit-helper output is a Zone-K signal.
* Zone-L: Identity × Spec-Seal — Reza-Tag-58 PR #371 sealed the
  Wirelang-Spec v0.4.3 cutover window. Drift between the recipe's
  cutover-date pin (2026-06-08) and the spec-seal cutover window
  is a Zone-L signal.
* Zone-N: QA × Audit-Trail — the operator-hand-audit-log.jsonl,
  AR-authorisation marker SHA-256, and quarantined .ots proof
  files are Henrik Voss Audit-Evidence-Inputs. Drift in their
  structure or completeness is a Zone-N signal.
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
    REPO_ROOT / "tooling" / "ci" / "verify_ots_live_setup_doc.py"
)
DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "ots-live-stamping-operator-setup.md"
)


def _load_verifier():
    """Load the Tag-77 verifier as a module."""
    mod_name = "verify_ots_live_setup_doc_tag77"
    spec = importlib.util.spec_from_file_location(mod_name, VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_verifier_on(text: str) -> tuple[int, str, str]:
    """Run the verifier against an arbitrary doc body in a temp dir.

    Returns ``(exit_code, stdout, stderr)``. Because the verifier
    reads from a hard-coded DOC_PATH at the top of the module, we
    monkey-patch DOC_PATH on the loaded module via a tempdir file.
    """
    m = _load_verifier()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_doc = Path(tmpdir) / "ots-live-stamping-operator-setup.md"
        tmp_doc.write_text(text, encoding="utf-8")
        m.DOC_PATH = tmp_doc
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        code = 0
        try:
            with redirect_stdout(out_buf), redirect_stderr(err_buf):
                code = m.main()
        except SystemExit as exc:
            code = int(exc.code) if exc.code is not None else 0
        return code, out_buf.getvalue(), err_buf.getvalue()


class TestDocExistsAndPasses(unittest.TestCase):
    """The doc is present and the verifier returns 0 (no findings)."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        self.assertTrue(DOC_PATH.exists(), f"missing doc: {DOC_PATH}")
        self.text = DOC_PATH.read_text(encoding="utf-8")

    def test_t01_doc_file_exists_and_nonempty(self) -> None:
        self.assertGreater(len(self.text.strip()), 500)

    def test_t02_verifier_returns_zero_against_checked_in_doc(self) -> None:
        code, out, err = _run_verifier_on(self.text)
        self.assertEqual(code, 0, f"verifier failed against checked-in doc: {err}")
        self.assertIn("verify_ots_live_setup_doc: OK", out)


class TestFrontmatter(unittest.TestCase):
    """Frontmatter sanity surface."""

    def setUp(self) -> None:
        self.text = DOC_PATH.read_text(encoding="utf-8")

    def test_t03_frontmatter_owner_tomas(self) -> None:
        self.assertIsNotNone(
            re.search(r'^owner:\s*"tomas"', self.text, re.MULTILINE)
        )

    def test_t04_frontmatter_tag_tag77(self) -> None:
        self.assertIsNotNone(
            re.search(r'^tag:\s*"tag-77"', self.text, re.MULTILINE)
        )

    def test_t05_frontmatter_predecessor_chain_present(self) -> None:
        self.assertIn("manifest-hash-ots-anchor-wiring.md", self.text)

    def test_t06_doc_starts_with_html_comment_then_frontmatter(self) -> None:
        # Leading SPDX HTML comment before YAML frontmatter.
        self.assertTrue(self.text.startswith("<!--"))
        # YAML frontmatter follows the HTML comment.
        self.assertIn("---\ntitle:", self.text)


class TestRequiredSections(unittest.TestCase):
    """Required sections §1..§8 present with verbatim headings."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        self.text = DOC_PATH.read_text(encoding="utf-8")
        self.sections = self.m.split_sections(self.text)

    def test_t07_all_eight_sections_present_in_order(self) -> None:
        last_idx = -1
        for req in self.m.REQUIRED_SECTIONS:
            idx = self.text.find(f"## {req} ")
            self.assertGreaterEqual(
                idx, 0, f"missing section header {req}"
            )
            self.assertGreater(
                idx, last_idx,
                f"section {req} out of order"
            )
            last_idx = idx

    def test_t08_section_count_is_exactly_eight(self) -> None:
        # Extra top-level ## headings would imply scope-creep.
        top_level_count = sum(
            1
            for line in self.text.splitlines()
            if line.startswith("## ")
        )
        self.assertEqual(
            top_level_count,
            len(self.m.REQUIRED_SECTIONS),
            f"expected exactly 8 top-level § sections, got "
            f"{top_level_count}",
        )


class TestSection1Scope(unittest.TestCase):
    """§1 Scope-Table covers all six activation phases."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        self.text = DOC_PATH.read_text(encoding="utf-8")
        self.s1 = self.m.split_sections(self.text)["§1"]

    def test_t09_scope_table_six_rows_present(self) -> None:
        for row in self.m.REQUIRED_S1_ROWS:
            self.assertIn(
                row, self.s1,
                f"§1 scope-table missing row '{row.strip()}'"
            )

    def test_t10_cutover_dates_named(self) -> None:
        self.assertIn("2026-06-07", self.s1)
        self.assertIn("2026-06-08", self.s1)
        self.assertIn("KW-24", self.s1)


class TestSection2Probe(unittest.TestCase):
    """§2 probe verification covers manifest-hash + Phase-3-COMPLETE."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        text = DOC_PATH.read_text(encoding="utf-8")
        self.s2 = self.m.split_sections(text)["§2"]

    def test_t11_three_subsections_present(self) -> None:
        for sub in self.m.REQUIRED_S2_SUBSECTIONS:
            self.assertIn(sub, self.s2, f"§2 missing subsection {sub}")

    def test_t12_probe_ready_aggregate_token_present(self) -> None:
        self.assertIn("PROBE-READY", self.s2)
        self.assertIn("PRE-EVE-PROBE-GREEN", self.s2)


class TestSection3ARAuthorisation(unittest.TestCase):
    """§3 AR-authorisation gate carries no-AR-no-flip pin."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        text = DOC_PATH.read_text(encoding="utf-8")
        self.s3 = self.m.split_sections(text)["§3"]

    def test_t13_must_not_pin_present(self) -> None:
        self.assertIn("MUST NOT", self.s3)

    def test_t14_ar_hand_inbox_marker_filename_pattern(self) -> None:
        self.assertIn("ar-hand/inbox/", self.s3)
        self.assertIn("ots-live-emit-activation-authorisation", self.s3)


class TestSection4Toggle(unittest.TestCase):
    """§4 export-toggle is verbatim and shell-scope-only."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        text = DOC_PATH.read_text(encoding="utf-8")
        self.s4 = self.m.split_sections(text)["§4"]

    def test_t15_export_live_emit_one_verbatim(self) -> None:
        self.assertIn("export WAKIR_OTS_LIVE_EMIT=1", self.s4)

    def test_t16_shell_scope_only_discipline_pinned(self) -> None:
        self.assertIn("shell-scope export only", self.s4)
        self.assertIn(".env", self.s4)


class TestSection5FirstLiveStamp(unittest.TestCase):
    """§5 first-live-stamp invokes the three ots CLI verbs."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        text = DOC_PATH.read_text(encoding="utf-8")
        self.s5 = self.m.split_sections(text)["§5"]

    def test_t17_three_ots_cli_verbs_present(self) -> None:
        self.assertIn("ots stamp", self.s5)
        self.assertIn("ots upgrade", self.s5)
        self.assertIn("ots verify", self.s5)

    def test_t18_bitcoin_block_attestation_named(self) -> None:
        self.assertIn("Bitcoin", self.s5)


class TestSection6MarkerChain(unittest.TestCase):
    """§6 marker-chain references all seven Welle-N markers."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        text = DOC_PATH.read_text(encoding="utf-8")
        self.s6 = self.m.split_sections(text)["§6"]

    def test_t19_welle_1_through_7_named(self) -> None:
        for n in range(1, 8):
            self.assertIn(
                f"Welle-{n}", self.s6,
                f"§6 must reference Welle-{n}"
            )

    def test_t20_chain_hash_field_referenced(self) -> None:
        self.assertIn("welle_1_7_marker_chain", self.s6)
        self.assertIn("cross_substrate_parity_markers", self.s6)


class TestSection7Rollback(unittest.TestCase):
    """§7 rollback enumerates five named triggers."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        text = DOC_PATH.read_text(encoding="utf-8")
        self.s7 = self.m.split_sections(text)["§7"]

    def test_t21_five_rollback_triggers_named(self) -> None:
        for trigger in self.m.REQUIRED_ROLLBACK_TRIGGERS:
            self.assertIn(
                trigger, self.s7,
                f"§7.1 missing rollback trigger '{trigger}'"
            )

    def test_t22_unset_live_emit_verbatim(self) -> None:
        self.assertIn("unset WAKIR_OTS_LIVE_EMIT", self.s7)
        self.assertIn("rollback-quarantine", self.s7)

    def test_t23_re_arm_marker_required_for_reactivation(self) -> None:
        self.assertIn("re-arm marker", self.s7)


class TestSection8SandboxBoundary(unittest.TestCase):
    """§8 sandbox-boundary explicit + anchored to ADR-0023a."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        text = DOC_PATH.read_text(encoding="utf-8")
        self.s8 = self.m.split_sections(text)["§8"]

    def test_t24_sandbox_scope_dual_pin(self) -> None:
        self.assertIn("Sandbox-Scope", self.s8)
        self.assertIn("Out-of-Sandbox-Scope", self.s8)
        self.assertIn("Operator-Hand-Sandbox-Gap", self.s8)

    def test_t25_feedback_sandbox_host_trennung_anchored(self) -> None:
        self.assertIn("feedback_sandbox_host_trennung", self.s8)

    def test_t26_adr_anchors_present(self) -> None:
        for adr in self.m.REQUIRED_ADR_ANCHORS:
            self.assertIn(adr, self.s8, f"§8.4 missing ADR anchor {adr}")

    def test_t27_cross_anchor_prs_present(self) -> None:
        for pr in self.m.REQUIRED_CROSS_ANCHOR_PRS:
            self.assertIn(pr, self.s8, f"§8.5 missing cross-anchor PR {pr}")


class TestSignature(unittest.TestCase):
    """Doc carries Tomás-Signature."""

    def setUp(self) -> None:
        self.text = DOC_PATH.read_text(encoding="utf-8")

    def test_t28_tomas_signature_present(self) -> None:
        self.assertIsNotNone(
            re.search(r"^-- Tom[áa]s\s*$", self.text, re.MULTILINE),
            "doc must end with '-- Tomás' signature line",
        )


class TestVerifierNegativePaths(unittest.TestCase):
    """Verifier returns non-zero against deliberately broken docs."""

    def setUp(self) -> None:
        self.text = DOC_PATH.read_text(encoding="utf-8")

    def test_t29_drops_section_three_fails(self) -> None:
        # Strip §3 heading from the doc to force a missing-section error.
        broken = re.sub(r"\n## §3 .*?\n", "\n## REMOVED §3\n", self.text, count=1)
        code, _out, err = _run_verifier_on(broken)
        self.assertEqual(code, 1)
        self.assertIn("§3", err)

    def test_t30_drops_must_not_pin_fails(self) -> None:
        broken = self.text.replace("MUST NOT", "may")
        code, _out, err = _run_verifier_on(broken)
        self.assertEqual(code, 1)
        self.assertIn("MUST NOT", err)

    def test_t31_drops_export_live_emit_one_fails(self) -> None:
        broken = self.text.replace(
            "export WAKIR_OTS_LIVE_EMIT=1",
            "# (toggle removed for test)",
        )
        code, _out, err = _run_verifier_on(broken)
        self.assertEqual(code, 1)
        self.assertIn("WAKIR_OTS_LIVE_EMIT=1", err)

    def test_t32_drops_one_rollback_trigger_fails(self) -> None:
        broken = self.text.replace(
            "R3-Chain-Drift", "R3-RENAMED-Chain-Drift"
        )
        code, _out, err = _run_verifier_on(broken)
        self.assertEqual(code, 1)
        self.assertIn("R3-Chain-Drift", err)

    def test_t33_drops_tomas_signature_fails(self) -> None:
        broken = re.sub(r"^-- Tom[áa]s\s*$", "", self.text, flags=re.MULTILINE)
        code, _out, err = _run_verifier_on(broken)
        self.assertEqual(code, 1)
        self.assertIn("Tomás", err)

    def test_t34_drops_welle_4_reference_fails(self) -> None:
        # Remove the "Welle-4" mentions from §6 but keep the rest.
        broken = self.text.replace("Welle-4", "Welle-FOUR")
        code, _out, err = _run_verifier_on(broken)
        self.assertEqual(code, 1)
        self.assertIn("Welle-4", err)

    def test_t35_drops_adr_0023a_anchor_in_section_8_fails(self) -> None:
        # Replace ADR-0023a only in section 8. §3.3 will still trigger,
        # but we want at least one failure path tied to §8.4 anchors.
        broken = self.text.replace("ADR-0023a", "ADR-XXXX")
        code, _out, err = _run_verifier_on(broken)
        self.assertEqual(code, 1)
        self.assertIn("ADR-0023a", err)


if __name__ == "__main__":
    unittest.main()
