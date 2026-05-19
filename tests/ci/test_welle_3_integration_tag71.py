# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic tests for the Tag-71 Welle-3 Integration-Smoke.

Auftrag-Anker
-------------

Tag-71 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
Hermetic end-to-end simulation of the four Welle-3 substrates that
fire in sequence on the 2026-06-12 (KW-24 Fr) Welle-3 Bridge-Audit-
Writer Cutover-Day pipeline. The integration-smoke aggregates the
Selin Welle-3-Producer, Tomas Welle-3-Audit-Trail-Anchor, Henrik
§11-Disziplin Pre-Auditor-Gate, and AP-9 Downstream-Block-Cascade
substrate envelopes into a single trinary WELLE-3 verdict
(INTACT / DRIFT / DEFECT).

Scope (aggregator + workflow-shape)
-----------------------------------

This module verifies two surfaces:

* The Tag-71 aggregator helper
  (``tooling/ci/aggregate_welle_3_integration.py``):
  - all-green inputs collapse to WELLE-3-INTACT
  - one-yellow inputs collapse to WELLE-3-DRIFT
  - one-red inputs collapse to WELLE-3-DEFECT
  - missing envelope on any stage collapses to WELLE-3-DEFECT
  - unknown verdict on any stage collapses to WELLE-3-DEFECT
  - per-stage notes surface the offending stage + verdict
  - envelope schema fields are present and well-typed
  - substrate-provenance carries the four cross-anchor records
  - sandbox-boundary axis is set correctly
  - welle_3_anchor surfaces 2026-06-12 / KW-24 / Welle-3
  - AP-9 downstream-cascade fires (3,4,5,6,7) on DEFECT only

* The Tag-71 workflow file
  (``.github/workflows/welle-3-integration-smoke.yml``):
  - five named stages present in declared order
  - workflow_dispatch surface includes drift_inject + defect_inject
  - permissions are read-only on contents
  - sandbox-boundary axis declared in header
  - aggregator helper invoked from Stage 5
  - artifact upload steps present for both envelope and stages

Hermetic posture
----------------

stdlib + unittest. No subprocess into the network. The aggregator
is loaded as a module via importlib. The workflow is parsed as text.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This test pins only the Tag-71 Welle-3-integration-smoke aggregator
and workflow. It does NOT modify any Welle-3 substrate workflow
(Selin / Tomas / Henrik domains), the AP-9 cascade-rule helpers,
or the Tag-69/Tag-70 helpers.

Cross-Review-Markers
--------------------

* Zone-M: QA x Selin -- producer-stage and cascade-stage verdict
  mappings inherit from the Welle-3 state-file producer and the
  AP-9 cascade-rule. Drift in the trinary verdict-shape is a
  Zone-M signal.
* Zone-M: QA x Tomas -- audit-anchor-stage verdict mapping
  inherits from the Welle-3 audit-trail-anchor wire-helper.
  Drift in the envelope schema is a Zone-M signal.
* Zone-N: QA x Henrik -- pre-auditor-gate-stage verdict mapping
  inherits from §11-Disziplin (Henrik pre-auditor designation).
  Drift in the PROCEED/CAUTION/BLOCK trinary is a Zone-N signal.
* Zone-N: QA x Henrik -- the aggregated WELLE-3-INTEGRATION
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
    REPO_ROOT / "tooling" / "ci" / "aggregate_welle_3_integration.py"
)
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "welle-3-integration-smoke.yml"
)


def _load_aggregator():
    spec = importlib.util.spec_from_file_location(
        "agg_welle_3_integration_tag71", AGGREGATOR_PATH
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
        "welle_3_producer": {"verdict": "WELLE-3-PRODUCER-READY"},
        "welle_3_audit_anchor": {"verdict": "WELLE-3-AUDIT-ANCHOR-READY"},
        "pre_auditor_gate": {"verdict": "PRE-AUDITOR-PROCEED"},
        "downstream_block_cascade": {"verdict": "CASCADE-CONSISTENT"},
    }


