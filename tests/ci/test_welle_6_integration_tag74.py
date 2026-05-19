# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic tests for the Tag-74 Welle-6 Integration-Smoke.

Auftrag-Anker
-------------

Tag-74 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
Hermetic end-to-end simulation of the four Welle-6 substrates that
fire in sequence on the canonical KW-27 Mi 2026-07-01 Welle-6
subscribe_loop Doppel-Welle-6+7 Cutover-Mittwoch pipeline.
The integration-smoke aggregates the Selin Welle-6-Producer, Tomas
Welle-6-Audit-Trail-Anchor, Amara Tag-74 Doppel-Welle-6+7 Coupling-
Gate, and the forward-block-cascade substrate envelopes into a
single trinary WELLE-6 verdict (INTACT / DRIFT / DEFECT).

Brief-vs-canonical reconciliation (Tag-71+72+73 lehre)
------------------------------------------------------

The Tag-74 brief carried three non-canonical anchors that the
aggregator and these tests reconcile against the repo doku-tree:

* Brief: "Cross-Substrate-Parity-Welle KW-26 Fr".
  Canonical: J3 W6 subscribe_loop rust->python (Marathon-
  Rollback-Runbook view); cross_substrate_parity is parallel
  KW-24-Acceptance view per kw-24-welle-1-7-acceptance-
  criteria.md §6. Tag-72/73 Welle-4/5 precedent pinned the
  Marathon-Rollback-Runbook view as canonical; Tag-74 follows
  the same precedent.
* Brief: Welle-6 is "KW-26 Fr". Canonical per pre-cutover-
  acceptance-run-order.md row Welle-6 + phase-3-marathon-
  final-acceptance.md row KW-27 is KW-27 Mi 2026-07-01
  cutover / KW-27 Fr 2026-07-03 sign-off. The KW-26 framing
  matches the older KW-24-Acceptance §6 chronology which was
  superseded by ADR-0066 Marathon-Cadence.
* Brief: state/welle-6.json kw_cutover_anchor=KW-26 (matches
  brief). Actual canonical is KW-27 (Doppel-Welle-6+7). The
  state-file drift is surfaced as a pin-drift marker; the
  state-file is NOT patched (Amara scope: surface, not patch).

Tests pin the canonical values verbatim and assert the
``brief_vs_canonical_reconciliation`` envelope field surfaces
all three deltas for the Henrik (Zone-N) audit-evidence trail.

Scope (aggregator + workflow-shape)
-----------------------------------

This module verifies two surfaces:

* The Tag-74 aggregator helper
  (``tooling/ci/aggregate_welle_6_integration.py``):
  - all-green inputs collapse to WELLE-6-INTACT
  - one-yellow inputs collapse to WELLE-6-DRIFT
  - one-red inputs collapse to WELLE-6-DEFECT
  - missing envelope on any stage collapses to WELLE-6-DEFECT
  - unknown verdict on any stage collapses to WELLE-6-DEFECT
  - per-stage notes surface the offending stage + verdict
  - envelope schema fields are present and well-typed
  - substrate-provenance carries the four cross-anchor records
  - parallel-substrate-views carry both Marathon + KW-24 views
  - sandbox-boundary axis is set correctly
  - welle_6_anchor surfaces 2026-07-01 / KW-27 / Welle-6 /
    subscribe_loop / doppel-welle-partner=7
  - forward-cascade fires (6,7) on DEFECT only
  - doppel_welle_coupling surface present and well-typed
  - brief_vs_canonical_reconciliation surfaces all three deltas

* The Tag-74 workflow file
  (``.github/workflows/welle-6-integration-smoke.yml``):
  - five named stages present in declared order
  - workflow_dispatch surface includes drift_inject + defect_inject
  - permissions are read-only on contents
  - sandbox-boundary axis declared in header
  - aggregator helper invoked from the aggregate stage
  - artifact upload steps present for both envelope and stages

Hermetic posture
----------------

stdlib + unittest. No subprocess into the network. The aggregator
is loaded as a module via importlib. The workflow is parsed as text.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This test pins only the Tag-74 Welle-6-integration-smoke aggregator
and workflow. It does NOT modify any Welle-6 substrate workflow
(Selin / Tomas domains), the rollback-runbook J3 helper, or the
forward-cascade-rule helpers.

