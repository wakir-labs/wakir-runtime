# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic tests for the Tag-72 Welle-4 Integration-Smoke.

Auftrag-Anker
-------------

Tag-72 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
Hermetic end-to-end simulation of the four Welle-4 substrates that
fire in sequence on the canonical KW-26 Mi 2026-06-24 Welle-4
State-Backing Doppel-Welle-4+5 Cutover-Mittwoch pipeline. The
integration-smoke aggregates the Selin Welle-4-Producer, Tomas
Welle-4-Audit-Trail-Anchor, Tomas Tag-56 §J5 Snapshot-Restore-
Pflicht-Gate, and the forward-block-cascade substrate envelopes
into a single trinary WELLE-4 verdict (INTACT / DRIFT / DEFECT).

Brief-vs-canonical reconciliation (Tag-71 lehre)
------------------------------------------------

The Tag-72 brief carried two non-canonical anchors that the
aggregator and these tests reconcile against the repo doku-tree:

* Brief: "Welle-4 KW-25 Mo".
  Canonical: KW-26 Mi 2026-06-24 cutover / KW-26 Fr 2026-06-26
  sign-off (per ``docs/quality-gates/phase-3-marathon-final-
  acceptance.md`` Marathon-Cadence row KW-26 + ``docs/quality-
  gates/pre-cutover-acceptance-run-order.md``). Doppel-Welle-4+5
  parallel with Welle-5 lifecycle_state_machine.
* Brief: "Tomas-Tag-56 Rollback-Workflow §J4".
  Canonical: §J5 W4 state_backing rust->python + snapshot-restore-
  planned (per ``docs/ci/phase-3-marathon-rollback-runbook.md``
  Job-Graph; §J4 is W5 lifecycle_state_machine).

Tests pin the canonical values verbatim and assert the
``brief_vs_canonical_reconciliation`` envelope field surfaces
both deltas for the Henrik (Zone-N) audit-evidence trail.

Scope (aggregator + workflow-shape)
-----------------------------------

This module verifies two surfaces:

* The Tag-72 aggregator helper
  (``tooling/ci/aggregate_welle_4_integration.py``):
  - all-green inputs collapse to WELLE-4-INTACT
  - one-yellow inputs collapse to WELLE-4-DRIFT
  - one-red inputs collapse to WELLE-4-DEFECT
  - missing envelope on any stage collapses to WELLE-4-DEFECT
  - unknown verdict on any stage collapses to WELLE-4-DEFECT
  - per-stage notes surface the offending stage + verdict
  - envelope schema fields are present and well-typed
  - substrate-provenance carries the four cross-anchor records
  - sandbox-boundary axis is set correctly
  - welle_4_anchor surfaces 2026-06-24 / KW-26 / Welle-4 /
    state_backing / doppel-welle-partner=5
  - forward-cascade fires (4,5,6,7) on DEFECT only
  - snapshot_restore_pflicht surface present and well-typed
  - brief_vs_canonical_reconciliation surfaces both deltas

* The Tag-72 workflow file
  (``.github/workflows/welle-4-integration-smoke.yml``):
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

This test pins only the Tag-72 Welle-4-integration-smoke aggregator
and workflow. It does NOT modify any Welle-4 substrate workflow
(Selin / Tomas domains), the Tag-56 rollback-runbook §J5 helper,
or the forward-cascade-rule helpers.

Cross-Review-Markers
--------------------

* Zone-M: QA x Selin -- producer-stage and cascade-stage verdict
  mappings inherit from the Welle-4 state-file producer and the
  forward-cascade-rule. Drift in the trinary verdict-shape is a
  Zone-M signal.
* Zone-M: QA x Tomas -- audit-anchor-stage + snapshot-restore-gate
  verdict mappings inherit from the Welle-4 audit-trail-anchor
  wire-helper and the Tag-56 rollback-runbook §J5 surface.
  Drift in the envelope schema or READY/PLANNED-MISSING/PLAN-
  DEFECT trinary is a Zone-M signal.
* Zone-N: QA x Henrik -- the aggregated WELLE-4-INTEGRATION
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
    REPO_ROOT / "tooling" / "ci" / "aggregate_welle_4_integration.py"
)
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "welle-4-integration-smoke.yml"
)


