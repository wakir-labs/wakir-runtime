# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic tests for the Tag-70 Cutover-Day-T0 Integration-Smoke.

Auftrag-Anker
-------------

Tag-70 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
Hermetic end-to-end simulation of the four Tag-69 substrates that
fire in sequence on the 2026-06-08 Welle-1-Cutover-Day (T0) Day-1
pipeline. The integration-smoke aggregates the Selin Welle-1-
Producer (PR #438), Tomas Welle-1-Audit-Trail-Anchor (PR #439),
Noa Live-Smoke-Stability-Window-Probe (PR #437), and Selin
Cutover-Day-Morgen Auto-Scheduler (Tag-64 + Tag-66 sidecar)
substrate envelopes into a single trinary T0-INTEGRATION verdict
(INTACT / DRIFT / DEFECT).

Scope (aggregator + workflow-shape)
-----------------------------------

This module verifies two surfaces:

* The Tag-70 aggregator helper
  (``tooling/ci/aggregate_cutover_day_t0_integration.py``):
  - all-green inputs collapse to T0-INTEGRATION-INTACT
  - one-yellow inputs collapse to T0-INTEGRATION-DRIFT
  - one-red inputs collapse to T0-INTEGRATION-DEFECT
  - missing envelope on any stage collapses to T0-INTEGRATION-DEFECT
  - unknown verdict on any stage collapses to T0-INTEGRATION-DEFECT
  - per-stage notes surface the offending stage + verdict
  - envelope schema fields are present and well-typed
  - substrate-provenance carries the four cross-anchor records
  - sandbox-boundary axis is set correctly
  - t0_anchor surfaces 2026-06-08 / KW-24 / Welle-1

* The Tag-70 workflow file
  (``.github/workflows/cutover-day-t0-integration-smoke.yml``):
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

This test pins only the Tag-70 T0-integration-smoke aggregator and
workflow. It does NOT modify the Tag-69 substrate workflows
(Selin / Tomas / Noa domains), the Tag-64 cutover-day-morgen
aggregator (Selin-domain), or the Tag-66 sidecar wiring (Selin-
domain).

Cross-Review-Markers
--------------------

* Zone-M: QA x Selin -- producer-stage and auto-scheduler-stage
  verdict mappings inherit from PR-#438 / Tag-64 helpers. Drift
  in the trinary verdict-shape is a Zone-M signal.
* Zone-M: QA x Tomas -- audit-anchor-stage verdict mapping
  inherits from PR-#439 wire-helper. Drift in the envelope
  schema is a Zone-M signal.
* Zone-M: QA x Noa -- live-smoke-stage verdict mapping inherits
  from PR-#437 stability-window-probe. Drift in the trinary
  shape is a Zone-M signal.
* Zone-N: QA x Henrik -- the aggregated T0-INTEGRATION envelope,
  per-stage envelopes, and the workflow-emitted artifacts are
  Audit-Evidence-Inputs. Drift in their structure or completeness
  is a Zone-N signal.
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
    REPO_ROOT / "tooling" / "ci" / "aggregate_cutover_day_t0_integration.py"
)
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "cutover-day-t0-integration-smoke.yml"
)