Cross-Review-Markers
--------------------

* Zone-M: QA x Selin -- producer-stage and cascade-stage verdict
  mappings inherit from the Welle-6 state-file producer and the
  forward-cascade-rule. Drift in the trinary verdict-shape is a
  Zone-M signal.
* Zone-M: QA x Tomas -- audit-anchor-stage verdict mapping
  inherits from the Welle-6 audit-trail-anchor wire-helper.
  Drift in the envelope schema is a Zone-M signal.
* Zone-M: QA x Selin+Tomas -- doppel-welle-coupling-gate
  inherits from the Welle-7 recovery_workflow readiness signal.
  Drift in READY/PARTNER-MISSING/PARTNER-DEFECT trinary is a
  Zone-M signal.
* Zone-N: QA x Henrik -- the aggregated WELLE-6-INTEGRATION
  envelope, per-stage envelopes, and the workflow-emitted
  artifacts are Audit-Evidence-Inputs. Drift in their structure
  or completeness is a Zone-N signal.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_PATH = (
    REPO_ROOT / "tooling" / "ci" / "aggregate_welle_6_integration.py"
)
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "welle-6-integration-smoke.yml"
)


def _load_aggregator():
    spec = importlib.util.spec_from_file_location(
        "agg_welle_6_integration_tag74", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_envelope(path: Path, verdict: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"verdict": verdict}, indent=2) + "\n", encoding="utf-8"
    )


def _all_green_envelopes() -> dict:
    return {
        "welle_6_producer": {"verdict": "WELLE-6-PRODUCER-READY"},
        "welle_6_audit_anchor": {"verdict": "WELLE-6-AUDIT-ANCHOR-READY"},
        "doppel_welle_coupling_gate": {"verdict": "DOPPEL-COUPLING-READY"},
        "downstream_block_cascade": {"verdict": "CASCADE-CONSISTENT"},
    }


