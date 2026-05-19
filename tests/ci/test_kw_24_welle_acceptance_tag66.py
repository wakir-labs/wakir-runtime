# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic CI-substrate tests for the Tag-66 KW-24 Welle-1..7
Per-Welle Acceptance-Criteria substrate (Amara, Continuous-Mode-Marathon).

Auftrag-Anker
-------------

Tag-66 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
KW-24-Welle-1..7 E2E-Smoke-Schedule + Welle-by-Welle Acceptance-
Criteria-Doc. Pins the per-Welle acceptance-criteria for the
KW-24..KW-27 Cutover-Marathon (T0 = KW-24 Mo 2026-06-08).

Three surfaces under test
-------------------------

* The Tag-66 aggregator helper
  (``tooling/ci/aggregate_kw_24_welle_acceptance.py``):
    - ``VALID_STAGE_STATUSES`` and ``WELLE_RANGE`` are the canonical
      tuples (green/yellow/red, 1..7)
    - ``WELLE_ANCHORS`` maps each Welle to (KW, weekday, focus) per
      ``docs/quality-gates/kw-24-welle-1-7-acceptance-criteria.md``
      §0.3 schedule-table
    - ``decide()`` applies the trinary-verdict-rule (any red -> DEFECT,
      else any yellow -> DRIFT, else READY)
    - ``build_envelope()`` produces a verdict-envelope with the
      documented schema fields, pattern-lineage, cross-substrate-
      links and cross-review-markers
    - Welle-3 DEFECT triggers downstream-block flag listing
      welle-4 / welle-5 / welle-7 (Tag-45 hot-spot family)
    - Welle-3 non-DEFECT (READY/DRIFT) leaves downstream-blocks empty
    - non-3 Wellen never emit downstream-blocks
    - ``_normalize_status()`` fails closed to 'red' on unknown input

* The Tag-66 workflow YAML
  (``.github/workflows/kw-24-welle-acceptance-e2e-smoke-schedule.yml``):
    - declared with workflow_dispatch + schedule + pull_request triggers
    - matrix-strategy fans out over welle 1..7
    - seven cron entries (one per Welle anchor-day)
    - hermetic-test-suite job runs Tag-66 tests before per-welle jobs

* The Tag-66 acceptance-criteria doc
  (``docs/quality-gates/kw-24-welle-1-7-acceptance-criteria.md``):
    - all eight sections §1..§8 present
    - schedule-table covers all seven Wellen
    - Zone-M / Zone-N cross-review markers present

Hermetic posture
----------------

stdlib + unittest. No subprocess into the network. The aggregator
is loaded as a module (same pattern as Tag-63/65 tests). Workflow
YAML and doc are parsed as bytes for marker presence (avoids a
PyYAML dependency in tests).

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This test pins only the Tag-66 per-Welle acceptance substrate.
It does NOT probe persona definitions (Aisha), WAT-core / V-907
(Tomas, Zone-K), identity-substrate (Reza, Zone-L), container-infra
(Kai, Zone-J), or persona-engine substrate (Selin, Zone-O).
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
AGGREGATOR_PATH = os.path.join(
    REPO_ROOT, "tooling", "ci", "aggregate_kw_24_welle_acceptance.py"
)
WORKFLOW_PATH = os.path.join(
    REPO_ROOT,
    ".github",
    "workflows",
    "kw-24-welle-acceptance-e2e-smoke-schedule.yml",
)
DOC_PATH = os.path.join(
    REPO_ROOT,
    "docs",
    "quality-gates",
    "kw-24-welle-1-7-acceptance-criteria.md",
)