def _load_aggregator():
    spec = importlib.util.spec_from_file_location(
        "agg_t0_integration_tag70", AGGREGATOR_PATH
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


class Tag70AggregatorAllGreenTests(unittest.TestCase):
    """All four stages green -> INTACT."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_all_green_collapses_to_intact(self) -> None:
        envelopes = {
            "welle_1_producer": {"verdict": "WELLE-1-PRODUCER-READY"},
            "welle_1_audit_anchor": {"verdict": "WELLE-1-AUDIT-ANCHOR-READY"},
            "live_smoke_stability_window": {
                "verdict": "LIVE-SMOKE-STABILITY-WINDOW-READY"
            },
            "auto_scheduler": {"verdict": "CUTOVER-DAY-MORGEN-READY"},
        }
        env = self.mod.build_envelope(envelopes, iso_week=24)
        self.assertEqual(env["verdict"], "T0-INTEGRATION-INTACT")
        self.assertEqual(env["counts"], {"green": 4, "yellow": 0, "red": 0})
        self.assertEqual(env["failed_steps"], [])
        self.assertEqual(env["per_stage_notes"], {})

    def test_all_green_step_results_all_green(self) -> None:
        envelopes = {
            "welle_1_producer": {"verdict": "WELLE-1-PRODUCER-READY"},
            "welle_1_audit_anchor": {"verdict": "WELLE-1-AUDIT-ANCHOR-READY"},
            "live_smoke_stability_window": {
                "verdict": "LIVE-SMOKE-STABILITY-WINDOW-READY"
            },
            "auto_scheduler": {"verdict": "CUTOVER-DAY-MORGEN-READY"},
        }
        env = self.mod.build_envelope(envelopes)
        for stage in self.mod.STAGES:
            self.assertEqual(env["step_results"][stage], "green")


class Tag70AggregatorDriftTests(unittest.TestCase):
    """One yellow + rest green -> DRIFT."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_producer_drift_collapses_to_drift(self) -> None:
        envelopes = {
            "welle_1_producer": {"verdict": "WELLE-1-PRODUCER-DRIFT"},
            "welle_1_audit_anchor": {"verdict": "WELLE-1-AUDIT-ANCHOR-READY"},
            "live_smoke_stability_window": {
                "verdict": "LIVE-SMOKE-STABILITY-WINDOW-READY"
            },
            "auto_scheduler": {"verdict": "CUTOVER-DAY-MORGEN-READY"},
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "T0-INTEGRATION-DRIFT")
        self.assertEqual(env["counts"]["yellow"], 1)
        self.assertEqual(env["counts"]["red"], 0)
        self.assertEqual(env["failed_steps"], ["welle_1_producer"])
        self.assertIn("welle_1_producer", env["per_stage_notes"])

    def test_live_smoke_drift_surfaces_in_failed_steps(self) -> None:
        envelopes = {
            "welle_1_producer": {"verdict": "WELLE-1-PRODUCER-READY"},
            "welle_1_audit_anchor": {"verdict": "WELLE-1-AUDIT-ANCHOR-READY"},
            "live_smoke_stability_window": {
                "verdict": "LIVE-SMOKE-STABILITY-WINDOW-DRIFT"
            },
            "auto_scheduler": {"verdict": "CUTOVER-DAY-MORGEN-READY"},
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "T0-INTEGRATION-DRIFT")
        self.assertIn("live_smoke_stability_window", env["failed_steps"])

    def test_auto_scheduler_caution_maps_to_drift(self) -> None:
        # The Tag-64 auto-scheduler emits CUTOVER-DAY-MORGEN-CAUTION
        # as the yellow signal; the Tag-70 mapping must translate
        # that into a stage-yellow status -> overall DRIFT.
        envelopes = {
            "welle_1_producer": {"verdict": "WELLE-1-PRODUCER-READY"},
            "welle_1_audit_anchor": {"verdict": "WELLE-1-AUDIT-ANCHOR-READY"},
            "live_smoke_stability_window": {
                "verdict": "LIVE-SMOKE-STABILITY-WINDOW-READY"
            },
            "auto_scheduler": {"verdict": "CUTOVER-DAY-MORGEN-CAUTION"},
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "T0-INTEGRATION-DRIFT")
        self.assertEqual(env["step_results"]["auto_scheduler"], "yellow")


class Tag70AggregatorDefectTests(unittest.TestCase):
    """Any red OR any missing envelope -> DEFECT."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_audit_anchor_defect_collapses_to_defect(self) -> None:
        envelopes = {
            "welle_1_producer": {"verdict": "WELLE-1-PRODUCER-READY"},
            "welle_1_audit_anchor": {
                "verdict": "WELLE-1-AUDIT-ANCHOR-DEFECT"
            },
            "live_smoke_stability_window": {
                "verdict": "LIVE-SMOKE-STABILITY-WINDOW-READY"
            },
            "auto_scheduler": {"verdict": "CUTOVER-DAY-MORGEN-READY"},
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "T0-INTEGRATION-DEFECT")
        self.assertEqual(env["counts"]["red"], 1)
        self.assertIn("welle_1_audit_anchor", env["failed_steps"])

    def test_missing_producer_envelope_collapses_to_defect(self) -> None:
        envelopes = {
            "welle_1_producer": None,
            "welle_1_audit_anchor": {"verdict": "WELLE-1-AUDIT-ANCHOR-READY"},
            "live_smoke_stability_window": {
                "verdict": "LIVE-SMOKE-STABILITY-WINDOW-READY"
            },
            "auto_scheduler": {"verdict": "CUTOVER-DAY-MORGEN-READY"},
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "T0-INTEGRATION-DEFECT")
        self.assertIn("welle_1_producer", env["per_stage_notes"])
        note = env["per_stage_notes"]["welle_1_producer"]
        self.assertIn("missing", note.lower())

    def test_unknown_verdict_collapses_to_defect(self) -> None:
        envelopes = {
            "welle_1_producer": {"verdict": "UNKNOWN-VERDICT-SHAPE"},
            "welle_1_audit_anchor": {"verdict": "WELLE-1-AUDIT-ANCHOR-READY"},
            "live_smoke_stability_window": {
                "verdict": "LIVE-SMOKE-STABILITY-WINDOW-READY"
            },
            "auto_scheduler": {"verdict": "CUTOVER-DAY-MORGEN-READY"},
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "T0-INTEGRATION-DEFECT")
        self.assertIn("welle_1_producer", env["per_stage_notes"])
        self.assertIn(
            "UNKNOWN-VERDICT-SHAPE",
            env["per_stage_notes"]["welle_1_producer"],
        )

    def test_red_dominates_yellow(self) -> None:
        # One yellow + one red -> DEFECT (red dominates).
        envelopes = {
            "welle_1_producer": {"verdict": "WELLE-1-PRODUCER-DRIFT"},
            "welle_1_audit_anchor": {
                "verdict": "WELLE-1-AUDIT-ANCHOR-DEFECT"
            },
            "live_smoke_stability_window": {
                "verdict": "LIVE-SMOKE-STABILITY-WINDOW-READY"
            },
            "auto_scheduler": {"verdict": "CUTOVER-DAY-MORGEN-READY"},
        }
        env = self.mod.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "T0-INTEGRATION-DEFECT")
        self.assertEqual(env["counts"]["red"], 1)
        self.assertEqual(env["counts"]["yellow"], 1)


class Tag70AggregatorEnvelopeShapeTests(unittest.TestCase):
    """Envelope schema fields are present, well-typed, ordered."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()
        self.envelopes = {
            "welle_1_producer": {"verdict": "WELLE-1-PRODUCER-READY"},
            "welle_1_audit_anchor": {"verdict": "WELLE-1-AUDIT-ANCHOR-READY"},
            "live_smoke_stability_window": {
                "verdict": "LIVE-SMOKE-STABILITY-WINDOW-READY"
            },
            "auto_scheduler": {"verdict": "CUTOVER-DAY-MORGEN-READY"},
        }

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
            "t0_anchor",
            "window",
            "input_verdicts",
            "substrate_provenance",
            "decision_rule",
            "sandbox_boundary",
        ):
            self.assertIn(key, env, f"missing top-level key: {key}")

    def test_envelope_workflow_field_matches_workflow_name(self) -> None:
        env = self.mod.build_envelope(self.envelopes)
        self.assertEqual(env["workflow"], "cutover-day-t0-integration-smoke")
        self.assertEqual(env["tag"], "tag-70")
        self.assertEqual(env["schema_version"], 1)

    def test_t0_anchor_carries_2026_06_08_kw24_welle1(self) -> None:
        env = self.mod.build_envelope(self.envelopes)
        anchor = env["t0_anchor"]
        self.assertEqual(anchor["iso_date"], "2026-06-08")
        self.assertEqual(anchor["iso_week"], 24)
        self.assertEqual(anchor["welle_number"], 1)

    def test_substrate_provenance_carries_four_anchors(self) -> None:
        env = self.mod.build_envelope(self.envelopes)
        prov = env["substrate_provenance"]
        self.assertEqual(set(prov.keys()), set(self.mod.STAGES))
        # PR-anchors per the Tag-69 substrate ownership.
        self.assertEqual(prov["welle_1_producer"]["pr"], 438)
        self.assertEqual(prov["welle_1_audit_anchor"]["pr"], 439)
        self.assertEqual(prov["live_smoke_stability_window"]["pr"], 437)
        # Auto-scheduler is composite (Tag-64 + Tag-66), no single PR.
        self.assertIsNone(prov["auto_scheduler"]["pr"])

    def test_sandbox_boundary_axis_set_correctly(self) -> None:
        env = self.mod.build_envelope(self.envelopes)
        sb = env["sandbox_boundary"]
        self.assertTrue(sb["stdlib_only"])
        self.assertTrue(sb["no_network_io"])
        self.assertTrue(sb["no_actual_t0_dispatch"])
        self.assertTrue(sb["no_gh_workflow_run"])

    def test_input_verdicts_surfaces_raw_strings(self) -> None:
        env = self.mod.build_envelope(self.envelopes)
        iv = env["input_verdicts"]
        self.assertEqual(iv["welle_1_producer"], "WELLE-1-PRODUCER-READY")
        self.assertEqual(
            iv["welle_1_audit_anchor"], "WELLE-1-AUDIT-ANCHOR-READY"
        )
        self.assertEqual(
            iv["live_smoke_stability_window"],
            "LIVE-SMOKE-STABILITY-WINDOW-READY",
        )
        self.assertEqual(iv["auto_scheduler"], "CUTOVER-DAY-MORGEN-READY")

    def test_input_verdicts_none_on_missing(self) -> None:
        envelopes = dict(self.envelopes)
        envelopes["live_smoke_stability_window"] = None
        env = self.mod.build_envelope(envelopes)
        self.assertIsNone(env["input_verdicts"]["live_smoke_stability_window"])

    def test_window_in_t0_week_true_for_kw_24(self) -> None:
        env = self.mod.build_envelope(self.envelopes, iso_week=24)
        self.assertTrue(env["window"]["in_t0_week"])
        self.assertEqual(env["window"]["iso_week"], 24)

    def test_window_in_t0_week_false_for_kw_25(self) -> None:
        env = self.mod.build_envelope(self.envelopes, iso_week=25)
        self.assertFalse(env["window"]["in_t0_week"])


