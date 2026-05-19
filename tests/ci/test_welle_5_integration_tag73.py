# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic tests for the Tag-73 Welle-5 Integration-Smoke.

Auftrag-Anker
-------------

Tag-73 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
Hermetic end-to-end simulation of the four Welle-5 substrates that
fire in sequence on the canonical KW-26 Mi 2026-06-24 Welle-5
lifecycle_state_machine Doppel-Welle-4+5 Cutover-Mittwoch pipeline.
The integration-smoke aggregates the Selin Welle-5-Producer, Tomas
Welle-5-Audit-Trail-Anchor, Amara Tag-73 Doppel-Welle-4+5 Coupling-
Gate, and the forward-block-cascade substrate envelopes into a
single trinary WELLE-5 verdict (INTACT / DRIFT / DEFECT).

Brief-vs-canonical reconciliation (Tag-71+72 lehre)
---------------------------------------------------

The Tag-73 brief carried three non-canonical anchors that the
aggregator and these tests reconcile against the repo doku-tree:

* Brief: "Welle-5 Capability-Token (Reza, Zone-L)".
  Canonical: J4 W5 lifecycle_state_machine rust->python
  (Marathon-Rollback-Runbook view); capability_token is parallel
  KW-24-Acceptance view per kw-24-welle-1-7-acceptance-criteria.md
  §5. Tag-72 Welle-4 precedent pinned the Marathon-Rollback-
  Runbook view as canonical; Tag-73 follows the same precedent.
* Brief: state/welle-5.json kw_cutover_anchor=KW-25 implied
  canonical. Actual canonical per pre-cutover-acceptance-run-
  order.md row Welle-5 is KW-26 (Doppel-Welle-4+5). The state-
  file drift is surfaced as a pin-drift marker; the state-file is
  NOT patched (Amara scope: surface, not patch).
* Brief: "Doppel-Welle-4+5 parallel" framing matches canonical.

Tests pin the canonical values verbatim and assert the
``brief_vs_canonical_reconciliation`` envelope field surfaces
all three deltas for the Henrik (Zone-N) audit-evidence trail.

Scope (aggregator + workflow-shape)
-----------------------------------

This module verifies two surfaces:

* The Tag-73 aggregator helper
  (``tooling/ci/aggregate_welle_5_integration.py``):
  - all-green inputs collapse to WELLE-5-INTACT
  - one-yellow inputs collapse to WELLE-5-DRIFT
  - one-red inputs collapse to WELLE-5-DEFECT
  - missing envelope on any stage collapses to WELLE-5-DEFECT
  - unknown verdict on any stage collapses to WELLE-5-DEFECT
  - per-stage notes surface the offending stage + verdict
  - envelope schema fields are present and well-typed
  - substrate-provenance carries the four cross-anchor records
  - parallel-substrate-views carry both Marathon + KW-24 views
  - sandbox-boundary axis is set correctly
  - welle_5_anchor surfaces 2026-06-24 / KW-26 / Welle-5 /
    lifecycle_state_machine / doppel-welle-partner=4
  - forward-cascade fires (5,6,7) on DEFECT only
  - doppel_welle_coupling surface present and well-typed
  - brief_vs_canonical_reconciliation surfaces all three deltas

* The Tag-73 workflow file
  (``.github/workflows/welle-5-integration-smoke.yml``):
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

This test pins only the Tag-73 Welle-5-integration-smoke aggregator
and workflow. It does NOT modify any Welle-5 substrate workflow
(Selin / Tomas domains), the rollback-runbook J4 helper, or the
forward-cascade-rule helpers.

Cross-Review-Markers
--------------------

* Zone-M: QA x Selin -- producer-stage and cascade-stage verdict
  mappings inherit from the Welle-5 state-file producer and the
  forward-cascade-rule. Drift in the trinary verdict-shape is a
  Zone-M signal.
* Zone-M: QA x Tomas -- audit-anchor-stage verdict mapping
  inherits from the Welle-5 audit-trail-anchor wire-helper.
  Drift in the envelope schema is a Zone-M signal.