def _load_aggregator():
    spec = importlib.util.spec_from_file_location(
        "tag66_aggregator", AGGREGATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError("could not load aggregator spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Tag66AggregatorContractTests(unittest.TestCase):
    """The aggregator helper exports the canonical contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.agg = _load_aggregator()

    def test_aggregator_file_exists(self) -> None:
        self.assertTrue(
            os.path.isfile(AGGREGATOR_PATH),
            f"Tag-66 aggregator missing: {AGGREGATOR_PATH}",
        )

    def test_valid_stage_statuses_tuple(self) -> None:
        self.assertEqual(
            self.agg.VALID_STAGE_STATUSES, ("green", "yellow", "red")
        )

    def test_welle_range_tuple(self) -> None:
        self.assertEqual(self.agg.WELLE_RANGE, (1, 2, 3, 4, 5, 6, 7))

    def test_welle_anchors_complete(self) -> None:
        expected_anchors = {
            1: ("KW-24", "Mo", "engine_cutover"),
            2: ("KW-24", "Mi", "doppelbetrieb_sealing"),
            3: ("KW-24", "Fr", "bridge_audit"),
            4: ("KW-25", "Mo", "state_backing"),
            5: ("KW-25", "Fr", "capability_token"),
            6: ("KW-26", "Fr", "cross_substrate_parity"),
            7: ("KW-27", "Fr", "final_sealing"),
        }
        self.assertEqual(self.agg.WELLE_ANCHORS, expected_anchors)

    def test_welle_3_downstream_blocks_tuple(self) -> None:
        self.assertEqual(self.agg.WELLE_3_DOWNSTREAM_BLOCKS, (4, 5, 7))


class Tag66DecideRuleTests(unittest.TestCase):
    """The trinary-verdict-rule (any red -> DEFECT, etc.)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.agg = _load_aggregator()

    def test_all_green_returns_ready(self) -> None:
        self.assertEqual(
            self.agg.decide(["green", "green", "green", "green"]), "READY"
        )

    def test_any_yellow_returns_drift(self) -> None:
        self.assertEqual(
            self.agg.decide(["green", "yellow", "green", "green"]), "DRIFT"
        )
        self.assertEqual(
            self.agg.decide(["yellow", "yellow", "yellow", "yellow"]),
            "DRIFT",
        )

    def test_any_red_returns_defect(self) -> None:
        self.assertEqual(
            self.agg.decide(["green", "green", "green", "red"]), "DEFECT"
        )
        self.assertEqual(
            self.agg.decide(["red", "yellow", "green", "green"]), "DEFECT"
        )

    def test_red_dominates_yellow(self) -> None:
        # mixed yellow + red still collapses to DEFECT
        self.assertEqual(
            self.agg.decide(["yellow", "yellow", "yellow", "red"]),
            "DEFECT",
        )

    def test_unknown_status_fails_closed_to_red(self) -> None:
        # unknown stage-status normalizes to red -> DEFECT
        self.assertEqual(
            self.agg.decide(["green", "green", "green", "purple"]),
            "DEFECT",
        )

    def test_empty_string_status_fails_closed_to_red(self) -> None:
        self.assertEqual(
            self.agg.decide(["green", "green", "green", ""]),
            "DEFECT",
        )


class Tag66BuildEnvelopeTests(unittest.TestCase):
    """The envelope schema."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.agg = _load_aggregator()

    def test_envelope_has_required_fields(self) -> None:
        env = self.agg.build_envelope(1, "green", "green", "green", "green")
        required = {
            "verdict",
            "welle",
            "anchor_kw",
            "anchor_weekday",
            "substrate_focus",
            "stages",
            "notes",
            "downstream_blocks",
            "pattern_lineage",
            "cross_review_markers",
            "doc_anchor",
        }
        self.assertTrue(required.issubset(env.keys()))

    def test_envelope_welle_1_green_verdict(self) -> None:
        env = self.agg.build_envelope(1, "green", "green", "green", "green")
        self.assertEqual(env["verdict"], "WELLE-1-READY")
        self.assertEqual(env["anchor_kw"], "KW-24")
        self.assertEqual(env["anchor_weekday"], "Mo")
        self.assertEqual(env["substrate_focus"], "engine_cutover")
        self.assertEqual(env["downstream_blocks"], [])

    def test_envelope_welle_3_defect_triggers_downstream_blocks(
        self,
    ) -> None:
        env = self.agg.build_envelope(3, "red", "green", "green", "green")
        self.assertEqual(env["verdict"], "WELLE-3-DEFECT")
        self.assertEqual(
            env["downstream_blocks"], ["welle-4", "welle-5", "welle-7"]
        )

    def test_envelope_welle_3_ready_no_downstream_blocks(self) -> None:
        env = self.agg.build_envelope(
            3, "green", "green", "green", "green"
        )
        self.assertEqual(env["verdict"], "WELLE-3-READY")
        self.assertEqual(env["downstream_blocks"], [])

    def test_envelope_welle_3_drift_no_downstream_blocks(self) -> None:
        # DRIFT does NOT trigger downstream-block (only DEFECT does)
        env = self.agg.build_envelope(
            3, "yellow", "green", "green", "green"
        )
        self.assertEqual(env["verdict"], "WELLE-3-DRIFT")
        self.assertEqual(env["downstream_blocks"], [])

    def test_envelope_non_3_defect_no_downstream_blocks(self) -> None:
        # Welle-4 DEFECT does NOT cascade further (only Welle-3 has
        # the documented downstream-block in this aggregator)
        for welle in (1, 2, 4, 5, 6, 7):
            env = self.agg.build_envelope(
                welle, "red", "green", "green", "green"
            )
            self.assertEqual(env["verdict"], f"WELLE-{welle}-DEFECT")
            self.assertEqual(
                env["downstream_blocks"],
                [],
                f"Welle-{welle} DEFECT should not emit downstream-blocks",
            )

    def test_envelope_welle_out_of_range_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.agg.build_envelope(0, "green", "green", "green", "green")
        with self.assertRaises(ValueError):
            self.agg.build_envelope(8, "green", "green", "green", "green")

    def test_envelope_notes_pairs_serialized(self) -> None:
        env = self.agg.build_envelope(
            2,
            "green",
            "yellow",
            "green",
            "green",
            n2="score-aggregator stale",
        )
        self.assertIn("w2_s2:score-aggregator stale", env["notes"])

    def test_envelope_cross_review_markers_present(self) -> None:
        env = self.agg.build_envelope(7, "green", "green", "green", "green")
        markers = env["cross_review_markers"]
        self.assertTrue(any("zone-M" in m for m in markers))
        self.assertTrue(any("zone-N" in m for m in markers))

    def test_envelope_pattern_lineage_references_tag63_and_tag45(
        self,
    ) -> None:
        env = self.agg.build_envelope(1, "green", "green", "green", "green")
        self.assertIn("tag-63", env["pattern_lineage"])
        self.assertIn("tag-45", env["pattern_lineage"])

    def test_envelope_doc_anchor_points_to_acceptance_doc(self) -> None:
        env = self.agg.build_envelope(1, "green", "green", "green", "green")
        self.assertEqual(
            env["doc_anchor"],
            "docs/quality-gates/kw-24-welle-1-7-acceptance-criteria.md",
        )


class Tag66MainEntryTests(unittest.TestCase):
    """The CLI entry-point reads env-vars and writes JSON output."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.agg = _load_aggregator()

    def test_main_reads_env_and_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "verdict.json")
            old_env = os.environ.copy()
            try:
                os.environ["W4_S1_STATUS"] = "green"
                os.environ["W4_S2_STATUS"] = "yellow"
                os.environ["W4_S3_STATUS"] = "green"
                os.environ["W4_S4_STATUS"] = "green"
                os.environ["W4_S2_NOTE"] = "doppel-welle SEQ chosen"
                rc = self.agg.main(
                    ["--welle", "4", "--output", out_path]
                )
                self.assertEqual(rc, 0)
                with open(out_path, encoding="utf-8") as fh:
                    env = json.load(fh)
                self.assertEqual(env["verdict"], "WELLE-4-DRIFT")
                self.assertEqual(env["welle"], 4)
                self.assertIn("doppel-welle SEQ chosen", env["notes"])
            finally:
                os.environ.clear()
                os.environ.update(old_env)

    def test_main_stdout_when_no_output(self) -> None:
        old_env = os.environ.copy()
        buf = io.StringIO()
        try:
            os.environ["W1_S1_STATUS"] = "green"
            os.environ["W1_S2_STATUS"] = "green"
            os.environ["W1_S3_STATUS"] = "green"
            os.environ["W1_S4_STATUS"] = "green"
            with redirect_stdout(buf):
                rc = self.agg.main(["--welle", "1"])
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["verdict"], "WELLE-1-READY")
        finally:
            os.environ.clear()
            os.environ.update(old_env)


