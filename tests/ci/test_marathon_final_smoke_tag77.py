# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic tests for the Tag-77 Marathon-Final-Smoke E2E aggregator.

Auftrag-Anker
-------------

Tag-77 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon
Polish-Phase): Umbrella hermetic Marathon-Final-Smoke E2E that
consolidates the entire Tag-69..Tag-76 substrate-set (seven per-
Welle integration-smokes + Cross-Welle-Stability-Pin + Marathon-
Closeout-Aggregator + Phase-3-COMPLETE-Marker-Audit-Bundle) into
a single MARATHON-FINAL verdict (INTACT / DRIFT / DEFECT).

Brief-vs-canonical reconciliation
---------------------------------

The Tag-77 brief was canonical-aligned. Two reconciliations
surface for the audit trail:

* Brief: "die 7 Welle-Integration-Smokes". Canonical: five
  integration-smoke aggregators (Welle-3..7); Welle-1+2 are audit-
  anchor-only stand-ins. Surfaced in stage_provenance.
* Brief: "Stage 9 Marathon-Closeout-Aggregator + Stage 10 Phase-3-
  COMPLETE-Marker-Audit-Bundle". Canonical: two distinct Tag-76
  substrates with distinct verdict maps.

Scope (aggregator + workflow-shape)
-----------------------------------

This module verifies two surfaces:

* The Tag-77 aggregator helper
  (``tooling/ci/aggregate_marathon_final_smoke.py``):
  - all-green inputs collapse to MARATHON-FINAL-INTACT
  - one-yellow inputs collapse to MARATHON-FINAL-DRIFT
  - one-red inputs collapse to MARATHON-FINAL-DEFECT
  - missing per-stage envelope collapses to DEFECT
  - unknown verdict collapses to DEFECT
  - per-stage notes surface offending stages
  - envelope schema fields present and well-typed
  - per_welle_run_order_anchors surfaces seven anchors
  - stage_provenance surfaces ten stages with tag/owner/kind
  - per_welle_input_verdicts surfaces seven verdicts
  - closeout_substrate_verdicts surfaces three substrate verdicts
  - Brief-vs-canonical reconciliation surfaces all three pins
  - Marathon-Window iso_week filter (24..27)
  - Sandbox-boundary axis declared
  - umbrella_role surfaces consumes_read_only path-list

* The Tag-77 workflow file
  (``.github/workflows/marathon-final-smoke-e2e.yml``):
  - eleven named stages present
  - workflow_dispatch surface includes drift_inject + defect_inject
  - permissions are read-only on contents
  - aggregator helper invoked from the aggregate stage
  - artifact upload steps present for envelope and stages

Hermetic posture
----------------

stdlib + unittest. No subprocess into the network. The aggregator
is loaded as a module via importlib. The workflow is parsed as text.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This test pins only the Tag-77 Marathon-Final-Smoke E2E aggregator
and workflow. It does NOT modify any Tag-76 substrate aggregator,
helper, or test-suite. Per-substrate constants are consumed read-
only from the per-stage envelopes that the workflow assembles.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AGG_PATH = REPO_ROOT / "tooling" / "ci" / "aggregate_marathon_final_smoke.py"
WF_PATH = REPO_ROOT / ".github" / "workflows" / "marathon-final-smoke-e2e.yml"