class Tag74AggregatorAllGreenTests(unittest.TestCase):
    """All four stages green -> WELLE-6-INTACT."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_all_green_collapses_to_intact(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes(), iso_week=27)
        self.assertEqual(env["verdict"], "WELLE-6-INTACT")
        self.assertEqual(env["counts"], {"green": 4, "yellow": 0, "red": 0})
        self.assertEqual(env["failed_steps"], [])
        self.assertEqual(env["per_stage_notes"], {})

    def test_all_green_step_results_all_green(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        for stage in self.mod.STAGES:
            self.assertEqual(env["step_results"][stage], "green")

    def test_all_green_does_not_arm_cascade(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        self.assertFalse(env["downstream_cascade"]["cascade_armed"])
        self.assertEqual(env["downstream_cascade"]["blocked_wellen_now"], [])


class Tag74AggregatorDriftTests(unittest.TestCase):
    """One yellow + rest green -> WELLE-6-DRIFT."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_producer_drift_collapses_to_drift(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_6_producer"] = {"verdict": "WELLE-6-PRODUCER-DRIFT"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DRIFT")
        self.assertEqual(env["counts"]["yellow"], 1)
        self.assertEqual(env["counts"]["red"], 0)
        self.assertIn("welle_6_producer", env["failed_steps"])

    def test_doppel_coupling_partner_missing_maps_to_drift(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["doppel_welle_coupling_gate"] = {
            "verdict": "DOPPEL-COUPLING-PARTNER-MISSING"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DRIFT")
        self.assertEqual(
            env["step_results"]["doppel_welle_coupling_gate"], "yellow"
        )
        self.assertIn(
            "doppel_welle_coupling_gate", env["per_stage_notes"]
        )

    def test_audit_anchor_drift_surfaces_in_failed_steps(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_6_audit_anchor"] = {
            "verdict": "WELLE-6-AUDIT-ANCHOR-DRIFT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DRIFT")
        self.assertIn("welle_6_audit_anchor", env["failed_steps"])

    def test_cascade_drift_surfaces_in_failed_steps(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["downstream_block_cascade"] = {"verdict": "CASCADE-DRIFT"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DRIFT")
        self.assertIn("downstream_block_cascade", env["failed_steps"])

    def test_drift_does_not_arm_cascade(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_6_audit_anchor"] = {
            "verdict": "WELLE-6-AUDIT-ANCHOR-DRIFT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DRIFT")
        self.assertFalse(env["downstream_cascade"]["cascade_armed"])
        self.assertEqual(env["downstream_cascade"]["blocked_wellen_now"], [])


class Tag74AggregatorDefectTests(unittest.TestCase):
    """One red collapses to WELLE-6-DEFECT, and cascade arms."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_audit_anchor_defect_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_6_audit_anchor"] = {
            "verdict": "WELLE-6-AUDIT-ANCHOR-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DEFECT")
        self.assertEqual(env["counts"]["red"], 1)
        self.assertIn("welle_6_audit_anchor", env["failed_steps"])

    def test_doppel_coupling_partner_defect_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["doppel_welle_coupling_gate"] = {
            "verdict": "DOPPEL-COUPLING-PARTNER-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DEFECT")
        self.assertEqual(
            env["step_results"]["doppel_welle_coupling_gate"], "red"
        )

    def test_producer_defect_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_6_producer"] = {
            "verdict": "WELLE-6-PRODUCER-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DEFECT")
        self.assertEqual(env["step_results"]["welle_6_producer"], "red")

    def test_cascade_break_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["downstream_block_cascade"] = {"verdict": "CASCADE-BREAK"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DEFECT")
        self.assertEqual(env["step_results"]["downstream_block_cascade"], "red")

    def test_missing_producer_envelope_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_6_producer"] = None
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DEFECT")
        self.assertEqual(env["step_results"]["welle_6_producer"], "red")
        self.assertIn("missing", env["per_stage_notes"]["welle_6_producer"])

    def test_missing_doppel_coupling_envelope_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["doppel_welle_coupling_gate"] = None
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DEFECT")
        self.assertEqual(
            env["step_results"]["doppel_welle_coupling_gate"], "red"
        )

    def test_unknown_verdict_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_6_producer"] = {"verdict": "WELLE-6-PRODUCER-WAT"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DEFECT")
        self.assertIn(
            "unknown verdict", env["per_stage_notes"]["welle_6_producer"]
        )

    def test_envelope_without_verdict_field_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_6_producer"] = {"not_a_verdict": "wat"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DEFECT")
        self.assertIn(
            "no string", env["per_stage_notes"]["welle_6_producer"]
        )

    def test_red_dominates_yellow(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_6_producer"] = {"verdict": "WELLE-6-PRODUCER-DRIFT"}
        envelopes["welle_6_audit_anchor"] = {
            "verdict": "WELLE-6-AUDIT-ANCHOR-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-6-DEFECT")
        self.assertEqual(env["counts"]["yellow"], 1)
        self.assertEqual(env["counts"]["red"], 1)

    def test_defect_arms_cascade_6_7(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_6_audit_anchor"] = {
            "verdict": "WELLE-6-AUDIT-ANCHOR-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertTrue(env["downstream_cascade"]["cascade_armed"])
        self.assertEqual(
            env["downstream_cascade"]["blocked_wellen_now"], [6, 7]
        )


class Tag74EnvelopeShapeTests(unittest.TestCase):
    """Envelope schema and provenance shape."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_envelope_has_required_top_level_keys(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes(), iso_week=27)
        required = {
            "schema_version",
            "workflow",
            "tag",
            "emitted_at_utc",
            "verdict",
            "step_results",
            "failed_steps",
            "per_stage_notes",
            "counts",
            "welle_6_anchor",
            "window",
            "input_verdicts",
            "substrate_provenance",
            "parallel_substrate_views",
            "doppel_welle_coupling",
            "downstream_cascade",
            "decision_rule",
            "brief_vs_canonical_reconciliation",
            "sandbox_boundary",
        }
        self.assertTrue(required.issubset(env.keys()))

    def test_envelope_workflow_field_matches_workflow_name(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        self.assertEqual(env["workflow"], "welle-6-integration-smoke")
        self.assertEqual(env["tag"], "tag-74")

    def test_welle_6_anchor_carries_kw27_2026_07_01_welle6(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        anchor = env["welle_6_anchor"]
        self.assertEqual(anchor["iso_cutover_date"], "2026-07-01")
        self.assertEqual(anchor["iso_signoff_date"], "2026-07-03")
        self.assertEqual(anchor["iso_week"], 27)
        self.assertEqual(anchor["welle_number"], 6)
        self.assertEqual(anchor["modul"], "subscribe_loop")
        self.assertEqual(
            anchor["modul_acceptance_view"], "cross_substrate_parity"
        )
        self.assertEqual(anchor["rollback_job"], "J3")
        self.assertEqual(anchor["doppel_welle_partner"], 7)

    def test_substrate_provenance_carries_four_anchors(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        prov = env["substrate_provenance"]
        for stage in self.mod.STAGES:
            self.assertIn(stage, prov)
            self.assertIn("owner", prov[stage])
            self.assertIn("tag", prov[stage])
            self.assertIn("kind", prov[stage])

    def test_substrate_provenance_doppel_coupling_owned_by_amara(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        prov = env["substrate_provenance"]["doppel_welle_coupling_gate"]
        self.assertEqual(prov["owner"], "Amara")
        self.assertIn("doppel-welle-6-7", prov["kind"])

    def test_parallel_substrate_views_both_present(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        views = env["parallel_substrate_views"]
        self.assertIn("marathon_rollback_runbook_view", views)
        self.assertIn("kw_24_acceptance_view", views)
        marathon = views["marathon_rollback_runbook_view"]
        kw24 = views["kw_24_acceptance_view"]
        self.assertTrue(marathon["is_canonical_for_tag_74"])
        self.assertFalse(kw24["is_canonical_for_tag_74"])
        self.assertEqual(marathon["modul"], "subscribe_loop")
        self.assertEqual(kw24["modul"], "cross_substrate_parity")

    def test_sandbox_boundary_axis_set_correctly(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        sb = env["sandbox_boundary"]
        self.assertTrue(sb["stdlib_only"])
        self.assertTrue(sb["no_network_io"])
        self.assertTrue(sb["no_actual_welle_6_dispatch"])
        self.assertTrue(sb["no_gh_workflow_run"])
        self.assertEqual(
            sb["boundary_anchor"], "feedback_sandbox_host_trennung.md"
        )

    def test_doppel_welle_coupling_surface_present(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        dwc = env["doppel_welle_coupling"]
        self.assertEqual(dwc["partner_welle"], 7)
        self.assertIn("Doppel-Welle-6+7", dwc["anchor"])
        self.assertIn("bi-directional", dwc["coupling_direction"])
        self.assertTrue(dwc["partner_defect_blocks_welle_6"])
        self.assertIn("ADR-0066", dwc["par_path_anchor"])
        self.assertIn("phase-3c-doppel-welle-6-7", dwc["seq_path_anchor"])

    def test_input_verdicts_surfaces_raw_strings(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        iv = env["input_verdicts"]
        self.assertEqual(iv["welle_6_producer"], "WELLE-6-PRODUCER-READY")
        self.assertEqual(
            iv["welle_6_audit_anchor"], "WELLE-6-AUDIT-ANCHOR-READY"
        )
        self.assertEqual(
            iv["doppel_welle_coupling_gate"], "DOPPEL-COUPLING-READY"
        )
        self.assertEqual(iv["downstream_block_cascade"], "CASCADE-CONSISTENT")

    def test_input_verdicts_none_on_missing(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_6_producer"] = None
        env = self.mod.build_envelope(envelopes)
        self.assertIsNone(env["input_verdicts"]["welle_6_producer"])

    def test_window_in_welle_6_week_true_for_kw_27(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes(), iso_week=27)
        self.assertTrue(env["window"]["in_welle_6_week"])

    def test_window_in_welle_6_week_false_for_kw_26(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes(), iso_week=26)
        self.assertFalse(env["window"]["in_welle_6_week"])

    def test_emitted_at_utc_iso_format(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        # Verify ISO-8601-with-timezone-offset format.
        self.assertRegex(
            env["emitted_at_utc"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$",
        )


class Tag74CascadeRuleTests(unittest.TestCase):
    """Forward-cascade-rule mapping."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_intact_yields_no_block(self) -> None:
        self.assertEqual(
            self.mod.downstream_blocked_wellen("WELLE-6-INTACT"), ()
        )

    def test_drift_yields_no_block(self) -> None:
        self.assertEqual(
            self.mod.downstream_blocked_wellen("WELLE-6-DRIFT"), ()
        )

    def test_defect_yields_six_through_seven(self) -> None:
        self.assertEqual(
            self.mod.downstream_blocked_wellen("WELLE-6-DEFECT"),
            (6, 7),
        )

    def test_unknown_verdict_yields_no_block(self) -> None:
        # Defensive: any non-DEFECT verdict (including unknown) yields ().
        self.assertEqual(
            self.mod.downstream_blocked_wellen("UNKNOWN"), ()
        )

    def test_forward_cascade_constant_matches_documented_tuple(self) -> None:
        # The constant must pin the (6,7) tuple verbatim per
        # docs/quality-gates/phase-3-marathon-anti-patterns.md AP-9
        # analogue + docs/ci/phase-3-marathon-rollback-runbook.md
        # reverse-cutover order J3 (W6 subscribe_loop rollback).
        self.assertEqual(
            self.mod.FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT,
            (6, 7),
        )

    def test_welle_1_through_5_not_in_forward_cascade(self) -> None:
        # Welle-1/2/3/4/5 are upstream of Welle-6 and MUST NOT be in
        # the forward-cascade-set.
        cascade = self.mod.FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT
        for upstream in (1, 2, 3, 4, 5):
            self.assertNotIn(upstream, cascade)

    def test_welle_6_itself_in_forward_cascade(self) -> None:
        # Welle-6 itself MUST be in the cascade-set (rollback of
        # Welle-6 cancels the Welle-6 cutover).
        cascade = self.mod.FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT
        self.assertIn(6, cascade)

    def test_welle_7_in_forward_cascade_doppel_welle_symmetry(self) -> None:
        # Tag-74 specific: Welle-7 IS in the forward-cascade-set
        # (Doppel-Welle-6+7 symmetric coupling under PAR-path). This
        # differs from Tag-73 Welle-5 (Welle-4 was NOT in cascade).
        cascade = self.mod.FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT
        self.assertIn(7, cascade)


class Tag74BriefReconciliationTests(unittest.TestCase):
    """Brief-vs-canonical reconciliation surface (Tag-71+72+73 lehre)."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_brief_reconciliation_carries_all_three_deltas(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        recon = env["brief_vs_canonical_reconciliation"]
        self.assertIn("welle_6_modul", recon)
        self.assertIn("welle_6_kw_anchor", recon)
        self.assertIn("welle_6_state_file_kw_anchor", recon)

    def test_welle_6_modul_reconciliation_marathon_view_canonical(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        modul_recon = env["brief_vs_canonical_reconciliation"][
            "welle_6_modul"
        ]
        self.assertIn("Cross-Substrate-Parity", modul_recon["brief_value"])
        self.assertIn("subscribe_loop", modul_recon["canonical_value"])
        self.assertIn("J3", modul_recon["canonical_value"])
        self.assertIn(
            "parallel-substrate-evidence", modul_recon["resolution"]
        )

    def test_welle_6_kw_anchor_reconciliation_canonical_kw_27(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        kw_recon = env["brief_vs_canonical_reconciliation"][
            "welle_6_kw_anchor"
        ]
        self.assertIn("KW-26", kw_recon["brief_value"])
        self.assertIn("KW-27", kw_recon["canonical_value"])
        self.assertIn("2026-07-01", kw_recon["canonical_value"])
        self.assertIn("ADR-0066", kw_recon["resolution"])

    def test_state_file_kw_anchor_reconciliation_canonical_kw_27(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        sf_recon = env["brief_vs_canonical_reconciliation"][
            "welle_6_state_file_kw_anchor"
        ]
        self.assertIn("KW-26", sf_recon["brief_value"])
        self.assertIn("KW-27", sf_recon["canonical_value"])
        self.assertIn("2026-07-01", sf_recon["canonical_value"])
        self.assertIn("NOT patched", sf_recon["resolution"])


class Tag74CliEndToEndTests(unittest.TestCase):
    """CLI surface produces a verdict-envelope on disk."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_cli_writes_intact_verdict_on_all_green(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            paths = {
                "welle_6_producer": tdp / "producer.json",
                "welle_6_audit_anchor": tdp / "audit-anchor.json",
                "doppel_welle_coupling_gate": tdp / "doppel-coupling.json",
                "downstream_block_cascade": tdp / "cascade.json",
            }
            _write_envelope(
                paths["welle_6_producer"], "WELLE-6-PRODUCER-READY"
            )
            _write_envelope(
                paths["welle_6_audit_anchor"], "WELLE-6-AUDIT-ANCHOR-READY"
            )
            _write_envelope(
                paths["doppel_welle_coupling_gate"], "DOPPEL-COUPLING-READY"
            )
            _write_envelope(
                paths["downstream_block_cascade"], "CASCADE-CONSISTENT"
            )
            output = tdp / "verdict.json"
            rc = self.mod.main(
                [
                    "--producer-envelope", str(paths["welle_6_producer"]),
                    "--audit-anchor-envelope", str(paths["welle_6_audit_anchor"]),
                    "--doppel-coupling-envelope", str(paths["doppel_welle_coupling_gate"]),
                    "--cascade-envelope", str(paths["downstream_block_cascade"]),
                    "--iso-week", "27",
                    "--output", str(output),
                ]
            )
            self.assertEqual(rc, 0)
            env = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(env["verdict"], "WELLE-6-INTACT")

    def test_cli_writes_defect_on_missing_envelope_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            paths = {
                "welle_6_audit_anchor": tdp / "audit-anchor.json",
                "doppel_welle_coupling_gate": tdp / "doppel-coupling.json",
                "downstream_block_cascade": tdp / "cascade.json",
            }
            _write_envelope(
                paths["welle_6_audit_anchor"], "WELLE-6-AUDIT-ANCHOR-READY"
            )
            _write_envelope(
                paths["doppel_welle_coupling_gate"], "DOPPEL-COUPLING-READY"
            )
            _write_envelope(
                paths["downstream_block_cascade"], "CASCADE-CONSISTENT"
            )
            output = tdp / "verdict.json"
            # NOTE: producer-envelope intentionally omitted.
            rc = self.mod.main(
                [
                    "--audit-anchor-envelope", str(paths["welle_6_audit_anchor"]),
                    "--doppel-coupling-envelope", str(paths["doppel_welle_coupling_gate"]),
                    "--cascade-envelope", str(paths["downstream_block_cascade"]),
                    "--output", str(output),
                ]
            )
            self.assertEqual(rc, 0)
            env = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(env["verdict"], "WELLE-6-DEFECT")
            self.assertEqual(env["step_results"]["welle_6_producer"], "red")

    def test_cli_writes_envelope_with_github_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            paths = {
                "welle_6_producer": tdp / "producer.json",
                "welle_6_audit_anchor": tdp / "audit-anchor.json",
                "doppel_welle_coupling_gate": tdp / "doppel-coupling.json",
                "downstream_block_cascade": tdp / "cascade.json",
            }
            _write_envelope(
                paths["welle_6_producer"], "WELLE-6-PRODUCER-READY"
            )
            _write_envelope(
                paths["welle_6_audit_anchor"], "WELLE-6-AUDIT-ANCHOR-READY"
            )
            _write_envelope(
                paths["doppel_welle_coupling_gate"], "DOPPEL-COUPLING-READY"
            )
            _write_envelope(
                paths["downstream_block_cascade"], "CASCADE-CONSISTENT"
            )
            output = tdp / "verdict.json"
            rc = self.mod.main(
                [
                    "--producer-envelope", str(paths["welle_6_producer"]),
                    "--audit-anchor-envelope", str(paths["welle_6_audit_anchor"]),
                    "--doppel-coupling-envelope", str(paths["doppel_welle_coupling_gate"]),
                    "--cascade-envelope", str(paths["downstream_block_cascade"]),
                    "--github-run-id", "1234567890",
                    "--github-sha", "deadbeefcafef00d",
                    "--github-ref", "refs/heads/amara/tag-74-welle-6-integration-smoke",
                    "--output", str(output),
                ]
            )
            self.assertEqual(rc, 0)
            env = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(env["github_run_id"], "1234567890")
            self.assertEqual(env["github_sha"], "deadbeefcafef00d")
            self.assertEqual(
                env["github_ref"],
                "refs/heads/amara/tag-74-welle-6-integration-smoke",
            )


class Tag74DecideHelperTests(unittest.TestCase):
    """Decide-helper trinary rule, isolated."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_decide_all_green_intact(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        self.assertEqual(self.mod.decide(steps), "WELLE-6-INTACT")

    def test_decide_one_yellow_drift(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        steps["doppel_welle_coupling_gate"] = "yellow"
        self.assertEqual(self.mod.decide(steps), "WELLE-6-DRIFT")

    def test_decide_one_red_defect(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        steps["welle_6_producer"] = "red"
        self.assertEqual(self.mod.decide(steps), "WELLE-6-DEFECT")

    def test_decide_red_dominates_yellow(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        steps["doppel_welle_coupling_gate"] = "yellow"
        steps["welle_6_audit_anchor"] = "red"
        self.assertEqual(self.mod.decide(steps), "WELLE-6-DEFECT")


class Tag74StageOrderingTests(unittest.TestCase):
    """Stage chronological order pins the pipeline-runbook ordering."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_stages_chronological_order(self) -> None:
        # The Tag-74 pipeline-runbook order:
        #   producer -> audit-anchor -> doppel-coupling-gate -> cascade.
        self.assertEqual(
            self.mod.STAGES,
            (
                "welle_6_producer",
                "welle_6_audit_anchor",
                "doppel_welle_coupling_gate",
                "downstream_block_cascade",
            ),
        )

    def test_stage_verdict_maps_cover_all_stages(self) -> None:
        for stage in self.mod.STAGES:
            self.assertIn(stage, self.mod.STAGE_VERDICT_MAPS)
            self.assertGreaterEqual(len(self.mod.STAGE_VERDICT_MAPS[stage]), 3)

    def test_step_results_preserves_stage_order_on_iteration(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        self.assertEqual(
            list(env["step_results"].keys()),
            list(self.mod.STAGES),
        )


class Tag74WorkflowShapeTests(unittest.TestCase):
    """Workflow file structural shape (parsed as text)."""

    def setUp(self) -> None:
        self.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_workflow_file_exists(self) -> None:
        self.assertTrue(WORKFLOW_PATH.exists(), msg=str(WORKFLOW_PATH))

    def test_workflow_name_field(self) -> None:
        self.assertIn("name: welle-6-integration-smoke", self.text)

    def test_workflow_declares_five_stages(self) -> None:
        # Stages 1..4 substantive + Stage 5 aggregate.
        for marker in (
            "Stage 1",
            "Stage 2",
            "Stage 3",
            "Stage 4",
            "Stage 5",
        ):
            self.assertIn(marker, self.text)

    def test_workflow_dispatch_inputs_include_inject_axes(self) -> None:
        self.assertIn("drift_inject", self.text)
        self.assertIn("defect_inject", self.text)

    def test_workflow_dispatch_inject_axes_include_doppel_coupling(self) -> None:
        # Tag-74 Stage 3 is doppel-coupling-gate, not snapshot-restore.
        self.assertIn("doppel_coupling", self.text)

    def test_workflow_permissions_read_only(self) -> None:
        self.assertIn("permissions:", self.text)
        self.assertIn("contents: read", self.text)

    def test_workflow_invokes_aggregate_helper(self) -> None:
        self.assertIn(
            "tooling/ci/aggregate_welle_6_integration.py", self.text
        )

    def test_workflow_uploads_envelope_artifact(self) -> None:
        self.assertIn("welle-6-integration-verdict", self.text)
        self.assertIn("upload-artifact@v4", self.text)

    def test_workflow_declares_sandbox_boundary_header(self) -> None:
        # Header must mention the hermetic / sandbox / boundary
        # discipline (per Mira feedback_sandbox_host_trennung.md).
        self.assertIn("hermetic", self.text.lower())
        self.assertIn("sandbox", self.text.lower())

    def test_workflow_invokes_doppel_coupling_stage(self) -> None:
        # Tag-74-specific: Stage 3 is Doppel-Welle-6+7 Coupling-Gate.
        self.assertIn("Doppel-Welle", self.text)
        self.assertIn("doppel_welle_coupling_gate", self.text)

    def test_workflow_declares_continuous_mode_header(self) -> None:
        # Continuous-Mode marathon discipline.
        self.assertIn("Continuous-Mode", self.text)

    def test_workflow_iso_week_pinned_to_27(self) -> None:
        # Tag-74 must pin iso_week=27 (not 26) per pre-cutover-
        # acceptance-run-order.md row Welle-6 (Doppel-Welle-6+7).
        self.assertIn("--iso-week 27", self.text)


if __name__ == "__main__":
    unittest.main()
