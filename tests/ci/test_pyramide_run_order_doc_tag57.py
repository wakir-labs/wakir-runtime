# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic CI tests for the Tag-57 Pre-Cutover Acceptance-Pyramide
Run-Order doc and its verdict-aggregator helper.

Anchors
-------

* Doc: ``docs/quality-gates/pre-cutover-acceptance-run-order.md`` (Tag-57)
* Helper: ``tooling/ci/aggregate_pyramide_run_order_verdict.py`` (Tag-57)
* Auftrag: Tag-57 Amara (Mira, 2026-05-19, Continuous-Mode).

This suite pins:

1. Doc-structural invariants (eight sections, per-Welle table cardinality,
   layer-inventory cardinality, Welle-set cardinality).
2. Helper aggregation invariants (required-layer sets, verdict computation
   for the GREEN / CAUTION / RED outcome-space, escalation routing).
3. Doc <-> Helper coupling invariants (the required-layer sets in the doc
   match the helper's required_layers_for_welle output).
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys
import unittest

# Anchor the doc + helper paths against the repo root (this test-file
# lives at <repo>/tests/ci/...).
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "quality-gates" / "pre-cutover-acceptance-run-order.md"
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "aggregate_pyramide_run_order_verdict.py"


def _load_helper_module():
    spec = importlib.util.spec_from_file_location(
        "aggregate_pyramide_run_order_verdict", HELPER_PATH
    )
    assert spec is not None and spec.loader is not None, (
        f"could not load helper at {HELPER_PATH}"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["aggregate_pyramide_run_order_verdict"] = mod
    spec.loader.exec_module(mod)
    return mod


HELPER = _load_helper_module()


class DocStructuralInvariants(unittest.TestCase):
    """The Tag-57 doc has a fixed structural shape; pin it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = DOC_PATH.read_text(encoding="utf-8")

    def test_01_doc_file_exists_and_nonempty(self) -> None:
        self.assertTrue(DOC_PATH.exists(), f"missing doc: {DOC_PATH}")
        self.assertGreater(len(self.text), 4000, "doc unreasonably short")

    def test_02_doc_has_all_eight_sections(self) -> None:
        # The doc declares eight numbered sections in §1; assert each is present.
        for section_n in range(1, 9):
            header = re.search(rf"^## {section_n}\.\s", self.text, re.MULTILINE)
            self.assertIsNotNone(
                header,
                f"missing top-level section ## {section_n}. in the doc",
            )

    def test_03_doc_anchors_adrs_and_companions(self) -> None:
        for needle in (
            "ADR-0058",
            "ADR-0066",
            "marathon-acceptance-pyramide.md",
            "phase-3-marathon-final-acceptance.md",
        ):
            self.assertIn(needle, self.text, f"doc missing anchor: {needle}")

    def test_04_doc_layer_inventory_has_six_layers_and_sum_167(self) -> None:
        # §2 table lists six layers with test-counts summing to 167.
        # We assert the explicit "**167**" marker (the sum row) and that
        # each layer name appears.
        self.assertIn("**167**", self.text, "doc must list the 167-test sum")
        for name in (
            "State-Machine",
            "Per-Day",
            "Marathon",
            "Anti-Pattern",
            "Pre-Mortem Coverage",
            "Defence-in-Depth Run-Suite",
        ):
            self.assertIn(name, self.text, f"doc missing layer name: {name}")

    def test_05_doc_per_welle_table_lists_all_seven_wellen(self) -> None:
        # §3.2 has a canonical per-Welle run-order table; each Welle-N
        # appears as a leading cell.
        for n in range(1, 8):
            # Table row leading cell: "| Welle-N |"
            self.assertIn(f"| Welle-{n} |", self.text, f"missing row for Welle-{n}")

    def test_06_doc_documents_doppel_welle_entries_2_5_7(self) -> None:
        # Doppel-Welle entries trigger L6-smoke on Pre-Welle.
        for w in (2, 5, 7):
            row_present = re.search(
                rf"\|\s*Welle-{w}\s*\|.*L6-smoke", self.text
            )
            self.assertIsNotNone(
                row_present,
                f"Doppel-Welle-entry Welle-{w} row missing L6-smoke marker",
            )

    def test_07_doc_includes_failure_mode_cascade_matrix_section(self) -> None:
        self.assertIn("## 6.", self.text, "doc missing §6 cascade matrix header")
        self.assertIn("Pre-Welle failure cascade", self.text)
        self.assertIn("Welle-Day failure cascade", self.text)
        self.assertIn("Post-Welle failure cascade", self.text)

    def test_08_doc_includes_sandbox_boundary_section(self) -> None:
        self.assertIn("## 8.", self.text, "doc missing §8 sandbox boundary")
        self.assertIn("operator-hand", self.text.lower())
        self.assertIn("hermetic-ci", self.text.lower())
        self.assertIn("Zone-N", self.text)


class HelperAggregationInvariants(unittest.TestCase):
    """The verdict-aggregator helper pins the doc's §7 semantics."""

    def test_09_required_layers_welle_1_includes_marathon_entry_layers(self) -> None:
        req = HELPER.required_layers_for_welle(1)
        for must in (
            "L1-smoke",
            "L2-dryrun",
            "L4-full",
            "L5-full",
            "L6-full",
            "L2-live",
            "L2-shadow",
            "L2-record-validation",
        ):
            self.assertIn(must, req, f"Welle-1 missing required: {must}")
        # Welle-1 is NOT a Doppel-Welle-entry per the doc.
        self.assertNotIn(
            "L6-smoke", req, "Welle-1 must not require L6-smoke (not a Doppel-entry)"
        )

    def test_10_required_layers_welle_2_5_7_include_l6_smoke(self) -> None:
        for w in (2, 5, 7):
            req = HELPER.required_layers_for_welle(w)
            self.assertIn(
                "L6-smoke", req, f"Welle-{w} (Doppel-entry) must require L6-smoke"
            )
            self.assertIn("L4-smoke", req)
            self.assertNotIn(
                "L4-full",
                req,
                f"Welle-{w} must NOT require L4-full (only Welle-1 does)",
            )

    def test_11_required_layers_welle_3_4_6_no_l6_smoke(self) -> None:
        for w in (3, 4, 6):
            req = HELPER.required_layers_for_welle(w)
            self.assertNotIn(
                "L6-smoke",
                req,
                f"Welle-{w} must NOT require L6-smoke (not a Doppel-entry)",
            )
            self.assertIn("L4-smoke", req)

    def test_12_required_layers_for_global_is_post_welle_7_triple(self) -> None:
        self.assertEqual(
            sorted(HELPER.required_layers_for_global()),
            sorted(["L1-full", "L3-full", "live-verify-gate"]),
        )

    def test_13_welle_verdict_green_happy_path(self) -> None:
        outcomes = {
            "L1-smoke": "GREEN",
            "L2-dryrun": "GREEN",
            "L4-full": "GREEN",
            "L5-full": "GREEN",
            "L6-full": "GREEN",
            "L2-live": "GREEN",
            "L2-shadow": "GREEN",
            "L2-record-validation": "GREEN",
        }
        env = HELPER.compute_welle_verdict(1, outcomes)
        self.assertEqual(env["verdict"], "GREEN")
        self.assertEqual(env["welle_id"], "welle-1")
        self.assertEqual(env["schema_version"], "1.0.0")
        self.assertEqual(env["doc_version"], "tag-57")
        self.assertIsNone(env["escalation"]["target"])

    def test_14_welle_verdict_red_missing_required(self) -> None:
        # Welle-3, omit L4-smoke -> RED with missing-required reason.
        outcomes = {
            "L1-smoke": "GREEN",
            "L2-dryrun": "GREEN",
            "L2-live": "GREEN",
            "L2-shadow": "GREEN",
            "L2-record-validation": "GREEN",
        }
        env = HELPER.compute_welle_verdict(3, outcomes)
        self.assertEqual(env["verdict"], "RED")
        self.assertIn("L4-smoke", env["escalation"]["reason"])

    def test_15_welle_verdict_red_on_l1_smoke_escalates_to_mira(self) -> None:
        outcomes = {
            "L1-smoke": "RED",
            "L2-dryrun": "GREEN",
            "L4-smoke": "GREEN",
            "L2-live": "GREEN",
            "L2-shadow": "GREEN",
            "L2-record-validation": "GREEN",
        }
        env = HELPER.compute_welle_verdict(3, outcomes)
        self.assertEqual(env["verdict"], "RED")
        self.assertEqual(env["escalation"]["target"], "Mira")

    def test_16_welle_verdict_caution_with_caution_layer(self) -> None:
        outcomes = {
            "L1-smoke": "GREEN",
            "L2-dryrun": "GREEN",
            "L4-smoke": "CAUTION",
            "L2-live": "GREEN",
            "L2-shadow": "GREEN",
            "L2-record-validation": "GREEN",
        }
        env = HELPER.compute_welle_verdict(3, outcomes)
        self.assertEqual(env["verdict"], "CAUTION")
        self.assertEqual(env["escalation"]["target"], "Amara")

    def test_17_global_verdict_green_requires_all_welle_green(self) -> None:
        per_welle = {n: "GREEN" for n in range(1, 8)}
        global_outcomes = {
            "L1-full": "GREEN",
            "L3-full": "GREEN",
            "live-verify-gate": "GREEN",
        }
        env = HELPER.compute_global_verdict(per_welle, global_outcomes)
        self.assertEqual(env["verdict"], "GREEN")
        self.assertEqual(env["welle_id"], "global")
        self.assertIsNone(env["escalation"]["target"])

    def test_18_global_verdict_red_when_any_welle_red(self) -> None:
        per_welle = {n: "GREEN" for n in range(1, 8)}
        per_welle[4] = "RED"
        global_outcomes = {
            "L1-full": "GREEN",
            "L3-full": "GREEN",
            "live-verify-gate": "GREEN",
        }
        env = HELPER.compute_global_verdict(per_welle, global_outcomes)
        self.assertEqual(env["verdict"], "RED")
        self.assertIn("Mira", env["escalation"]["target"])

    def test_19_global_verdict_red_when_l1_full_red(self) -> None:
        per_welle = {n: "GREEN" for n in range(1, 8)}
        global_outcomes = {
            "L1-full": "RED",
            "L3-full": "GREEN",
            "live-verify-gate": "GREEN",
        }
        env = HELPER.compute_global_verdict(per_welle, global_outcomes)
        self.assertEqual(env["verdict"], "RED")

    def test_20_global_verdict_caution_when_live_verify_gate_caution(self) -> None:
        per_welle = {n: "GREEN" for n in range(1, 8)}
        global_outcomes = {
            "L1-full": "GREEN",
            "L3-full": "GREEN",
            "live-verify-gate": "CAUTION",
        }
        env = HELPER.compute_global_verdict(per_welle, global_outcomes)
        self.assertEqual(env["verdict"], "CAUTION")
        self.assertIn("Henrik", env["escalation"]["target"])

    def test_21_invalid_outcome_raises(self) -> None:
        with self.assertRaises(ValueError):
            HELPER.compute_welle_verdict(1, {"L1-smoke": "MAYBE"})

    def test_22_invalid_welle_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            HELPER.required_layers_for_welle(0)
        with self.assertRaises(ValueError):
            HELPER.required_layers_for_welle(8)

    def test_23_global_verdict_requires_all_seven_per_welle_keys(self) -> None:
        per_welle = {n: "GREEN" for n in range(1, 7)}  # missing welle-7
        with self.assertRaises(ValueError):
            HELPER.compute_global_verdict(
                per_welle,
                {
                    "L1-full": "GREEN",
                    "L3-full": "GREEN",
                    "live-verify-gate": "GREEN",
                },
            )


class DocHelperCouplingInvariants(unittest.TestCase):
    """The doc's §7.1 required-layer specification and the helper's
    required_layers_for_welle output must match key-by-key.

    This catches drift where the doc adds/removes a required layer
    without updating the helper (or vice versa).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = DOC_PATH.read_text(encoding="utf-8")

    def test_24_doc_mentions_every_helper_required_layer_for_welle_1(self) -> None:
        # All Welle-1 required layers must be named in §3.2's Welle-1 row
        # or in §7.1 "Welle-1 additionally" enumeration.
        for layer in HELPER.required_layers_for_welle(1):
            self.assertIn(
                layer,
                self.text,
                f"helper requires {layer} for Welle-1 but doc never mentions it",
            )

    def test_25_doc_mentions_global_required_triple(self) -> None:
        # The doc uses human-prose forms ("Live-Verify-Gate") while the
        # helper uses kebab-case keys ("live-verify-gate"); compare
        # case-insensitively to assert the global-required-layer triple
        # is referenced in the doc.
        text_lower = self.text.lower()
        for layer in HELPER.required_layers_for_global():
            self.assertIn(
                layer.lower(),
                text_lower,
                f"helper requires global layer {layer} but doc never mentions it",
            )

    def test_26_verdict_envelope_schema_version_is_pinned(self) -> None:
        # Schema version is a contract; if it bumps, downstream consumers
        # (Tomas, Henrik) must be notified. Pin it here.
        self.assertEqual(HELPER.SCHEMA_VERSION, "1.0.0")
        self.assertEqual(HELPER.DOC_VERSION, "tag-57")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