class Tag71AggregatorAllGreenTests(unittest.TestCase):
    """All four stages green -> WELLE-3-INTACT."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_all_green_collapses_to_intact(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes(), iso_week=24)
        self.assertEqual(env["verdict"], "WELLE-3-INTACT")
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


class Tag71AggregatorDriftTests(unittest.TestCase):
    """One yellow + rest green -> WELLE-3-DRIFT."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_producer_drift_collapses_to_drift(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_3_producer"] = {"verdict": "WELLE-3-PRODUCER-DRIFT"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-3-DRIFT")
        self.assertEqual(env["counts"]["yellow"], 1)
        self.assertEqual(env["counts"]["red"], 0)
        self.assertEqual(env["failed_steps"], ["welle_3_producer"])
        self.assertIn("welle_3_producer", env["per_stage_notes"])

    def test_pre_auditor_caution_maps_to_drift(self) -> None:
        # The §11-Disziplin CAUTION decision degrades to DRIFT,
        # NOT defect. Only BLOCK collapses to defect.
        envelopes = _all_green_envelopes()
        envelopes["pre_auditor_gate"] = {"verdict": "PRE-AUDITOR-CAUTION"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-3-DRIFT")
        self.assertEqual(env["step_results"]["pre_auditor_gate"], "yellow")

    def test_cascade_drift_surfaces_in_failed_steps(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["downstream_block_cascade"] = {"verdict": "CASCADE-DRIFT"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-3-DRIFT")
        self.assertIn("downstream_block_cascade", env["failed_steps"])

    def test_drift_does_not_arm_cascade(self) -> None:
        # Per AP-9: only DEFECT arms the downstream-block cascade.
        # A DRIFT verdict yields warnings, not a blocked-wellen
        # tuple.
        envelopes = _all_green_envelopes()
        envelopes["welle_3_audit_anchor"] = {
            "verdict": "WELLE-3-AUDIT-ANCHOR-DRIFT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-3-DRIFT")
        self.assertFalse(env["downstream_cascade"]["cascade_armed"])


class Tag71AggregatorDefectTests(unittest.TestCase):
    """Any red OR any missing envelope -> WELLE-3-DEFECT + cascade armed."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_audit_anchor_defect_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_3_audit_anchor"] = {
            "verdict": "WELLE-3-AUDIT-ANCHOR-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-3-DEFECT")
        self.assertEqual(env["counts"]["red"], 1)
        self.assertIn("welle_3_audit_anchor", env["failed_steps"])

    def test_pre_auditor_block_collapses_to_defect(self) -> None:
        # The §11-Disziplin BLOCK decision is a hard-stop on the
        # Welle-3 cutover; the integration-smoke MUST collapse to
        # DEFECT so the cascade arms.
        envelopes = _all_green_envelopes()
        envelopes["pre_auditor_gate"] = {"verdict": "PRE-AUDITOR-BLOCK"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-3-DEFECT")
        self.assertEqual(env["step_results"]["pre_auditor_gate"], "red")

    def test_missing_producer_envelope_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_3_producer"] = None
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-3-DEFECT")
        self.assertIn("welle_3_producer", env["per_stage_notes"])
        note = env["per_stage_notes"]["welle_3_producer"]
        self.assertIn("missing", note.lower())

    def test_unknown_verdict_collapses_to_defect(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_3_producer"] = {"verdict": "UNKNOWN-VERDICT-SHAPE"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-3-DEFECT")
        self.assertIn("welle_3_producer", env["per_stage_notes"])
        self.assertIn(
            "UNKNOWN-VERDICT-SHAPE",
            env["per_stage_notes"]["welle_3_producer"],
        )

    def test_red_dominates_yellow(self) -> None:
        envelopes = _all_green_envelopes()
        envelopes["welle_3_producer"] = {"verdict": "WELLE-3-PRODUCER-DRIFT"}
        envelopes["welle_3_audit_anchor"] = {
            "verdict": "WELLE-3-AUDIT-ANCHOR-DEFECT"
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-3-DEFECT")
        self.assertEqual(env["counts"]["red"], 1)
        self.assertEqual(env["counts"]["yellow"], 1)

    def test_defect_arms_cascade_3_4_5_6_7(self) -> None:
        # AP-9: any DEFECT MUST arm the downstream-block cascade
        # to (3,4,5,6,7) regardless of which stage triggered it.
        envelopes = _all_green_envelopes()
        envelopes["downstream_block_cascade"] = {"verdict": "CASCADE-BREAK"}
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "WELLE-3-DEFECT")
        self.assertTrue(env["downstream_cascade"]["cascade_armed"])
        self.assertEqual(
            env["downstream_cascade"]["blocked_wellen_now"], [3, 4, 5, 6, 7]
        )


class Tag71AggregatorEnvelopeShapeTests(unittest.TestCase):
    """Envelope schema fields are present, well-typed, ordered."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()
        self.envelopes = _all_green_envelopes()

    def test_envelope_has_required_top_level_keys(self) -> None:
        env = self.mod.build_envelope(self.envelopes, iso_week=24)
        for key in (
            "schema_version",
            "workflow",
            "tag",
            "emitted_at_utc",
            "verdict",
            "step_results",
            "failed_steps",
            "per_stage_notes",
            "counts",
            "welle_3_anchor",
            "window",
            "input_verdicts",
            "substrate_provenance",
            "downstream_cascade",
            "decision_rule",
            "sandbox_boundary",
        ):
            self.assertIn(key, env, f"missing top-level key: {key}")

    def test_envelope_workflow_field_matches_workflow_name(self) -> None:
        env = self.mod.build_envelope(self.envelopes)
        self.assertEqual(env["workflow"], "welle-3-integration-smoke")
        self.assertEqual(env["tag"], "tag-71")
        self.assertEqual(env["schema_version"], 1)

    def test_welle_3_anchor_carries_2026_06_12_kw24_welle3(self) -> None:
        env = self.mod.build_envelope(self.envelopes)
        anchor = env["welle_3_anchor"]
        self.assertEqual(anchor["iso_date"], "2026-06-12")
        self.assertEqual(anchor["iso_week"], 24)
        self.assertEqual(anchor["welle_number"], 3)

    def test_substrate_provenance_carries_four_anchors(self) -> None:
        env = self.mod.build_envelope(self.envelopes)
        prov = env["substrate_provenance"]
        self.assertEqual(set(prov.keys()), set(self.mod.STAGES))
        self.assertEqual(prov["welle_3_producer"]["owner"], "Selin")
        self.assertEqual(prov["welle_3_audit_anchor"]["owner"], "Tomas")
        self.assertEqual(prov["pre_auditor_gate"]["owner"], "Henrik")
        self.assertEqual(prov["downstream_block_cascade"]["owner"], "Selin")
        # Pre-auditor anchor calls out the §11 paragraph.
        self.assertIn("paragraph-11", prov["pre_auditor_gate"]["kind"])

    def test_sandbox_boundary_axis_set_correctly(self) -> None:
        env = self.mod.build_envelope(self.envelopes)
        sb = env["sandbox_boundary"]
        self.assertTrue(sb["stdlib_only"])
        self.assertTrue(sb["no_network_io"])
        self.assertTrue(sb["no_actual_welle_3_dispatch"])
        self.assertTrue(sb["no_gh_workflow_run"])

    def test_input_verdicts_surfaces_raw_strings(self) -> None:
        env = self.mod.build_envelope(self.envelopes)
        iv = env["input_verdicts"]
        self.assertEqual(iv["welle_3_producer"], "WELLE-3-PRODUCER-READY")
        self.assertEqual(
            iv["welle_3_audit_anchor"], "WELLE-3-AUDIT-ANCHOR-READY"
        )
        self.assertEqual(iv["pre_auditor_gate"], "PRE-AUDITOR-PROCEED")
        self.assertEqual(
            iv["downstream_block_cascade"], "CASCADE-CONSISTENT"
        )

    def test_input_verdicts_none_on_missing(self) -> None:
        envelopes = dict(self.envelopes)
        envelopes["pre_auditor_gate"] = None
        env = self.mod.build_envelope(envelopes)
        self.assertIsNone(env["input_verdicts"]["pre_auditor_gate"])

    def test_window_in_welle_3_week_true_for_kw_24(self) -> None:
        env = self.mod.build_envelope(self.envelopes, iso_week=24)
        self.assertTrue(env["window"]["in_welle_3_week"])
        self.assertEqual(env["window"]["iso_week"], 24)

    def test_window_in_welle_3_week_false_for_kw_25(self) -> None:
        env = self.mod.build_envelope(self.envelopes, iso_week=25)
        self.assertFalse(env["window"]["in_welle_3_week"])


class Tag71CascadeRuleTests(unittest.TestCase):
    """AP-9 downstream_blocked_wellen helper matches the canonical rule."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_intact_yields_no_block(self) -> None:
        self.assertEqual(
            self.mod.downstream_blocked_wellen("WELLE-3-INTACT"), ()
        )

    def test_drift_yields_no_block(self) -> None:
        self.assertEqual(
            self.mod.downstream_blocked_wellen("WELLE-3-DRIFT"), ()
        )

    def test_defect_yields_three_through_seven(self) -> None:
        self.assertEqual(
            self.mod.downstream_blocked_wellen("WELLE-3-DEFECT"),
            (3, 4, 5, 6, 7),
        )

    def test_unknown_verdict_yields_no_block(self) -> None:
        # Defensive: any verdict that is not DEFECT (incl. an
        # unrecognised string) must NOT arm the cascade. The
        # arming-condition is strictly defect-bound.
        self.assertEqual(
            self.mod.downstream_blocked_wellen("SOMETHING-ELSE"), ()
        )

    def test_ap_9_constant_matches_documented_tuple(self) -> None:
        # Pin the AP-9 constant to (3,4,5,6,7); a drift in the
        # tuple shape is a Zone-M signal that the cascade-rule
        # documentation diverged from the aggregator.
        self.assertEqual(
            self.mod.AP_9_BLOCKED_WELLEN_ON_DEFECT, (3, 4, 5, 6, 7)
        )


class Tag71AggregatorCLITests(unittest.TestCase):
    """CLI round-trip: envelope JSON written to disk matches build_envelope."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_cli_writes_intact_verdict_on_all_green(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            _write_envelope(tdp / "p.json", "WELLE-3-PRODUCER-READY")
            _write_envelope(tdp / "a.json", "WELLE-3-AUDIT-ANCHOR-READY")
            _write_envelope(tdp / "h.json", "PRE-AUDITOR-PROCEED")
            _write_envelope(tdp / "c.json", "CASCADE-CONSISTENT")
            out_path = tdp / "agg.json"
            rc = self.mod.main(
                [
                    "--producer-envelope", str(tdp / "p.json"),
                    "--audit-anchor-envelope", str(tdp / "a.json"),
                    "--pre-auditor-envelope", str(tdp / "h.json"),
                    "--cascade-envelope", str(tdp / "c.json"),
                    "--iso-week", "24",
                    "--output", str(out_path),
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(out_path.exists())
            env = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(env["verdict"], "WELLE-3-INTACT")

    def test_cli_writes_defect_on_missing_envelope_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            _write_envelope(tdp / "p.json", "WELLE-3-PRODUCER-READY")
            _write_envelope(tdp / "a.json", "WELLE-3-AUDIT-ANCHOR-READY")
            _write_envelope(tdp / "h.json", "PRE-AUDITOR-PROCEED")
            # cascade envelope omitted
            out_path = tdp / "agg.json"
            rc = self.mod.main(
                [
                    "--producer-envelope", str(tdp / "p.json"),
                    "--audit-anchor-envelope", str(tdp / "a.json"),
                    "--pre-auditor-envelope", str(tdp / "h.json"),
                    "--output", str(out_path),
                ]
            )
            self.assertEqual(rc, 0)
            env = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(env["verdict"], "WELLE-3-DEFECT")
            self.assertIn(
                "downstream_block_cascade", env["failed_steps"]
            )

    def test_cli_writes_envelope_with_github_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            _write_envelope(tdp / "p.json", "WELLE-3-PRODUCER-READY")
            _write_envelope(tdp / "a.json", "WELLE-3-AUDIT-ANCHOR-READY")
            _write_envelope(tdp / "h.json", "PRE-AUDITOR-PROCEED")
            _write_envelope(tdp / "c.json", "CASCADE-CONSISTENT")
            out_path = tdp / "agg.json"
            rc = self.mod.main(
                [
                    "--producer-envelope", str(tdp / "p.json"),
                    "--audit-anchor-envelope", str(tdp / "a.json"),
                    "--pre-auditor-envelope", str(tdp / "h.json"),
                    "--cascade-envelope", str(tdp / "c.json"),
                    "--github-run-id", "71-run-id",
                    "--github-sha", "def5678",
                    "--github-ref", "refs/pull/9999/merge",
                    "--output", str(out_path),
                ]
            )
            self.assertEqual(rc, 0)
            env = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(env["github_run_id"], "71-run-id")
            self.assertEqual(env["github_sha"], "def5678")
            self.assertEqual(env["github_ref"], "refs/pull/9999/merge")


class Tag71AggregatorDecisionRuleTests(unittest.TestCase):
    """The exposed decide() helper matches the documented rule."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_decide_all_green_intact(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        self.assertEqual(self.mod.decide(steps), "WELLE-3-INTACT")

    def test_decide_one_yellow_drift(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        steps["welle_3_producer"] = "yellow"
        self.assertEqual(self.mod.decide(steps), "WELLE-3-DRIFT")

    def test_decide_one_red_defect(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        steps["pre_auditor_gate"] = "red"
        self.assertEqual(self.mod.decide(steps), "WELLE-3-DEFECT")

    def test_decide_red_dominates_yellow(self) -> None:
        steps = {s: "yellow" for s in self.mod.STAGES}
        steps["downstream_block_cascade"] = "red"
        self.assertEqual(self.mod.decide(steps), "WELLE-3-DEFECT")


class Tag71AggregatorStageOrderingTests(unittest.TestCase):
    """STAGES tuple matches the chronological Welle-3 pipeline order."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_stages_chronological_order(self) -> None:
        # producer -> audit-anchor -> pre-auditor -> cascade.
        # Mirrors the runbook order on 2026-06-12.
        self.assertEqual(
            self.mod.STAGES,
            (
                "welle_3_producer",
                "welle_3_audit_anchor",
                "pre_auditor_gate",
                "downstream_block_cascade",
            ),
        )

    def test_stage_verdict_maps_cover_all_stages(self) -> None:
        for stage in self.mod.STAGES:
            self.assertIn(
                stage,
                self.mod.STAGE_VERDICT_MAPS,
                f"stage {stage} missing verdict map",
            )
            vmap = self.mod.STAGE_VERDICT_MAPS[stage]
            self.assertEqual(set(vmap.values()), {"green", "yellow", "red"})

    def test_step_results_preserves_stage_order_on_iteration(self) -> None:
        env = self.mod.build_envelope(_all_green_envelopes())
        self.assertEqual(tuple(env["step_results"].keys()), self.mod.STAGES)


class Tag71WorkflowShapeTests(unittest.TestCase):
    """The Tag-71 workflow file has the expected hermetic shape."""

    def setUp(self) -> None:
        self.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_workflow_file_exists(self) -> None:
        self.assertTrue(WORKFLOW_PATH.exists())

    def test_workflow_name_field(self) -> None:
        self.assertIn("name: welle-3-integration-smoke", self.text)

    def test_workflow_declares_five_stages(self) -> None:
        for stage_line in (
            "Stage 1 -- Welle-3-Producer simulation",
            "Stage 2 -- Welle-3-Audit-Anchor simulation",
            "Stage 3 -- Pre-Auditor-Gate-Verification",
            "Stage 4 -- Downstream-Block-Cascade-Test",
            "Stage 5 -- Aggregate WELLE-3-INTEGRATION verdict",
        ):
            self.assertIn(stage_line, self.text, f"missing: {stage_line}")

    def test_workflow_dispatch_has_drift_and_defect_inject(self) -> None:
        self.assertIn("drift_inject:", self.text)
        self.assertIn("defect_inject:", self.text)

    def test_workflow_invokes_aggregator_from_stage_5(self) -> None:
        self.assertIn(
            "tooling/ci/aggregate_welle_3_integration.py", self.text
        )

    def test_workflow_uploads_envelope_and_stages_artifacts(self) -> None:
        self.assertIn("welle-3-integration-verdict", self.text)
        self.assertIn("welle-3-integration-stages", self.text)

    def test_workflow_permissions_read_only_on_contents(self) -> None:
        self.assertIn("contents: read", self.text)
        self.assertNotIn("contents: write", self.text)
        self.assertNotIn("actions: write", self.text)

    def test_workflow_declares_sandbox_boundary_in_header(self) -> None:
        self.assertIn("Sandbox boundary", self.text)
        self.assertIn("hermetic", self.text)
        self.assertIn("does NOT trigger", self.text)

    def test_workflow_references_paragraph_11_and_ap_9(self) -> None:
        # The header should cite the §11-Disziplin and the AP-9
        # cascade-rule explicitly for the audit-evidence trail.
        self.assertIn("§11", self.text)
        self.assertIn("AP-9", self.text)

    def test_workflow_terminal_gate_exits_1_on_defect(self) -> None:
        self.assertIn("WELLE-3-DEFECT", self.text)
        self.assertIn("exit 1", self.text)

    def test_workflow_does_not_invoke_gh_workflow_run(self) -> None:
        non_comment_lines = [
            line
            for line in self.text.splitlines()
            if not line.lstrip().startswith("#")
        ]
        non_comment_text = "\n".join(non_comment_lines)
        self.assertNotIn("gh workflow run", non_comment_text)


class Tag71AggregatorHelpersTests(unittest.TestCase):
    """Sanity tests for individual helper functions in the aggregator."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_load_envelope_returns_none_for_missing_path(self) -> None:
        self.assertIsNone(
            self.mod._load_envelope(Path("/nonexistent/path/missing.json"))
        )

    def test_load_envelope_returns_none_for_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"
            bad.write_text("not-json", encoding="utf-8")
            self.assertIsNone(self.mod._load_envelope(bad))

    def test_load_envelope_returns_none_for_non_dict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            arr = Path(td) / "arr.json"
            arr.write_text("[1,2,3]", encoding="utf-8")
            self.assertIsNone(self.mod._load_envelope(arr))

    def test_normalise_status_green_for_known_ready(self) -> None:
        status, note = self.mod._normalise_status(
            "welle_3_producer", {"verdict": "WELLE-3-PRODUCER-READY"}
        )
        self.assertEqual(status, "green")
        self.assertEqual(note, "")

    def test_normalise_status_red_for_missing_envelope(self) -> None:
        status, note = self.mod._normalise_status("welle_3_producer", None)
        self.assertEqual(status, "red")
        self.assertIn("missing", note.lower())

    def test_normalise_status_red_for_non_string_verdict(self) -> None:
        status, note = self.mod._normalise_status(
            "welle_3_producer", {"verdict": 42}
        )
        self.assertEqual(status, "red")
        self.assertIn("no string", note.lower())


if __name__ == "__main__":
    unittest.main()