class Tag70AggregatorCLITests(unittest.TestCase):
    """CLI round-trip: envelope JSON written to disk matches build_envelope."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_cli_writes_intact_verdict_on_all_green(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            _write_envelope(tdp / "p.json", "WELLE-1-PRODUCER-READY")
            _write_envelope(tdp / "a.json", "WELLE-1-AUDIT-ANCHOR-READY")
            _write_envelope(
                tdp / "l.json", "LIVE-SMOKE-STABILITY-WINDOW-READY"
            )
            _write_envelope(tdp / "s.json", "CUTOVER-DAY-MORGEN-READY")
            out_path = tdp / "agg.json"
            rc = self.mod.main(
                [
                    "--producer-envelope",
                    str(tdp / "p.json"),
                    "--audit-anchor-envelope",
                    str(tdp / "a.json"),
                    "--live-smoke-envelope",
                    str(tdp / "l.json"),
                    "--auto-scheduler-envelope",
                    str(tdp / "s.json"),
                    "--iso-week",
                    "24",
                    "--output",
                    str(out_path),
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(out_path.exists())
            env = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(env["verdict"], "T0-INTEGRATION-INTACT")

    def test_cli_writes_defect_on_missing_envelope_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            # Only three envelopes; the fourth is omitted from CLI.
            _write_envelope(tdp / "p.json", "WELLE-1-PRODUCER-READY")
            _write_envelope(tdp / "a.json", "WELLE-1-AUDIT-ANCHOR-READY")
            _write_envelope(
                tdp / "l.json", "LIVE-SMOKE-STABILITY-WINDOW-READY"
            )
            out_path = tdp / "agg.json"
            rc = self.mod.main(
                [
                    "--producer-envelope",
                    str(tdp / "p.json"),
                    "--audit-anchor-envelope",
                    str(tdp / "a.json"),
                    "--live-smoke-envelope",
                    str(tdp / "l.json"),
                    "--output",
                    str(out_path),
                ]
            )
            self.assertEqual(rc, 0)
            env = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(env["verdict"], "T0-INTEGRATION-DEFECT")
            self.assertIn("auto_scheduler", env["failed_steps"])

    def test_cli_writes_envelope_with_github_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            _write_envelope(tdp / "p.json", "WELLE-1-PRODUCER-READY")
            _write_envelope(tdp / "a.json", "WELLE-1-AUDIT-ANCHOR-READY")
            _write_envelope(
                tdp / "l.json", "LIVE-SMOKE-STABILITY-WINDOW-READY"
            )
            _write_envelope(tdp / "s.json", "CUTOVER-DAY-MORGEN-READY")
            out_path = tdp / "agg.json"
            rc = self.mod.main(
                [
                    "--producer-envelope",
                    str(tdp / "p.json"),
                    "--audit-anchor-envelope",
                    str(tdp / "a.json"),
                    "--live-smoke-envelope",
                    str(tdp / "l.json"),
                    "--auto-scheduler-envelope",
                    str(tdp / "s.json"),
                    "--github-run-id",
                    "70-run-id",
                    "--github-sha",
                    "abc1234",
                    "--github-ref",
                    "refs/pull/9999/merge",
                    "--output",
                    str(out_path),
                ]
            )
            self.assertEqual(rc, 0)
            env = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(env["github_run_id"], "70-run-id")
            self.assertEqual(env["github_sha"], "abc1234")
            self.assertEqual(env["github_ref"], "refs/pull/9999/merge")


class Tag70AggregatorDecisionRuleTests(unittest.TestCase):
    """The exposed decide() helper matches the documented rule."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_decide_all_green_intact(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        self.assertEqual(self.mod.decide(steps), "T0-INTEGRATION-INTACT")

    def test_decide_one_yellow_drift(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        steps["welle_1_producer"] = "yellow"
        self.assertEqual(self.mod.decide(steps), "T0-INTEGRATION-DRIFT")

    def test_decide_one_red_defect(self) -> None:
        steps = {s: "green" for s in self.mod.STAGES}
        steps["live_smoke_stability_window"] = "red"
        self.assertEqual(self.mod.decide(steps), "T0-INTEGRATION-DEFECT")

    def test_decide_red_dominates_yellow(self) -> None:
        steps = {s: "yellow" for s in self.mod.STAGES}
        steps["auto_scheduler"] = "red"
        self.assertEqual(self.mod.decide(steps), "T0-INTEGRATION-DEFECT")


class Tag70AggregatorStageOrderingTests(unittest.TestCase):
    """STAGES tuple matches the chronological T0-Day-1 pipeline order."""

    def setUp(self) -> None:
        self.mod = _load_aggregator()

    def test_stages_chronological_order(self) -> None:
        # producer -> audit-anchor -> live-smoke -> auto-scheduler.
        # This is the order in which the four substrates fire on
        # the actual 2026-06-08 Welle-1-Cutover-Day pipeline.
        self.assertEqual(
            self.mod.STAGES,
            (
                "welle_1_producer",
                "welle_1_audit_anchor",
                "live_smoke_stability_window",
                "auto_scheduler",
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
            # Each map must cover all three trinary slots.
            self.assertEqual(set(vmap.values()), {"green", "yellow", "red"})

    def test_step_results_preserves_stage_order_on_iteration(self) -> None:
        envelopes = {
            "welle_1_producer": {"verdict": "WELLE-1-PRODUCER-READY"},
            "welle_1_audit_anchor": {"verdict": "WELLE-1-AUDIT-ANCHOR-READY"},
            "live_smoke_stability_window": {
                "verdict": "LIVE-SMOKE-STABILITY-WINDOW-READY"
            },
            "auto_scheduler": {"verdict": "CUTOVER-DAY-MORGEN-READY"},
        }
        env = self.mod.build_envelope(envelopes)
        # Python dict preserves insertion order; build_envelope
        # iterates STAGES in declared order, so step_results.keys
        # must match STAGES.
        self.assertEqual(tuple(env["step_results"].keys()), self.mod.STAGES)


class Tag70WorkflowShapeTests(unittest.TestCase):
    """The Tag-70 workflow file has the expected hermetic shape."""

    def setUp(self) -> None:
        self.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_workflow_file_exists(self) -> None:
        self.assertTrue(WORKFLOW_PATH.exists())

    def test_workflow_name_field(self) -> None:
        self.assertIn(
            "name: cutover-day-t0-integration-smoke", self.text
        )

    def test_workflow_declares_five_stages(self) -> None:
        # Five stages: producer / audit-anchor / live-smoke /
        # auto-scheduler / aggregate.
        for stage_line in (
            "Stage 1 -- Welle-1-Producer simulation",
            "Stage 2 -- Welle-1-Audit-Anchor simulation",
            "Stage 3 -- Live-Smoke Stability-Window-Probe simulation",
            "Stage 4 -- Auto-Scheduler simulation",
            "Stage 5 -- Aggregate T0-INTEGRATION verdict",
        ):
            self.assertIn(stage_line, self.text, f"missing: {stage_line}")

    def test_workflow_dispatch_has_drift_and_defect_inject(self) -> None:
        self.assertIn("drift_inject:", self.text)
        self.assertIn("defect_inject:", self.text)

    def test_workflow_invokes_aggregator_from_stage_5(self) -> None:
        self.assertIn(
            "tooling/ci/aggregate_cutover_day_t0_integration.py", self.text
        )

    def test_workflow_uploads_envelope_and_stages_artifacts(self) -> None:
        self.assertIn("cutover-day-t0-integration-verdict", self.text)
        self.assertIn("cutover-day-t0-integration-stages", self.text)

    def test_workflow_permissions_read_only_on_contents(self) -> None:
        self.assertIn("contents: read", self.text)
        # No write permission on contents/actions/issues (this is a
        # hermetic smoke; no gh workflow run fanout).
        self.assertNotIn("contents: write", self.text)
        self.assertNotIn("actions: write", self.text)

    def test_workflow_declares_sandbox_boundary_in_header(self) -> None:
        # The header must explicitly call out the hermetic / no-T0-
        # dispatch property so future readers understand the boundary.
        self.assertIn("Sandbox boundary", self.text)
        self.assertIn("hermetic", self.text)
        self.assertIn("does NOT trigger", self.text)

    def test_workflow_references_all_four_tag_69_substrates(self) -> None:
        # The header should cite the four substrate PRs / owners
        # for the Henrik audit-evidence trail.
        self.assertIn("Selin Tag-69", self.text)
        self.assertIn("Tomas Tag-69", self.text)
        self.assertIn("Noa Tag-69", self.text)
        self.assertIn("Selin Tag-64", self.text)

    def test_workflow_terminal_gate_exits_1_on_defect(self) -> None:
        # The terminal-status step must fail loudly on DEFECT so
        # the workflow surfaces a red check.
        self.assertIn("T0-INTEGRATION-DEFECT", self.text)
        self.assertIn("exit 1", self.text)

    def test_workflow_does_not_invoke_gh_workflow_run(self) -> None:
        # Hermetic posture: no actual gh workflow run dispatch.
        # The header comments document what the workflow does NOT
        # do (mentioning "gh workflow run" as a banned operation),
        # so we filter to non-comment lines before asserting.
        non_comment_lines = [
            line
            for line in self.text.splitlines()
            if not line.lstrip().startswith("#")
        ]
        non_comment_text = "\n".join(non_comment_lines)
        self.assertNotIn("gh workflow run", non_comment_text)


class Tag70AggregatorHelpersTests(unittest.TestCase):
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
            "welle_1_producer", {"verdict": "WELLE-1-PRODUCER-READY"}
        )
        self.assertEqual(status, "green")
        self.assertEqual(note, "")

    def test_normalise_status_red_for_missing_envelope(self) -> None:
        status, note = self.mod._normalise_status("welle_1_producer", None)
        self.assertEqual(status, "red")
        self.assertIn("missing", note.lower())

    def test_normalise_status_red_for_non_string_verdict(self) -> None:
        status, note = self.mod._normalise_status(
            "welle_1_producer", {"verdict": 42}
        )
        self.assertEqual(status, "red")
        self.assertIn("no string", note.lower())


if __name__ == "__main__":
    unittest.main()