def _load_aggregator():
    spec = importlib.util.spec_from_file_location("agg_mfs_tag77", AGG_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _welle_envelope(n: int, verdict: str | None = None) -> dict:
    if verdict is None:
        verdict = f"WELLE-{n}-INTACT"
    return {
        "schema_version": 1,
        "stage": f"welle_{n}_integration_smoke",
        "tag": "tag-77",
        "verdict": verdict,
    }


def _cross_welle_envelope(
    verdict: str = "CROSS-WELLE-STABILITY-INTACT",
) -> dict:
    return {
        "schema_version": 1,
        "stage": "cross_welle_stability_pin",
        "tag": "tag-77",
        "verdict": verdict,
    }


def _closeout_envelope(verdict: str = "MARATHON-CLOSEOUT-READY") -> dict:
    return {
        "schema_version": 1,
        "stage": "marathon_closeout_aggregator",
        "tag": "tag-77",
        "verdict": verdict,
    }


def _bundle_envelope(verdict: str = "BUNDLE-READY") -> dict:
    return {
        "schema_version": 1,
        "stage": "phase_3_complete_marker_audit_bundle",
        "tag": "tag-77",
        "verdict": verdict,
    }


def _all_green_envelopes() -> dict:
    e: dict = {
        f"welle_{n}_integration_smoke": _welle_envelope(n) for n in range(1, 8)
    }
    e["cross_welle_stability_pin"] = _cross_welle_envelope()
    e["marathon_closeout_aggregator"] = _closeout_envelope()
    e["phase_3_complete_marker_audit_bundle"] = _bundle_envelope()
    return e


# -- Aggregator-decision tests ---------------------------------------------


class TestAggregatorAllGreen(unittest.TestCase):
    """All-green per-stage inputs collapse to MARATHON-FINAL-INTACT."""

    def test_all_green_yields_intact(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        self.assertEqual(env["verdict"], "MARATHON-FINAL-INTACT")
        self.assertEqual(env["counts"]["red"], 0)
        self.assertEqual(env["counts"]["yellow"], 0)
        self.assertEqual(env["counts"]["green"], 10)
        self.assertEqual(env["failed_steps"], [])
        self.assertEqual(env["per_stage_notes"], {})


class TestAggregatorDriftPerWelle(unittest.TestCase):
    """One-yellow per-Welle input collapses to MARATHON-FINAL-DRIFT."""

    def test_welle_3_drift_yields_drift(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["welle_3_integration_smoke"] = _welle_envelope(
            3, "WELLE-3-DRIFT"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DRIFT")
        self.assertIn("welle_3_integration_smoke", env["failed_steps"])
        self.assertIn("welle_3_integration_smoke", env["per_stage_notes"])
        self.assertEqual(env["counts"]["yellow"], 1)
        self.assertEqual(env["counts"]["red"], 0)

    def test_welle_7_drift_yields_drift(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["welle_7_integration_smoke"] = _welle_envelope(
            7, "WELLE-7-DRIFT"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DRIFT")


class TestAggregatorDriftSubstrate(unittest.TestCase):
    """One-yellow substrate input collapses to MARATHON-FINAL-DRIFT."""

    def test_cross_welle_drift_yields_drift(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["cross_welle_stability_pin"] = _cross_welle_envelope(
            "CROSS-WELLE-STABILITY-DRIFT"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DRIFT")
        self.assertIn("cross_welle_stability_pin", env["failed_steps"])

    def test_closeout_partial_yields_drift(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["marathon_closeout_aggregator"] = _closeout_envelope(
            "PARTIAL"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DRIFT")
        self.assertIn("marathon_closeout_aggregator", env["failed_steps"])

    def test_bundle_partial_yields_drift(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["phase_3_complete_marker_audit_bundle"] = _bundle_envelope(
            "BUNDLE-PARTIAL"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DRIFT")


class TestAggregatorDefectPerWelle(unittest.TestCase):
    """One-red per-Welle input collapses to MARATHON-FINAL-DEFECT."""

    def test_welle_5_defect_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["welle_5_integration_smoke"] = _welle_envelope(
            5, "WELLE-5-DEFECT"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DEFECT")
        self.assertEqual(env["counts"]["red"], 1)


class TestAggregatorDefectSubstrate(unittest.TestCase):
    """One-red substrate input collapses to MARATHON-FINAL-DEFECT."""

    def test_cross_welle_defect_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["cross_welle_stability_pin"] = _cross_welle_envelope(
            "CROSS-WELLE-STABILITY-DEFECT"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DEFECT")

    def test_closeout_defect_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["marathon_closeout_aggregator"] = _closeout_envelope(
            "DEFECT"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DEFECT")

    def test_bundle_defect_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["phase_3_complete_marker_audit_bundle"] = _bundle_envelope(
            "BUNDLE-DEFECT"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DEFECT")


class TestAggregatorMissingEnvelope(unittest.TestCase):
    """Missing per-stage envelope collapses to DEFECT (defect-on-missing)."""

    def test_missing_welle_envelope_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["welle_4_integration_smoke"] = None
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DEFECT")
        self.assertIn("welle_4_integration_smoke", env["per_stage_notes"])
        self.assertIn("missing", env["per_stage_notes"][
            "welle_4_integration_smoke"
        ])

    def test_missing_cross_welle_envelope_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["cross_welle_stability_pin"] = None
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DEFECT")

    def test_missing_closeout_envelope_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["marathon_closeout_aggregator"] = None
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DEFECT")

    def test_missing_bundle_envelope_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["phase_3_complete_marker_audit_bundle"] = None
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DEFECT")


class TestAggregatorUnknownVerdict(unittest.TestCase):
    """Unknown verdict on any stage collapses to DEFECT."""

    def test_unknown_welle_verdict_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["welle_3_integration_smoke"] = _welle_envelope(
            3, "WELLE-3-UNKNOWN"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DEFECT")
        self.assertIn(
            "unknown verdict",
            env["per_stage_notes"]["welle_3_integration_smoke"],
        )

    def test_unknown_closeout_verdict_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["marathon_closeout_aggregator"] = _closeout_envelope(
            "WHATEVER"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DEFECT")


class TestAggregatorMalformedEnvelope(unittest.TestCase):
    """Envelope with no string verdict field collapses to DEFECT."""

    def test_envelope_without_verdict_field_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["welle_2_integration_smoke"] = {
            "schema_version": 1,
            "stage": "welle_2_integration_smoke",
        }
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DEFECT")
        self.assertIn("no string", env["per_stage_notes"][
            "welle_2_integration_smoke"
        ])

    def test_envelope_non_string_verdict_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["welle_6_integration_smoke"] = {
            "schema_version": 1,
            "stage": "welle_6_integration_smoke",
            "verdict": 42,
        }
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "MARATHON-FINAL-DEFECT")


# -- Envelope-schema tests -------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    """The aggregated envelope carries the expected schema surface."""

    def test_top_level_keys(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
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
            "per_welle_run_order_anchors",
            "stage_provenance",
            "per_welle_input_verdicts",
            "closeout_substrate_verdicts",
            "window",
            "decision_rule",
            "brief_vs_canonical_reconciliation",
            "sandbox_boundary",
            "umbrella_role",
        ):
            self.assertIn(key, env, f"missing top-level key '{key}'")

    def test_workflow_and_tag_pinned(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        self.assertEqual(env["workflow"], "marathon-final-smoke-e2e")
        self.assertEqual(env["tag"], "tag-77")

    def test_step_results_ten_stages(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        self.assertEqual(len(env["step_results"]), 10)
        for stage in agg.STAGES:
            self.assertIn(stage, env["step_results"])

    def test_per_welle_run_order_anchors_seven(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        anchors = env["per_welle_run_order_anchors"]
        self.assertEqual(len(anchors), 7)
        for n in range(1, 8):
            self.assertIn(str(n), anchors)
            for field in (
                "iso_cutover_date",
                "iso_signoff_date",
                "iso_week",
                "modul",
            ):
                self.assertIn(field, anchors[str(n)])

    def test_per_welle_run_order_dates_canonical(self) -> None:
        """Per-Welle cutover dates match pre-cutover-acceptance-run-order.md §3."""
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        anchors = env["per_welle_run_order_anchors"]
        # KW-24: Welle-1+2 Doppel-Welle on 2026-06-10
        self.assertEqual(anchors["1"]["iso_cutover_date"], "2026-06-10")
        self.assertEqual(anchors["2"]["iso_cutover_date"], "2026-06-10")
        # KW-25: Welle-3 solo on 2026-06-17
        self.assertEqual(anchors["3"]["iso_cutover_date"], "2026-06-17")
        # KW-26: Welle-4+5 Doppel-Welle on 2026-06-24
        self.assertEqual(anchors["4"]["iso_cutover_date"], "2026-06-24")
        self.assertEqual(anchors["5"]["iso_cutover_date"], "2026-06-24")
        # KW-27: Welle-6+7 Doppel-Welle on 2026-07-01
        self.assertEqual(anchors["6"]["iso_cutover_date"], "2026-07-01")
        self.assertEqual(anchors["7"]["iso_cutover_date"], "2026-07-01")

    def test_stage_provenance_ten_stages(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        prov = env["stage_provenance"]
        self.assertEqual(len(prov), 10)
        for stage in agg.STAGES:
            self.assertIn(stage, prov)
            for field in ("tag", "owner", "kind", "canonical_artefact"):
                self.assertIn(field, prov[stage])

    def test_stage_provenance_welle_1_2_audit_anchor_only(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        prov = env["stage_provenance"]
        self.assertEqual(
            prov["welle_1_integration_smoke"]["kind"],
            "audit-anchor-only-stand-in",
        )
        self.assertEqual(
            prov["welle_2_integration_smoke"]["kind"],
            "audit-anchor-only-stand-in",
        )

    def test_per_welle_input_verdicts_seven(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        verdicts = env["per_welle_input_verdicts"]
        self.assertEqual(len(verdicts), 7)
        for n in range(1, 8):
            self.assertEqual(verdicts[f"welle_{n}"], f"WELLE-{n}-INTACT")

    def test_closeout_substrate_verdicts_three(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        v = env["closeout_substrate_verdicts"]
        self.assertEqual(len(v), 3)
        self.assertEqual(v["cross_welle_stability_pin"],
                         "CROSS-WELLE-STABILITY-INTACT")
        self.assertEqual(v["marathon_closeout_aggregator"],
                         "MARATHON-CLOSEOUT-READY")
        self.assertEqual(v["phase_3_complete_marker_audit_bundle"],
                         "BUNDLE-READY")

    def test_brief_vs_canonical_three_pins(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        recon = env["brief_vs_canonical_reconciliation"]
        self.assertEqual(len(recon), 3)
        for pin in (
            "seven_integration_smokes_framing",
            "closeout_vs_complete_marker_distinct_substrates",
            "anti_pattern_anchor_ap_9",
        ):
            self.assertIn(pin, recon)
            for field in (
                "brief_value",
                "canonical_value",
                "canonical_source",
                "resolution",
            ):
                self.assertIn(field, recon[pin])


class TestWindowFilter(unittest.TestCase):
    """The window filter declares the four Marathon ISO-weeks."""

    def test_marathon_iso_weeks_24_27(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes(), iso_week=25)
        self.assertEqual(env["window"]["marathon_iso_weeks"], [24, 25, 26, 27])
        self.assertTrue(env["window"]["in_marathon_window"])
        self.assertEqual(env["window"]["iso_week"], 25)

    def test_iso_week_outside_marathon(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes(), iso_week=30)
        self.assertFalse(env["window"]["in_marathon_window"])

    def test_iso_week_none(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        self.assertFalse(env["window"]["in_marathon_window"])


class TestSandboxBoundary(unittest.TestCase):
    """The sandbox-boundary axis declares the hermetic posture."""

    def test_sandbox_flags(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        sb = env["sandbox_boundary"]
        self.assertTrue(sb["stdlib_only"])
        self.assertTrue(sb["no_network_io"])
        self.assertTrue(sb["no_actual_welle_dispatch"])
        self.assertTrue(sb["no_gh_workflow_run"])
        self.assertTrue(sb["no_marker_emission"])
        self.assertTrue(sb["no_closeout_signing"])
        self.assertEqual(
            sb["boundary_anchor"], "feedback_sandbox_host_trennung.md"
        )


class TestUmbrellaRole(unittest.TestCase):
    """The umbrella-role axis declares the read-only substrate consumption."""

    def test_consumes_read_only_list(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        ur = env["umbrella_role"]
        self.assertIn("tag_77_role", ur)
        self.assertIn("consumes_read_only", ur)
        self.assertGreaterEqual(len(ur["consumes_read_only"]), 4)
        joined = "\n".join(ur["consumes_read_only"])
        self.assertIn("aggregate_cross_welle_stability.py", joined)
        self.assertIn("verify_marathon_closeout.py", joined)
        self.assertIn("wire_phase_3_complete_audit_bundle.py", joined)


class TestDecideFunction(unittest.TestCase):
    """The decide() function applies the trinary collapse rule."""

    def test_decide_all_green(self) -> None:
        agg = _load_aggregator()
        steps = {f"s{i}": "green" for i in range(10)}
        self.assertEqual(agg.decide(steps), "MARATHON-FINAL-INTACT")

    def test_decide_one_yellow(self) -> None:
        agg = _load_aggregator()
        steps = {f"s{i}": "green" for i in range(9)}
        steps["s9"] = "yellow"
        self.assertEqual(agg.decide(steps), "MARATHON-FINAL-DRIFT")

    def test_decide_one_red(self) -> None:
        agg = _load_aggregator()
        steps = {f"s{i}": "green" for i in range(9)}
        steps["s9"] = "red"
        self.assertEqual(agg.decide(steps), "MARATHON-FINAL-DEFECT")

    def test_decide_red_dominates_yellow(self) -> None:
        agg = _load_aggregator()
        steps = {f"s{i}": "yellow" for i in range(9)}
        steps["s9"] = "red"
        self.assertEqual(agg.decide(steps), "MARATHON-FINAL-DEFECT")


# -- CLI tests --------------------------------------------------------------


class TestCli(unittest.TestCase):
    """End-to-end CLI smoke: writes a verdict envelope to disk."""

    def test_cli_all_green_writes_intact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = pathlib.Path(td)
            envelope_paths: list[tuple[str, dict]] = []
            for n in range(1, 8):
                p = tdp / f"welle-{n}.json"
                p.write_text(json.dumps(_welle_envelope(n)))
                envelope_paths.append((f"--welle-{n}-envelope", p))
            cw = tdp / "cross-welle.json"
            cw.write_text(json.dumps(_cross_welle_envelope()))
            envelope_paths.append(("--cross-welle-stability-envelope", cw))
            co = tdp / "closeout.json"
            co.write_text(json.dumps(_closeout_envelope()))
            envelope_paths.append(("--marathon-closeout-envelope", co))
            bd = tdp / "bundle.json"
            bd.write_text(json.dumps(_bundle_envelope()))
            envelope_paths.append((
                "--phase-3-complete-bundle-envelope",
                bd,
            ))
            out = tdp / "verdict.json"
            argv: list[str] = []
            for flag, path in envelope_paths:
                argv.extend([flag, str(path)])
            argv.extend(["--iso-week", "24", "--output", str(out)])
            rc = subprocess.run(
                [sys.executable, str(AGG_PATH), *argv],
                check=False,
            )
            self.assertEqual(rc.returncode, 0)
            self.assertTrue(out.exists())
            env = json.loads(out.read_text())
            self.assertEqual(env["verdict"], "MARATHON-FINAL-INTACT")

    def test_cli_defect_yields_intact_envelope_still_written(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = pathlib.Path(td)
            argv: list[str] = []
            for n in range(1, 8):
                p = tdp / f"welle-{n}.json"
                v = f"WELLE-{n}-INTACT" if n != 4 else "WELLE-4-DEFECT"
                p.write_text(json.dumps(_welle_envelope(n, v)))
                argv.extend([f"--welle-{n}-envelope", str(p)])
            cw = tdp / "cross-welle.json"
            cw.write_text(json.dumps(_cross_welle_envelope()))
            argv.extend(["--cross-welle-stability-envelope", str(cw)])
            co = tdp / "closeout.json"
            co.write_text(json.dumps(_closeout_envelope()))
            argv.extend(["--marathon-closeout-envelope", str(co)])
            bd = tdp / "bundle.json"
            bd.write_text(json.dumps(_bundle_envelope()))
            argv.extend(["--phase-3-complete-bundle-envelope", str(bd)])
            out = tdp / "verdict.json"
            argv.extend(["--output", str(out)])
            rc = subprocess.run(
                [sys.executable, str(AGG_PATH), *argv],
                check=False,
            )
            self.assertEqual(rc.returncode, 0)
            self.assertTrue(out.exists())
            env = json.loads(out.read_text())
            self.assertEqual(env["verdict"], "MARATHON-FINAL-DEFECT")
            self.assertIn(
                "welle_4_integration_smoke", env["failed_steps"]
            )


# -- Workflow-shape tests --------------------------------------------------


class TestWorkflowShape(unittest.TestCase):
    """The Tag-77 workflow file carries the expected eleven-stage shape."""

    def setUp(self) -> None:
        self.text = WF_PATH.read_text(encoding="utf-8")

    def test_workflow_file_exists(self) -> None:
        self.assertTrue(WF_PATH.exists())

    def test_workflow_name_pinned(self) -> None:
        self.assertIn("name: marathon-final-smoke-e2e", self.text)

    def test_workflow_eleven_stages(self) -> None:
        # Stages 1..11 must all be named.
        for stage_num in range(1, 12):
            marker = f"Stage {stage_num} --"
            self.assertIn(
                marker, self.text, f"missing stage marker '{marker}'"
            )

    def test_workflow_seven_welle_stages(self) -> None:
        for n in range(1, 8):
            self.assertIn(f"Welle-{n} Integration-Smoke envelope", self.text)

    def test_workflow_stage_8_cross_welle(self) -> None:
        self.assertIn("Cross-Welle-Stability-Pin envelope", self.text)
        self.assertIn("CROSS-WELLE-STABILITY-INTACT", self.text)

    def test_workflow_stage_9_closeout(self) -> None:
        self.assertIn("Marathon-Closeout-Aggregator envelope", self.text)
        self.assertIn("MARATHON-CLOSEOUT-READY", self.text)

    def test_workflow_stage_10_bundle(self) -> None:
        self.assertIn("Phase-3-COMPLETE-Marker-Audit-Bundle envelope", self.text)
        self.assertIn("BUNDLE-READY", self.text)

    def test_workflow_stage_11_aggregate(self) -> None:
        self.assertIn("Aggregate MARATHON-FINAL verdict", self.text)

    def test_workflow_dispatch_inputs(self) -> None:
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("drift_inject:", self.text)
        self.assertIn("defect_inject:", self.text)

    def test_workflow_permissions_read_only(self) -> None:
        self.assertIn("permissions:", self.text)
        self.assertIn("contents: read", self.text)

    def test_workflow_invokes_aggregator(self) -> None:
        self.assertIn(
            "tooling/ci/aggregate_marathon_final_smoke.py", self.text
        )

    def test_workflow_artifact_uploads(self) -> None:
        self.assertIn("name: marathon-final-smoke-verdict", self.text)
        self.assertIn("name: marathon-final-smoke-stages", self.text)

    def test_workflow_terminal_status_gate(self) -> None:
        self.assertIn("Terminal-status gate", self.text)
        self.assertIn("MARATHON-FINAL-INTACT", self.text)
        self.assertIn("MARATHON-FINAL-DRIFT", self.text)
        self.assertIn("MARATHON-FINAL-DEFECT", self.text)

    def test_workflow_concurrency_pin(self) -> None:
        self.assertIn("concurrency:", self.text)
        self.assertIn(
            "group: marathon-final-smoke-e2e-${{ github.ref }}", self.text
        )

    def test_workflow_not_required_check_disclaimer(self) -> None:
        self.assertIn("Not a required status check", self.text)


# -- Constants tests -------------------------------------------------------


class TestConstants(unittest.TestCase):
    """Module-level constants pin the canonical surface."""

    def test_stages_tuple_ten_items(self) -> None:
        agg = _load_aggregator()
        self.assertEqual(len(agg.STAGES), 10)
        self.assertEqual(agg.STAGES[0], "welle_1_integration_smoke")
        self.assertEqual(agg.STAGES[6], "welle_7_integration_smoke")
        self.assertEqual(agg.STAGES[7], "cross_welle_stability_pin")
        self.assertEqual(agg.STAGES[8], "marathon_closeout_aggregator")
        self.assertEqual(
            agg.STAGES[9], "phase_3_complete_marker_audit_bundle"
        )

    def test_verdict_constants_pinned(self) -> None:
        agg = _load_aggregator()
        self.assertEqual(agg.VERDICT_INTACT, "MARATHON-FINAL-INTACT")
        self.assertEqual(agg.VERDICT_DRIFT, "MARATHON-FINAL-DRIFT")
        self.assertEqual(agg.VERDICT_DEFECT, "MARATHON-FINAL-DEFECT")

    def test_per_stage_verdict_maps_present(self) -> None:
        agg = _load_aggregator()
        self.assertEqual(len(agg.STAGE_VERDICT_MAPS), 10)
        # Per-Welle maps
        for n in range(1, 8):
            stage = f"welle_{n}_integration_smoke"
            m = agg.STAGE_VERDICT_MAPS[stage]
            self.assertEqual(m[f"WELLE-{n}-INTACT"], "green")
            self.assertEqual(m[f"WELLE-{n}-DRIFT"], "yellow")
            self.assertEqual(m[f"WELLE-{n}-DEFECT"], "red")
        # Substrate maps
        self.assertEqual(
            agg.STAGE_VERDICT_MAPS["cross_welle_stability_pin"][
                "CROSS-WELLE-STABILITY-INTACT"
            ],
            "green",
        )
        self.assertEqual(
            agg.STAGE_VERDICT_MAPS["marathon_closeout_aggregator"][
                "MARATHON-CLOSEOUT-READY"
            ],
            "green",
        )
        self.assertEqual(
            agg.STAGE_VERDICT_MAPS["phase_3_complete_marker_audit_bundle"][
                "BUNDLE-READY"
            ],
            "green",
        )


if __name__ == "__main__":
    unittest.main()