* Zone-M: QA x Selin+Tomas -- doppel-welle-coupling-gate
  inherits from the Welle-4 state_backing readiness signal.
  Drift in READY/PARTNER-MISSING/PARTNER-DEFECT trinary is a
  Zone-M signal.
* Zone-N: QA x Henrik -- the aggregated WELLE-5-INTEGRATION
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
    REPO_ROOT / "tooling" / "ci" / "aggregate_welle_5_integration.py"
)
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "welle-5-integration-smoke.yml"
)


def _load_aggregator():
    spec = importlib.util.spec_from_file_location(
        "agg_welle_5_integration_tag73", AGGREGATOR_PATH
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
        "welle_5_producer": {"verdict": "WELLE-5-PRODUCER-READY"},
        "welle_5_audit_anchor": {"verdict": "WELLE-5-AUDIT-ANCHOR-READY"},
        "doppel_welle_coupling_gate": {"verdict": "DOPPEL-COUPLING-READY"},
        "downstream_block_cascade": {"verdict": "CASCADE-CONSISTENT"},
    }


class Tag73AggregatorAllGreenTests(unittest.TestCase):
    """All four stages green -> WELLE-5-INTACT."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_all_green_collapses_to_intact(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes(), iso_week=26)
        self.assertEqual(env["verdict"], "WELLE-5-INTACT")
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


class Tag73AggregatorDriftTests(unittest.TestCase):
    """One yellow + rest green -> WELLE-5-DRIFT."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_producer_drift_collapses_to_drift(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_5_producer"] = {"verdict": "WELLE-5-PRODUCER-DRIFT"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DRIFT")
        self.assertEqual(env["counts"]["yellow"], 1)
        self.assertEqual(env["counts"]["red"], 0)
        self.assertIn("welle_5_producer", env["failed_steps"])

    def test_doppel_coupling_partner_missing_maps_to_drift(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["doppel_welle_coupling_gate"] = {
            "verdict": "DOPPEL-COUPLING-PARTNER-MISSING"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DRIFT")
        self.assertEqual(
            env["step_results"]["doppel_welle_coupling_gate"], "yellow"
        )
        self.assertIn(
            "doppel_welle_coupling_gate", env["per_stage_notes"]
        )

    def test_audit_anchor_drift_surfaces_in_failed_steps(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_5_audit_anchor"] = {
            "verdict": "WELLE-5-AUDIT-ANCHOR-DRIFT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DRIFT")
        self.assertIn("welle_5_audit_anchor", env["failed_steps"])

    def test_cascade_drift_surfaces_in_failed_steps(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["downstream_block_cascade"] = {"verdict": "CASCADE-DRIFT"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DRIFT")
        self.assertIn("downstream_block_cascade", env["failed_steps"])

    def test_drift_does_not_arm_cascade(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_5_audit_anchor"] = {
            "verdict": "WELLE-5-AUDIT-ANCHOR-DRIFT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DRIFT")
        self.assertFalse(env["downstream_cascade"]["cascade_armed"])
        self.assertEqual(env["downstream_cascade"]["blocked_wellen_now"], [])


class Tag73AggregatorDefectTests(unittest.TestCase):
    """One red collapses to WELLE-5-DEFECT, and cascade arms."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_audit_anchor_defect_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_5_audit_anchor"] = {
            "verdict": "WELLE-5-AUDIT-ANCHOR-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DEFECT")
        self.assertEqual(env["counts"]["red"], 1)
        self.assertIn("welle_5_audit_anchor", env["failed_steps"])

    def test_doppel_coupling_partner_defect_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["doppel_welle_coupling_gate"] = {
            "verdict": "DOPPEL-COUPLING-PARTNER-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DEFECT")
        self.assertEqual(
            env["step_results"]["doppel_welle_coupling_gate"], "red"
        )

    def test_producer_defect_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_5_producer"] = {
            "verdict": "WELLE-5-PRODUCER-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DEFECT")
        self.assertEqual(env["step_results"]["welle_5_producer"], "red")

    def test_cascade_break_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["downstream_block_cascade"] = {"verdict": "CASCADE-BREAK"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DEFECT")
        self.assertEqual(env["step_results"]["downstream_block_cascade"], "red")

    def test_missing_producer_envelope_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_5_producer"] = None
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DEFECT")
        self.assertEqual(env["step_results"]["welle_5_producer"], "red")
        self.assertIn("missing", env["per_stage_notes"]["welle_5_producer"])

    def test_missing_doppel_coupling_envelope_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["doppel_welle_coupling_gate"] = None
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DEFECT")
        self.assertEqual(
            env["step_results"]["doppel_welle_coupling_gate"], "red"
        )

    def test_unknown_verdict_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_5_producer"] = {"verdict": "WELLE-5-PRODUCER-WAT"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DEFECT")
        self.assertIn(
            "unknown verdict", env["per_stage_notes"]["welle_5_producer"]
        )

    def test_envelope_without_verdict_field_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_5_producer"] = {"not_a_verdict": "wat"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DEFECT")
        self.assertIn(
            "no string", env["per_stage_notes"]["welle_5_producer"]
        )

    def test_red_dominates_yellow(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_5_producer"] = {"verdict": "WELLE-5-PRODUCER-DRIFT"}
        envelopes["welle_5_audit_anchor"] = {
            "verdict": "WELLE-5-AUDIT-ANCHOR-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-5-DEFECT")
        self.assertEqual(env["counts"]["yellow"], 1)
        self.assertEqual(env["counts"]["red"], 1)

    def test_defect_arms_cascade_5_6_7(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_5_audit_anchor"] = {
            "verdict": "WELLE-5-AUDIT-ANCHOR-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertTrue(env["downstream_cascade"]["cascade_armed"])
        self.assertEqual(
            env["downstream_cascade"]["blocked_wellen_now"], [5, 6, 7]
        )


class Tag73EnvelopeShapeTests(unittest.TestCase):
    """Envelope schema and provenance shape."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_envelope_has_required_top_level_keys(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes(), iso_week=26)
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
            "welle_5_anchor",
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
        self.assertEqual(env["workflow"], "welle-5-integration-smoke")
        self.assertEqual(env["tag"], "tag-73")

    def test_welle_5_anchor_carries_kw26_2026_06_24_welle5(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        anchor = env["welle_5_anchor"]
        self.assertEqual(anchor["iso_cutover_date"], "2026-06-24")
        self.assertEqual(anchor["iso_signoff_date"], "2026-06-26")
        self.assertEqual(anchor["iso_week"], 26)
        self.assertEqual(anchor["welle_number"], 5)
        self.assertEqual(anchor["modul"], "lifecycle_state_machine")
        self.assertEqual(anchor["modul_acceptance_view"], "capability_token")
        self.assertEqual(anchor["rollback_job"], "J4")
        self.assertEqual(anchor["doppel_welle_partner"], 4)

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
        self.assertIn("doppel-welle-4-5", prov["kind"])

    def test_parallel_substrate_views_both_present(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        views = env["parallel_substrate_views"]
        self.assertIn("marathon_rollback_runbook_view", views)
        self.assertIn("kw_24_acceptance_view", views)
        marathon = views["marathon_rollback_runbook_view"]
        kw24 = views["kw_24_acceptance_view"]
        self.assertTrue(marathon["is_canonical_for_tag_73"])
        self.assertFalse(kw24["is_canonical_for_tag_73"])
        self.assertEqual(marathon["modul"], "lifecycle_state_machine")
        self.assertEqual(kw24["modul"], "capability_token")

    def test_sandbox_boundary_axis_set_correctly(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        sb = env["sandbox_boundary"]
        self.assertTrue(sb["stdlib_only"])
        self.assertTrue(sb["no_network_io"])
        self.assertTrue(sb["no_actual_welle_5_dispatch"])
        self.assertTrue(sb["no_gh_workflow_run"])
        self.assertEqual(
            sb["boundary_anchor"], "feedback_sandbox_host_trennung.md"
        )

    def test_doppel_welle_coupling_surface_present(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        dwc = env["doppel_welle_coupling"]
        self.assertEqual(dwc["partner_welle"], 4)
        self.assertIn("Doppel-Welle-4+5", dwc["anchor"])
        self.assertIn("one-way", dwc["coupling_direction"])
        self.assertTrue(dwc["partner_defect_blocks_welle_5"])

    def test_input_verdicts_surfaces_raw_strings(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        iv = env["input_verdicts"]
        self.assertEqual(iv["welle_5_producer"], "WELLE-5-PRODUCER-READY")
        self.assertEqual(
            iv["welle_5_audit_anchor"], "WELLE-5-AUDIT-ANCHOR-READY"
        )
        self.assertEqual(
            iv["doppel_welle_coupling_gate"], "DOPPEL-COUPLING-READY"
        )
        self.assertEqual(iv["downstream_block_cascade"], "CASCADE-CONSISTENT")

    def test_input_verdicts_none_on_missing(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_5_producer"] = None
        env = self.mod.build_envelope(envelopes)
        self.assertIsNone(env["input_verdicts"]["welle_5_producer"])

    def test_window_in_welle_5_week_true_for_kw_26(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes(), iso_week=26)
        self.assertTrue(env["window"]["in_welle_5_week"])

    def test_window_in_welle_5_week_false_for_kw_25(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes(), iso_week=25)
        self.assertFalse(env["window"]["in_welle_5_week"])

    def test_emitted_at_utc_iso_format(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        # Verify ISO-8601-with-timezone-offset format.
        self.assertRegex(
            env["emitted_at_utc"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$",
        )


class Tag73CascadeRuleTests(unittest.TestCase):
    """Forward-cascade-rule mapping."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_intact_yields_no_block(self) -> None:
        self.assertEqual(
            self.mod.downstream_blocked_wellen("WELLE-5-INTACT"), ()
        )

    def test_drift_yields_no_block(self) -> None:
        self.assertEqual(
            self.mod.downstream_blocked_wellen("WELLE-5-DRIFT"), ()
        )

    def test_defect_yields_five_through_seven(self) -> None:
        self.assertEqual(
            self.mod.downstream_blocked_wellen("WELLE-5-DEFECT"),
            (5, 6, 7),
        )

    def test_unknown_verdict_yields_no_block(self) -> None:
        # Defensive: any non-DEFECT verdict (including unknown) yields ().
        self.assertEqual(
            self.mod.downstream_blocked_wellen("UNKNOWN"), ()
        )

    def test_forward_cascade_constant_matches_documented_tuple(self) -> None:
        # The constant must pin the (5,6,7) tuple verbatim per
        # docs/quality-gates/phase-3-marathon-anti-patterns.md AP-9
        # analogue + docs/ci/phase-3-marathon-rollback-runbook.md
        # reverse-cutover order J4 (W5 lifecycle_state_machine rollback).
        self.assertEqual(
            self.mod.FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT,
            (5, 6, 7),
        )

    def test_welle_1_2_3_4_not_in_forward_cascade(self) -> None:
        # Welle-1/2/3/4 are upstream of Welle-5 and MUST NOT be in
        # the forward-cascade-set. Note in particular: Welle-4 is
        # the Doppel-Welle partner but is upstream of Welle-5 in
        # the cutover order; the coupling-direction is one-way.
        cascade = self.mod.FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT
        for upstream in (1, 2, 3, 4):
            self.assertNotIn(upstream, cascade)

    def test_welle_5_itself_in_forward_cascade(self) -> None:
        # Welle-5 itself MUST be in the cascade-set (rollback of
        # Welle-5 cancels the Welle-5 cutover).
        cascade = self.mod.FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT
        self.assertIn(5, cascade)


class Tag73BriefReconciliationTests(unittest.TestCase):
    """Brief-vs-canonical reconciliation surface (Tag-71+72 lehre)."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_brief_reconciliation_carries_all_three_deltas(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        recon = env["brief_vs_canonical_reconciliation"]
        self.assertIn("welle_5_modul", recon)
        self.assertIn("welle_5_state_file_kw_anchor", recon)
        self.assertIn("doppel_welle_4_5_framing", recon)

    def test_welle_5_modul_reconciliation_marathon_view_canonical(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        modul_recon = env["brief_vs_canonical_reconciliation"][
            "welle_5_modul"
        ]
        self.assertIn("Capability-Token", modul_recon["brief_value"])
        self.assertIn("lifecycle_state_machine", modul_recon["canonical_value"])
        self.assertIn("J4", modul_recon["canonical_value"])
        self.assertIn(
            "parallel-substrate-evidence", modul_recon["resolution"]
        )

    def test_state_file_kw_anchor_reconciliation_canonical_kw_26(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        kw_recon = env["brief_vs_canonical_reconciliation"][
            "welle_5_state_file_kw_anchor"
        ]
        self.assertIn("KW-25", kw_recon["brief_value"])
        self.assertIn("KW-26", kw_recon["canonical_value"])
        self.assertIn("2026-06-24", kw_recon["canonical_value"])
        # Tag-74 reconciliation: the Tag-73-era 'NOT patched' resolution
        # is superseded; the state-file was PATCHED in Tag-74 per the
        # producer-domain owner (Selin). The post-Tag-74 resolution
        # records that the patch landed via the Tag-74 reconciliation
        # doc; the historical row remains on the envelope as an audit-
        # trail anchor.
        self.assertIn("PATCHED in Tag-74", kw_recon["resolution"])
        self.assertIn(
            "welle-5-kw-anchor-reconciliation-tag74", kw_recon["resolution"]
        )

    def test_doppel_welle_framing_reconciliation_canonical(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        dw_recon = env["brief_vs_canonical_reconciliation"][
            "doppel_welle_4_5_framing"
        ]
        self.assertIn("Doppel-Welle-4+5", dw_recon["brief_value"])
        self.assertIn("Doppel-Welle-4+5", dw_recon["canonical_value"])


class Tag73CliEndToEndTests(unittest.TestCase):
    """CLI surface produces a verdict-envelope on disk."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_cli_writes_intact_verdict_on_all_green(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            paths = {
                "welle_5_producer": tdp / "producer.json",
                "welle_5_audit_anchor": tdp / "audit-anchor.json",
                "doppel_welle_coupling_gate": tdp / "doppel-coupling.json",
                "downstream_block_cascade": tdp / "cascade.json",
            }
            _write_envelope(
                paths["welle_5_producer"], "WELLE-5-PRODUCER-READY"
            )
            _write_envelope(
                paths["welle_5_audit_anchor"], "WELLE-5-AUDIT-ANCHOR-READY"
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
                    "--producer-envelope", str(paths["welle_5_producer"]),
                    "--audit-anchor-envelope", str(paths["welle_5_audit_anchor"]),
                    "--doppel-coupling-envelope", str(paths["doppel_welle_coupling_gate"]),
                    "--cascade-envelope", str(paths["downstream_block_cascade"]),
                    "--iso-week", "26",
                    "--output", str(output),
                ]
            )
            self.assertEqual(rc, 0)
            env = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(env["verdict"], "WELLE-5-INTACT")

    def test_cli_writes_defect_on_missing_envelope_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            paths = {
                "welle_5_audit_anchor": tdp / "audit-anchor.json",
                "doppel_welle_coupling_gate": tdp / "doppel-coupling.json",
                "downstream_block_cascade": tdp / "cascade.json",
            }
            _write_envelope(
                paths["welle_5_audit_anchor"], "WELLE-5-AUDIT-ANCHOR-READY"
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
                    "--audit-anchor-envelope", str(paths["welle_5_audit_anchor"]),
                    "--doppel-coupling-envelope", str(paths["doppel_welle_coupling_gate"]),
                    "--cascade-envelope", str(paths["downstream_block_cascade"]),
                    "--output", str(output),
                ]
            )
            self.assertEqual(rc, 0)
            env = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(env["verdict"], "WELLE-5-DEFECT")
            self.assertEqual(env["step_results"]["welle_5_producer"], "red")

    def test_cli_writes_envelope_with_github_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            paths = {
                "welle_5_producer": tdp / "producer.json",
                "welle_5_audit_anchor": tdp / "audit-anchor.json",
                "doppel_welle_coupling_gate": tdp / "doppel-coupling.json",
                "downstream_block_cascade": tdp / "cascade.json",
            }
            _write_envelope(
                paths["welle_5_producer"], "WELLE-5-PRODUCER-READY"
            )
            _write_envelope(
                paths["welle_5_audit_anchor"], "WELLE-5-AUDIT-ANCHOR-READY"
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
                    "--producer-envelope", str(paths["welle_5_producer"]),
                    "--audit-anchor-envelope", str(paths["welle_5_audit_anchor"]),
                    "--doppel-coupling-envelope", str(paths["doppel_welle_coupling_gate"]),
                    "--cascade-envelope", str(paths["downstream_block_cascade"]),
                    "--github-run-id", "1234567890",
                    "--github-sha", "deadbeefcafef00d",
                    "--github-ref", "refs/heads/amara/tag-73-welle-5-integration-smoke",
                    "--output", str(output),
                ]
            )
            self.assertEqual(rc, 0)
            env = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(env["github_run_id"], "1234567890")
            self.assertEqual(env["github_sha"], "deadbeefcafef00d")
            self.assertEqual(
                env["github_ref"],
                "refs/heads/amara/tag-73-welle-5-integration-smoke",
            )


class Tag73DecideHelperTests(unittest.TestCase):
    """Decide-helper trinary rule, isolated."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_decide_all_green_intact(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        self.assertEqual(self.mod.decide(steps), "WELLE-5-INTACT")

    def test_decide_one_yellow_drift(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        steps["doppel_welle_coupling_gate"] = "yellow"
        self.assertEqual(self.mod.decide(steps), "WELLE-5-DRIFT")

    def test_decide_one_red_defect(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        steps["welle_5_producer"] = "red"
        self.assertEqual(self.mod.decide(steps), "WELLE-5-DEFECT")

    def test_decide_red_dominates_yellow(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        steps["doppel_welle_coupling_gate"] = "yellow"
        steps["welle_5_audit_anchor"] = "red"
        self.assertEqual(self.mod.decide(steps), "WELLE-5-DEFECT")


class Tag73StageOrderingTests(unittest.TestCase):
    """Stage chronological order pins the pipeline-runbook ordering."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_stages_chronological_order(self) -> None:
        # The Tag-73 pipeline-runbook order:
        #   producer -> audit-anchor -> doppel-coupling-gate -> cascade.
        self.assertEqual(
            self.mod.STAGES,
            (
                "welle_5_producer",
                "welle_5_audit_anchor",
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


class Tag73WorkflowShapeTests(unittest.TestCase):
    """Workflow file structural shape (parsed as text)."""

    def setUp(self) -> None:
        self.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_workflow_file_exists(self) -> None:
        self.assertTrue(WORKFLOW_PATH.exists(), msg=str(WORKFLOW_PATH))

    def test_workflow_name_field(self) -> None:
        self.assertIn("name: welle-5-integration-smoke", self.text)

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
        # Tag-73 Stage 3 is doppel-coupling-gate, not snapshot-restore.
        self.assertIn("doppel_coupling", self.text)

    def test_workflow_permissions_read_only(self) -> None:
        self.assertIn("permissions:", self.text)
        self.assertIn("contents: read", self.text)

    def test_workflow_invokes_aggregate_helper(self) -> None:
        self.assertIn(
            "tooling/ci/aggregate_welle_5_integration.py", self.text
        )

    def test_workflow_uploads_envelope_artifact(self) -> None:
        self.assertIn("welle-5-integration-verdict", self.text)
        self.assertIn("upload-artifact@v4", self.text)

    def test_workflow_declares_sandbox_boundary_header(self) -> None:
        # Header must mention the hermetic / sandbox / boundary
        # discipline (per Mira feedback_sandbox_host_trennung.md).
        self.assertIn("hermetic", self.text.lower())
        self.assertIn("sandbox", self.text.lower())

    def test_workflow_invokes_doppel_coupling_stage(self) -> None:
        # Tag-73-specific: Stage 3 is Doppel-Welle-4+5 Coupling-Gate.
        self.assertIn("Doppel-Welle", self.text)
        self.assertIn("doppel_welle_coupling_gate", self.text)

    def test_workflow_declares_continuous_mode_header(self) -> None:
        # Continuous-Mode marathon discipline.
        self.assertIn("Continuous-Mode", self.text)


if __name__ == "__main__":
    unittest.main()