class Tag66WorkflowYamlTests(unittest.TestCase):
    """The workflow YAML has the documented matrix-strategy + cron."""

    @classmethod
    def setUpClass(cls) -> None:
        with open(WORKFLOW_PATH, "rb") as fh:
            cls.data = fh.read()

    def test_workflow_file_exists(self) -> None:
        self.assertTrue(
            os.path.isfile(WORKFLOW_PATH),
            f"Tag-66 workflow YAML missing: {WORKFLOW_PATH}",
        )

    def test_workflow_has_name(self) -> None:
        self.assertIn(
            b"name: kw-24-welle-acceptance-e2e-smoke-schedule", self.data
        )

    def test_workflow_has_workflow_dispatch(self) -> None:
        self.assertIn(b"workflow_dispatch:", self.data)

    def test_workflow_has_schedule_trigger(self) -> None:
        self.assertIn(b"schedule:", self.data)

    def test_workflow_has_seven_cron_entries(self) -> None:
        # Each Welle has one cron entry; should be at least 7 cron lines.
        cron_count = self.data.count(b"- cron:")
        self.assertGreaterEqual(
            cron_count,
            7,
            f"expected >= 7 cron entries (one per Welle), got {cron_count}",
        )

    def test_workflow_has_matrix_strategy_1_to_7(self) -> None:
        self.assertIn(b"matrix:", self.data)
        self.assertIn(b"welle: [1, 2, 3, 4, 5, 6, 7]", self.data)

    def test_workflow_invokes_tag66_aggregator(self) -> None:
        self.assertIn(
            b"tooling/ci/aggregate_kw_24_welle_acceptance.py", self.data
        )

    def test_workflow_runs_hermetic_test_suite(self) -> None:
        self.assertIn(b"test_kw_24_welle_acceptance_tag66.py", self.data)

    def test_workflow_uploads_per_welle_artifact(self) -> None:
        self.assertIn(b"welle-${{ matrix.welle }}-acceptance-verdict", self.data)

    def test_workflow_has_enforce_input(self) -> None:
        self.assertIn(b"enforce:", self.data)