def _load_aggregator():
    spec = importlib.util.spec_from_file_location(
        "agg_welle_4_integration_tag72", AGGREGATOR_PATH
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
        "welle_4_producer": {"verdict": "WELLE-4-PRODUCER-READY"},
        "welle_4_audit_anchor": {"verdict": "WELLE-4-AUDIT-ANCHOR-READY"},
        "snapshot_restore_gate": {"verdict": "SNAPSHOT-RESTORE-READY"},
        "downstream_block_cascade": {"verdict": "CASCADE-CONSISTENT"},
    }


class Tag72AggregatorAllGreenTests(unittest.TestCase):
    """All four stages green -> WELLE-4-INTACT."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_all_green_collapses_to_intact(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes(), iso_week=26)
        self.assertEqual(env["verdict"], "WELLE-4-INTACT")
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


class Tag72AggregatorDriftTests(unittest.TestCase):
    """One yellow + rest green -> WELLE-4-DRIFT."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_producer_drift_collapses_to_drift(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_4_producer"] = {"verdict": "WELLE-4-PRODUCER-DRIFT"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-4-DRIFT")
        self.assertEqual(env["counts"]["yellow"], 1)
        self.assertEqual(env["counts"]["red"], 0)
        self.assertIn("welle_4_producer", env["failed_steps"])

    def test_snapshot_restore_planned_missing_maps_to_drift(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["snapshot_restore_gate"] = {
            "verdict": "SNAPSHOT-RESTORE-PLANNED-MISSING"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-4-DRIFT")
        self.assertEqual(env["step_results"]["snapshot_restore_gate"], "yellow")
        self.assertIn(
            "snapshot_restore_gate", env["per_stage_notes"]
        )

    def test_cascade_drift_surfaces_in_failed_steps(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["downstream_block_cascade"] = {"verdict": "CASCADE-DRIFT"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-4-DRIFT")
        self.assertIn("downstream_block_cascade", env["failed_steps"])

    def test_drift_does_not_arm_cascade(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_4_audit_anchor"] = {
            "verdict": "WELLE-4-AUDIT-ANCHOR-DRIFT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-4-DRIFT")
        self.assertFalse(env["downstream_cascade"]["cascade_armed"])
        self.assertEqual(env["downstream_cascade"]["blocked_wellen_now"], [])


class Tag72AggregatorDefectTests(unittest.TestCase):
    """One red collapses to WELLE-4-DEFECT, and cascade arms."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_audit_anchor_defect_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_4_audit_anchor"] = {
            "verdict": "WELLE-4-AUDIT-ANCHOR-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-4-DEFECT")
        self.assertEqual(env["counts"]["red"], 1)
        self.assertIn("welle_4_audit_anchor", env["failed_steps"])

    def test_snapshot_restore_plan_defect_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["snapshot_restore_gate"] = {
            "verdict": "SNAPSHOT-RESTORE-PLAN-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-4-DEFECT")
        self.assertEqual(env["step_results"]["snapshot_restore_gate"], "red")

    def test_missing_producer_envelope_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_4_producer"] = None
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-4-DEFECT")
        self.assertEqual(env["step_results"]["welle_4_producer"], "red")
        self.assertIn("missing", env["per_stage_notes"]["welle_4_producer"])

    def test_unknown_verdict_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_4_producer"] = {"verdict": "WELLE-4-PRODUCER-WAT"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-4-DEFECT")
        self.assertIn("unknown verdict", env["per_stage_notes"]["welle_4_producer"])

    def test_red_dominates_yellow(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_4_producer"] = {"verdict": "WELLE-4-PRODUCER-DRIFT"}
        envelopes["welle_4_audit_anchor"] = {
            "verdict": "WELLE-4-AUDIT-ANCHOR-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-4-DEFECT")
        self.assertEqual(env["counts"]["yellow"], 1)
        self.assertEqual(env["counts"]["red"], 1)

    def test_defect_arms_cascade_4_5_6_7(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_4_audit_anchor"] = {
            "verdict": "WELLE-4-AUDIT-ANCHOR-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertTrue(env["downstream_cascade"]["cascade_armed"])
        self.assertEqual(
            env["downstream_cascade"]["blocked_wellen_now"], [4, 5, 6, 7]
        )


class Tag72EnvelopeShapeTests(unittest.TestCase):
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
            "welle_4_anchor",
            "window",
            "input_verdicts",
            "substrate_provenance",
            "snapshot_restore_pflicht",
            "downstream_cascade",
            "decision_rule",
            "brief_vs_canonical_reconciliation",
            "sandbox_boundary",
        }
        self.assertTrue(required.issubset(env.keys()))

    def test_envelope_workflow_field_matches_workflow_name(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        self.assertEqual(env["workflow"], "welle-4-integration-smoke")
        self.assertEqual(env["tag"], "tag-72")

    def test_welle_4_anchor_carries_kw26_2026_06_24_welle4(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        anchor = env["welle_4_anchor"]
        self.assertEqual(anchor["iso_cutover_date"], "2026-06-24")
        self.assertEqual(anchor["iso_signoff_date"], "2026-06-26")
        self.assertEqual(anchor["iso_week"], 26)
        self.assertEqual(anchor["welle_number"], 4)
        self.assertEqual(anchor["modul"], "state_backing")
        self.assertEqual(anchor["doppel_welle_partner"], 5)

    def test_substrate_provenance_carries_four_anchors(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        prov = env["substrate_provenance"]
        for stage in self.mod.STAGES:
            self.assertIn(stage, prov)
            self.assertIn("owner", prov[stage])
            self.assertIn("tag", prov[stage])
            self.assertIn("kind", prov[stage])

    def test_sandbox_boundary_axis_set_correctly(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        sb = env["sandbox_boundary"]
        self.assertTrue(sb["stdlib_only"])
        self.assertTrue(sb["no_network_io"])
        self.assertTrue(sb["no_actual_welle_4_dispatch"])
        self.assertTrue(sb["no_gh_workflow_run"])
        self.assertEqual(sb["boundary_anchor"], "feedback_sandbox_host_trennung.md")

    def test_snapshot_restore_pflicht_surface_present(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        srp = env["snapshot_restore_pflicht"]
        self.assertIn("J5", srp["anchor"])
        self.assertIn("state_backing", srp["anchor"])
        self.assertIn("snapshot-restore-planned", srp["anchor"])
        self.assertTrue(srp["welle_4_required"])

    def test_input_verdicts_surfaces_raw_strings(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        iv = env["input_verdicts"]
        self.assertEqual(iv["welle_4_producer"], "WELLE-4-PRODUCER-READY")
        self.assertEqual(
            iv["welle_4_audit_anchor"], "WELLE-4-AUDIT-ANCHOR-READY"
        )
        self.assertEqual(iv["snapshot_restore_gate"], "SNAPSHOT-RESTORE-READY")
        self.assertEqual(iv["downstream_block_cascade"], "CASCADE-CONSISTENT")

    def test_input_verdicts_none_on_missing(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_4_producer"] = None
        env = self.mod.build_envelope(envelopes)
        self.assertIsNone(env["input_verdicts"]["welle_4_producer"])

    def test_window_in_welle_4_week_true_for_kw_26(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes(), iso_week=26)
        self.assertTrue(env["window"]["in_welle_4_week"])

    def test_window_in_welle_4_week_false_for_kw_25(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes(), iso_week=25)
        self.assertFalse(env["window"]["in_welle_4_week"])


class Tag72CascadeRuleTests(unittest.TestCase):
    """Forward-cascade-rule mapping."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_intact_yields_no_block(self) -> None:
        self.assertEqual(
            self.mod.downstream_blocked_wellen("WELLE-4-INTACT"), ()
        )

    def test_drift_yields_no_block(self) -> None:
        self.assertEqual(
            self.mod.downstream_blocked_wellen("WELLE-4-DRIFT"), ()
        )

    def test_defect_yields_four_through_seven(self) -> None:
        self.assertEqual(
            self.mod.downstream_blocked_wellen("WELLE-4-DEFECT"),
            (4, 5, 6, 7),
        )

    def test_unknown_verdict_yields_no_block(self) -> None:
        # Defensive: any non-DEFECT verdict (including unknown) yields ().
        self.assertEqual(
            self.mod.downstream_blocked_wellen("UNKNOWN"), ()
        )

    def test_forward_cascade_constant_matches_documented_tuple(self) -> None:
        # The constant must pin the (4,5,6,7) tuple verbatim per
        # docs/quality-gates/phase-3-marathon-anti-patterns.md AP-9
        # analogue + docs/ci/phase-3-marathon-rollback-runbook.md
        # reverse-cutover order J5 (W4 state_backing rollback).
        self.assertEqual(
            self.mod.FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT,
            (4, 5, 6, 7),
        )

    def test_welle_1_2_3_not_in_forward_cascade(self) -> None:
        # Welle-1/2/3 are upstream of Welle-4 and MUST NOT be in
        # the forward-cascade-set (unlike AP-9 Welle-3 cascade
        # which is reverse).
        cascade = self.mod.FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT
        for upstream in (1, 2, 3):
            self.assertNotIn(upstream, cascade)


class Tag72BriefReconciliationTests(unittest.TestCase):
    """Brief-vs-canonical reconciliation surface (Tag-71 lehre)."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_brief_reconciliation_carries_both_deltas(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        recon = env["brief_vs_canonical_reconciliation"]
        self.assertIn("welle_4_date", recon)
        self.assertIn("rollback_workflow_job", recon)

    def test_welle_4_date_reconciliation_canonical_kw_26(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        date_recon = env["brief_vs_canonical_reconciliation"]["welle_4_date"]
        self.assertIn("KW-25", date_recon["brief_value"])
        self.assertIn("KW-26", date_recon["canonical_value"])
        self.assertIn("2026-06-24", date_recon["canonical_value"])

    def test_rollback_job_reconciliation_canonical_j5(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        job_recon = env["brief_vs_canonical_reconciliation"][
            "rollback_workflow_job"
        ]
        self.assertIn("J4", job_recon["brief_value"])
        self.assertIn("J5", job_recon["canonical_value"])
        self.assertIn("state_backing", job_recon["canonical_value"])
        self.assertIn("snapshot-restore", job_recon["canonical_value"])


class Tag72CliEndToEndTests(unittest.TestCase):
    """CLI surface produces a verdict-envelope on disk."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_cli_writes_intact_verdict_on_all_green(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            paths = {
                "welle_4_producer": tdp / "producer.json",
                "welle_4_audit_anchor": tdp / "audit-anchor.json",
                "snapshot_restore_gate": tdp / "snapshot-restore.json",
                "downstream_block_cascade": tdp / "cascade.json",
            }
            _write_envelope(paths["welle_4_producer"], "WELLE-4-PRODUCER-READY")
            _write_envelope(
                paths["welle_4_audit_anchor"], "WELLE-4-AUDIT-ANCHOR-READY"
            )
            _write_envelope(
                paths["snapshot_restore_gate"], "SNAPSHOT-RESTORE-READY"
            )
            _write_envelope(
                paths["downstream_block_cascade"], "CASCADE-CONSISTENT"
            )
            output = tdp / "verdict.json"
            rc = self.mod.main(
                [
                    "--producer-envelope", str(paths["welle_4_producer"]),
                    "--audit-anchor-envelope", str(paths["welle_4_audit_anchor"]),
                    "--snapshot-restore-envelope", str(paths["snapshot_restore_gate"]),
                    "--cascade-envelope", str(paths["downstream_block_cascade"]),
                    "--iso-week", "26",
                    "--output", str(output),
                ]
            )
            self.assertEqual(rc, 0)
            env = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(env["verdict"], "WELLE-4-INTACT")

    def test_cli_writes_defect_on_missing_envelope_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            paths = {
                "welle_4_audit_anchor": tdp / "audit-anchor.json",
                "snapshot_restore_gate": tdp / "snapshot-restore.json",
                "downstream_block_cascade": tdp / "cascade.json",
            }
            _write_envelope(
                paths["welle_4_audit_anchor"], "WELLE-4-AUDIT-ANCHOR-READY"
            )
            _write_envelope(
                paths["snapshot_restore_gate"], "SNAPSHOT-RESTORE-READY"
            )
            _write_envelope(
                paths["downstream_block_cascade"], "CASCADE-CONSISTENT"
            )
            output = tdp / "verdict.json"
            # NOTE: producer-envelope intentionally omitted.
            rc = self.mod.main(
                [
                    "--audit-anchor-envelope", str(paths["welle_4_audit_anchor"]),
                    "--snapshot-restore-envelope", str(paths["snapshot_restore_gate"]),
                    "--cascade-envelope", str(paths["downstream_block_cascade"]),
                    "--output", str(output),
                ]
            )
            self.assertEqual(rc, 0)
            env = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(env["verdict"], "WELLE-4-DEFECT")
            self.assertEqual(env["step_results"]["welle_4_producer"], "red")

    def test_cli_writes_envelope_with_github_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            paths = {
                "welle_4_producer": tdp / "producer.json",
                "welle_4_audit_anchor": tdp / "audit-anchor.json",
                "snapshot_restore_gate": tdp / "snapshot-restore.json",
                "downstream_block_cascade": tdp / "cascade.json",
            }
            _write_envelope(paths["welle_4_producer"], "WELLE-4-PRODUCER-READY")
            _write_envelope(
                paths["welle_4_audit_anchor"], "WELLE-4-AUDIT-ANCHOR-READY"
            )
            _write_envelope(
                paths["snapshot_restore_gate"], "SNAPSHOT-RESTORE-READY"
            )
            _write_envelope(
                paths["downstream_block_cascade"], "CASCADE-CONSISTENT"
            )
            output = tdp / "verdict.json"
            rc = self.mod.main(
                [
                    "--producer-envelope", str(paths["welle_4_producer"]),
                    "--audit-anchor-envelope", str(paths["welle_4_audit_anchor"]),
                    "--snapshot-restore-envelope", str(paths["snapshot_restore_gate"]),
                    "--cascade-envelope", str(paths["downstream_block_cascade"]),
                    "--github-run-id", "1234567890",
                    "--github-sha", "deadbeefcafef00d",
                    "--github-ref", "refs/heads/amara/tag-72-welle-4-integration-smoke",
                    "--output", str(output),
                ]
            )
            self.assertEqual(rc, 0)
            env = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(env["github_run_id"], "1234567890")
            self.assertEqual(env["github_sha"], "deadbeefcafef00d")
            self.assertEqual(
                env["github_ref"], "refs/heads/amara/tag-72-welle-4-integration-smoke"
            )


class Tag72DecideHelperTests(unittest.TestCase):
    """Decide-helper trinary rule, isolated."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_decide_all_green_intact(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        self.assertEqual(self.mod.decide(steps), "WELLE-4-INTACT")

    def test_decide_one_yellow_drift(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        steps["snapshot_restore_gate"] = "yellow"
        self.assertEqual(self.mod.decide(steps), "WELLE-4-DRIFT")

    def test_decide_one_red_defect(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        steps["welle_4_producer"] = "red"
        self.assertEqual(self.mod.decide(steps), "WELLE-4-DEFECT")

    def test_decide_red_dominates_yellow(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        steps["snapshot_restore_gate"] = "yellow"
        steps["welle_4_audit_anchor"] = "red"
        self.assertEqual(self.mod.decide(steps), "WELLE-4-DEFECT")


class Tag72StageOrderingTests(unittest.TestCase):
    """Stage chronological order pins the pipeline-runbook ordering."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_stages_chronological_order(self) -> None:
        # The Tag-72 pipeline-runbook order:
        #   producer -> audit-anchor -> snapshot-restore-gate -> cascade.
        self.assertEqual(
            self.mod.STAGES,
            (
                "welle_4_producer",
                "welle_4_audit_anchor",
                "snapshot_restore_gate",
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


class Tag72WorkflowShapeTests(unittest.TestCase):
    """Workflow file structural shape (parsed as text)."""

    def setUp(self) -> None:
        self.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_workflow_file_exists(self) -> None:
        self.assertTrue(WORKFLOW_PATH.exists(), msg=str(WORKFLOW_PATH))

    def test_workflow_name_field(self) -> None:
        self.assertIn("name: welle-4-integration-smoke", self.text)

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

    def test_workflow_permissions_read_only(self) -> None:
        self.assertIn("permissions:", self.text)
        self.assertIn("contents: read", self.text)

    def test_workflow_invokes_aggregate_helper(self) -> None:
        self.assertIn(
            "tooling/ci/aggregate_welle_4_integration.py", self.text
        )

    def test_workflow_uploads_envelope_artifact(self) -> None:
        self.assertIn("welle-4-integration-verdict", self.text)
        self.assertIn("upload-artifact@v4", self.text)

    def test_workflow_declares_sandbox_boundary_header(self) -> None:
        # Header must mention the hermetic / sandbox / boundary
        # discipline (per Mira feedback_sandbox_host_trennung.md).
        self.assertIn("hermetic", self.text.lower())
        self.assertIn("sandbox", self.text.lower())

    def test_workflow_invokes_snapshot_restore_stage(self) -> None:
        self.assertIn("Snapshot-Restore", self.text)
        self.assertIn("snapshot_restore", self.text)


if __name__ == "__main__":
    unittest.main()