class Tag66AcceptanceCriteriaDocTests(unittest.TestCase):
    """The acceptance-criteria doc has all eight sections + tables."""

    @classmethod
    def setUpClass(cls) -> None:
        with open(DOC_PATH, "rb") as fh:
            cls.data = fh.read()

    def test_doc_file_exists(self) -> None:
        self.assertTrue(
            os.path.isfile(DOC_PATH), f"Tag-66 doc missing: {DOC_PATH}"
        )

    def test_doc_has_all_eight_sections(self) -> None:
        for marker in (
            b"## \xc2\xa71. Welle-1",  # §1 in UTF-8
            b"## \xc2\xa72. Welle-2",
            b"## \xc2\xa73. Welle-3",
            b"## \xc2\xa74. Welle-4",
            b"## \xc2\xa75. Welle-5",
            b"## \xc2\xa76. Welle-6",
            b"## \xc2\xa77. Welle-7",
            b"## \xc2\xa78. Acceptance-Verdict Aggregation",
        ):
            self.assertIn(
                marker, self.data, f"missing section marker: {marker!r}"
            )

    def test_doc_has_schedule_table(self) -> None:
        # The §0.3 schedule-table header
        self.assertIn(b"Anchor-Day", self.data)
        self.assertIn(b"2026-06-08", self.data)  # KW-24 Mo
        self.assertIn(b"2026-07-03", self.data)  # KW-27 Fr

    def test_doc_references_zone_m_and_zone_n(self) -> None:
        self.assertIn(b"Zone-M", self.data)
        self.assertIn(b"Zone-N", self.data)

    def test_doc_references_henrik_audit(self) -> None:
        self.assertIn(b"Henrik", self.data)

    def test_doc_references_tag63_lineage(self) -> None:
        self.assertIn(b"Tag-63", self.data)

    def test_doc_owner_is_amara(self) -> None:
        self.assertIn(b"Amara Osei", self.data)

    def test_doc_amara_signature(self) -> None:
        # Amara signs longer reports with em-dash + name
        self.assertIn(b"\xe2\x80\x94 Amara", self.data)  # — Amara in UTF-8


if __name__ == "__main__":
    unittest.main(verbosity=2)
