# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic tests for the Tag-75 Welle-7 Integration-Smoke.

Auftrag-Anker
-------------

Tag-75 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
Hermetic end-to-end simulation of the five Welle-7 substrates that
fire in sequence on the canonical KW-27 Mi 2026-07-01 Welle-7
recovery_workflow Doppel-Welle-6+7 Cutover-Mittwoch +
KW-27 Fr 2026-07-03 Post-Welle-7 Global-Acceptance pipeline.
The integration-smoke aggregates the Selin Welle-7-Producer, Tomas
Welle-7-Audit-Trail-Anchor, Amara Doppel-Welle-6+7 Coupling-Gate
(W7 side), Amara IIA-1130 Pre-Auditor-Gate, and the Final-Sealing-
Verification substrate envelopes into a single trinary WELLE-7
verdict (INTACT / DRIFT / DEFECT).

Brief-vs-canonical reconciliation (Tag-71+72+73+74 lehre)
---------------------------------------------------------

The Tag-75 brief was largely canonical-aligned. Three reconciliations
remain for the audit trail:

* Brief framing: Welle-7 = "Final-Sealing-Welle". Canonical:
  substrate_modul=recovery_workflow (J2); schedule_role=
  final_sealing_welle. Both framings surfaced on the envelope.
* Brief cited "ADR-0066 vs KW-24-Acceptance §7". ADR-0066 wins;
  KW-24-Acceptance §7 surfaced as parallel-view evidence.
* Brief cited "§11 Pre-Auditor-Disziplin". Full anchor-chain
  surfaced (AP-7 + hot-spot-probe Check-4 + Henrik Tag-39
  Pre-Audit-Bundle + IIA-1130 standard).

Tests pin canonical values verbatim and assert the
``brief_vs_canonical_reconciliation`` envelope field surfaces all
three reconciliations for the Henrik (Zone-N) audit-evidence trail.

Scope (aggregator + workflow-shape)
-----------------------------------

This module verifies two surfaces:

* The Tag-75 aggregator helper
  (``tooling/ci/aggregate_welle_7_integration.py``):
  - all-green inputs collapse to WELLE-7-INTACT
  - one-yellow inputs collapse to WELLE-7-DRIFT
  - one-red inputs collapse to WELLE-7-DEFECT
  - missing envelope on any stage collapses to WELLE-7-DEFECT
  - unknown verdict on any stage collapses to WELLE-7-DEFECT
  - per-stage notes surface the offending stage + verdict
  - envelope schema fields are present and well-typed
  - substrate-provenance carries the five cross-anchor records
  - parallel-substrate-views carry three views
  - sandbox-boundary axis is set correctly
  - welle_7_anchor surfaces 2026-07-01 / KW-27 / Welle-7 /
    recovery_workflow / J2 / doppel-welle-partner=6 / terminal=true
  - forward-cascade fires (6,7) on DEFECT only (symmetric with
    Tag-74)
  - doppel_welle_coupling surface present and well-typed
  - iia_1130_pre_auditor surface present and well-typed
  - final_sealing surface present with three Layer anchors
  - brief_vs_canonical_reconciliation surfaces all three reconciliations
  - Pre-Auditor verdict map covers all five trinary surfaces
  - Final-Sealing verdict map covers READY/PARTIAL/BREAK

* The Tag-75 workflow file
  (``.github/workflows/welle-7-integration-smoke.yml``):
  - six named stages present in declared order
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

This test pins only the Tag-75 Welle-7-integration-smoke aggregator
and workflow. It does NOT modify any Welle-7 substrate workflow
(Selin / Tomas / hot-spot-probe domains), the rollback-runbook J2
helper, the Pre-Auditor-Decision schema (AR-Hand-domain), or the
Layer test-suites (Tag-40 / Tag-41 / Tag-43 domains).
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AGG_PATH = REPO_ROOT / "tooling" / "ci" / "aggregate_welle_7_integration.py"
WF_PATH = REPO_ROOT / ".github" / "workflows" / "welle-7-integration-smoke.yml"


def _load_aggregator():
    spec = importlib.util.spec_from_file_location("agg_w7_tag75", AGG_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_envelopes(
    tmpdir: pathlib.Path,
    producer: str = "WELLE-7-PRODUCER-READY",
    audit: str = "WELLE-7-AUDIT-ANCHOR-READY",
    doppel: str = "DOPPEL-COUPLING-READY",
    pre_auditor: str = "PRE-AUDITOR-APPROVED",
    final_sealing: str = "FINAL-SEALING-READY",
) -> dict[str, pathlib.Path]:
    paths = {}
    spec_map = {
        "producer": ("welle_7_producer", producer),
        "audit": ("welle_7_audit_anchor", audit),
        "doppel": ("doppel_welle_coupling_gate", doppel),
        "pre_auditor": ("iia_1130_pre_auditor_gate", pre_auditor),
        "final_sealing": ("final_sealing_verification", final_sealing),
    }
    for slot, (stage, verdict) in spec_map.items():
        p = tmpdir / f"{slot}.json"
        p.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": stage,
                    "tag": "tag-75",
                    "verdict": verdict,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        paths[slot] = p
    return paths


class TestAggregatorAllGreen(unittest.TestCase):
    """All-green inputs collapse to WELLE-7-INTACT."""

    def test_all_green_yields_intact(self) -> None:
        agg = _load_aggregator()
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            paths = _write_envelopes(tmp)
            envelopes = {
                "welle_7_producer": json.loads(paths["producer"].read_text()),
                "welle_7_audit_anchor": json.loads(paths["audit"].read_text()),
                "doppel_welle_coupling_gate": json.loads(paths["doppel"].read_text()),
                "iia_1130_pre_auditor_gate": json.loads(paths["pre_auditor"].read_text()),
                "final_sealing_verification": json.loads(paths["final_sealing"].read_text()),
            }
            env = agg.build_envelope(envelopes)
            self.assertEqual(env["verdict"], "WELLE-7-INTACT")
            self.assertEqual(env["counts"]["red"], 0)
            self.assertEqual(env["counts"]["yellow"], 0)
            self.assertEqual(env["counts"]["green"], 5)
            self.assertEqual(env["failed_steps"], [])
            self.assertEqual(env["per_stage_notes"], {})


class TestAggregatorYellow(unittest.TestCase):
    """One-yellow inputs collapse to WELLE-7-DRIFT."""

    def test_pre_auditor_pending_yields_drift(self) -> None:
        agg = _load_aggregator()
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            paths = _write_envelopes(tmp, pre_auditor="PRE-AUDITOR-PENDING")
            envelopes = {
                "welle_7_producer": json.loads(paths["producer"].read_text()),
                "welle_7_audit_anchor": json.loads(paths["audit"].read_text()),
                "doppel_welle_coupling_gate": json.loads(paths["doppel"].read_text()),
                "iia_1130_pre_auditor_gate": json.loads(paths["pre_auditor"].read_text()),
                "final_sealing_verification": json.loads(paths["final_sealing"].read_text()),
            }
            env = agg.build_envelope(envelopes)
            self.assertEqual(env["verdict"], "WELLE-7-DRIFT")
            self.assertIn("iia_1130_pre_auditor_gate", env["failed_steps"])
            self.assertIn("iia_1130_pre_auditor_gate", env["per_stage_notes"])

    def test_pre_auditor_missing_yields_drift(self) -> None:
        agg = _load_aggregator()
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            paths = _write_envelopes(tmp, pre_auditor="PRE-AUDITOR-MISSING")
            envelopes = {
                "welle_7_producer": json.loads(paths["producer"].read_text()),
                "welle_7_audit_anchor": json.loads(paths["audit"].read_text()),
                "doppel_welle_coupling_gate": json.loads(paths["doppel"].read_text()),
                "iia_1130_pre_auditor_gate": json.loads(paths["pre_auditor"].read_text()),
                "final_sealing_verification": json.loads(paths["final_sealing"].read_text()),
            }
            env = agg.build_envelope(envelopes)
            self.assertEqual(env["verdict"], "WELLE-7-DRIFT")

    def test_final_sealing_partial_yields_drift(self) -> None:
        agg = _load_aggregator()
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            paths = _write_envelopes(tmp, final_sealing="FINAL-SEALING-PARTIAL")
            envelopes = {
                "welle_7_producer": json.loads(paths["producer"].read_text()),
                "welle_7_audit_anchor": json.loads(paths["audit"].read_text()),
                "doppel_welle_coupling_gate": json.loads(paths["doppel"].read_text()),
                "iia_1130_pre_auditor_gate": json.loads(paths["pre_auditor"].read_text()),
                "final_sealing_verification": json.loads(paths["final_sealing"].read_text()),
            }
            env = agg.build_envelope(envelopes)
            self.assertEqual(env["verdict"], "WELLE-7-DRIFT")


class TestAggregatorRed(unittest.TestCase):
    """One-red inputs collapse to WELLE-7-DEFECT."""

    def test_pre_auditor_rejected_yields_defect(self) -> None:
        agg = _load_aggregator()
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            paths = _write_envelopes(tmp, pre_auditor="PRE-AUDITOR-REJECTED")
            envelopes = {
                "welle_7_producer": json.loads(paths["producer"].read_text()),
                "welle_7_audit_anchor": json.loads(paths["audit"].read_text()),
                "doppel_welle_coupling_gate": json.loads(paths["doppel"].read_text()),
                "iia_1130_pre_auditor_gate": json.loads(paths["pre_auditor"].read_text()),
                "final_sealing_verification": json.loads(paths["final_sealing"].read_text()),
            }
            env = agg.build_envelope(envelopes)
            self.assertEqual(env["verdict"], "WELLE-7-DEFECT")

    def test_pre_auditor_malformed_yields_defect(self) -> None:
        agg = _load_aggregator()
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            paths = _write_envelopes(tmp, pre_auditor="PRE-AUDITOR-MALFORMED")
            envelopes = {
                "welle_7_producer": json.loads(paths["producer"].read_text()),
                "welle_7_audit_anchor": json.loads(paths["audit"].read_text()),
                "doppel_welle_coupling_gate": json.loads(paths["doppel"].read_text()),
                "iia_1130_pre_auditor_gate": json.loads(paths["pre_auditor"].read_text()),
                "final_sealing_verification": json.loads(paths["final_sealing"].read_text()),
            }
            env = agg.build_envelope(envelopes)
            self.assertEqual(env["verdict"], "WELLE-7-DEFECT")

    def test_doppel_partner_defect_yields_defect(self) -> None:
        agg = _load_aggregator()
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            paths = _write_envelopes(tmp, doppel="DOPPEL-COUPLING-PARTNER-DEFECT")
            envelopes = {
                "welle_7_producer": json.loads(paths["producer"].read_text()),
                "welle_7_audit_anchor": json.loads(paths["audit"].read_text()),
                "doppel_welle_coupling_gate": json.loads(paths["doppel"].read_text()),
                "iia_1130_pre_auditor_gate": json.loads(paths["pre_auditor"].read_text()),
                "final_sealing_verification": json.loads(paths["final_sealing"].read_text()),
            }
            env = agg.build_envelope(envelopes)
            self.assertEqual(env["verdict"], "WELLE-7-DEFECT")

    def test_final_sealing_break_yields_defect(self) -> None:
        agg = _load_aggregator()
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            paths = _write_envelopes(tmp, final_sealing="FINAL-SEALING-BREAK")
            envelopes = {
                "welle_7_producer": json.loads(paths["producer"].read_text()),
                "welle_7_audit_anchor": json.loads(paths["audit"].read_text()),
                "doppel_welle_coupling_gate": json.loads(paths["doppel"].read_text()),
                "iia_1130_pre_auditor_gate": json.loads(paths["pre_auditor"].read_text()),
                "final_sealing_verification": json.loads(paths["final_sealing"].read_text()),
            }
            env = agg.build_envelope(envelopes)
            self.assertEqual(env["verdict"], "WELLE-7-DEFECT")


class TestAggregatorMissingOrUnknown(unittest.TestCase):
    """Missing envelopes or unknown verdicts collapse to WELLE-7-DEFECT."""

    def test_missing_envelope_yields_defect(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(
            {
                "welle_7_producer": None,
                "welle_7_audit_anchor": None,
                "doppel_welle_coupling_gate": None,
                "iia_1130_pre_auditor_gate": None,
                "final_sealing_verification": None,
            }
        )
        self.assertEqual(env["verdict"], "WELLE-7-DEFECT")
        self.assertEqual(env["counts"]["red"], 5)
        self.assertEqual(env["failed_steps"], list(agg.STAGES))

    def test_unknown_verdict_yields_defect(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(
            {
                "welle_7_producer": {"verdict": "WELLE-7-PRODUCER-READY"},
                "welle_7_audit_anchor": {"verdict": "BANANA"},
                "doppel_welle_coupling_gate": {"verdict": "DOPPEL-COUPLING-READY"},
                "iia_1130_pre_auditor_gate": {"verdict": "PRE-AUDITOR-APPROVED"},
                "final_sealing_verification": {"verdict": "FINAL-SEALING-READY"},
            }
        )
        self.assertEqual(env["verdict"], "WELLE-7-DEFECT")
        self.assertIn("welle_7_audit_anchor", env["per_stage_notes"])


class TestForwardCascadeSymmetric(unittest.TestCase):
    """Welle-7 DEFECT blocks (6,7) under Doppel-Welle PAR-path symmetry.

    Mirrors Tag-74 Welle-6 forward-cascade tuple; attests the symmetric
    coupling on the W7 side per phase-3c-doppel-welle-6-7.md §2.
    """

    def test_intact_no_block(self) -> None:
        agg = _load_aggregator()
        self.assertEqual(agg.downstream_blocked_wellen("WELLE-7-INTACT"), ())

    def test_drift_no_block(self) -> None:
        agg = _load_aggregator()
        self.assertEqual(agg.downstream_blocked_wellen("WELLE-7-DRIFT"), ())

    def test_defect_blocks_6_and_7(self) -> None:
        agg = _load_aggregator()
        self.assertEqual(
            agg.downstream_blocked_wellen("WELLE-7-DEFECT"), (6, 7)
        )

    def test_cascade_symmetry_constant(self) -> None:
        agg = _load_aggregator()
        # Tag-74 Welle-6 fires (6,7) on DEFECT; Tag-75 Welle-7
        # MUST fire the same tuple under PAR-path symmetric coupling.
        self.assertEqual(
            agg.FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT, (6, 7)
        )


class TestEnvelopeSchema(unittest.TestCase):
    """Verdict-envelope schema fields are present and well-typed."""

    def test_envelope_schema_fields(self) -> None:
        agg = _load_aggregator()
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            paths = _write_envelopes(tmp)
            envelopes = {
                "welle_7_producer": json.loads(paths["producer"].read_text()),
                "welle_7_audit_anchor": json.loads(paths["audit"].read_text()),
                "doppel_welle_coupling_gate": json.loads(paths["doppel"].read_text()),
                "iia_1130_pre_auditor_gate": json.loads(paths["pre_auditor"].read_text()),
                "final_sealing_verification": json.loads(paths["final_sealing"].read_text()),
            }
            env = agg.build_envelope(
                envelopes, iso_week=27, github_run_id="42", github_sha="deadbeef",
                github_ref="refs/heads/main",
            )
            for field in (
                "schema_version", "workflow", "tag", "emitted_at_utc",
                "verdict", "step_results", "failed_steps", "per_stage_notes",
                "counts", "welle_7_anchor", "window", "input_verdicts",
                "substrate_provenance", "parallel_substrate_views",
                "doppel_welle_coupling", "downstream_cascade",
                "iia_1130_pre_auditor", "final_sealing", "decision_rule",
                "brief_vs_canonical_reconciliation", "sandbox_boundary",
            ):
                self.assertIn(field, env, f"missing schema field: {field}")
            self.assertEqual(env["workflow"], "welle-7-integration-smoke")
            self.assertEqual(env["tag"], "tag-75")
            self.assertEqual(env["github_run_id"], "42")
            self.assertEqual(env["github_sha"], "deadbeef")
            self.assertEqual(env["github_ref"], "refs/heads/main")
            self.assertEqual(env["window"]["iso_week"], 27)
            self.assertTrue(env["window"]["in_welle_7_week"])

    def test_welle_7_anchor_canonical_values(self) -> None:
        agg = _load_aggregator()
        anchor = {
            "iso_cutover_date": agg.WELLE_7_ISO_CUTOVER_DATE,
            "iso_signoff_date": agg.WELLE_7_ISO_SIGNOFF_DATE,
            "iso_week": agg.WELLE_7_ISO_WEEK,
            "welle_number": agg.WELLE_7_WELLE_NUMBER,
            "substrate_modul": agg.WELLE_7_MODUL_MARATHON,
            "schedule_role": agg.WELLE_7_SCHEDULE_ROLE,
            "rollback_job": agg.WELLE_7_ROLLBACK_JOB,
            "doppel_welle_partner": agg.WELLE_7_DOPPEL_WELLE_PARTNER,
        }
        self.assertEqual(anchor["iso_cutover_date"], "2026-07-01")
        self.assertEqual(anchor["iso_signoff_date"], "2026-07-03")
        self.assertEqual(anchor["iso_week"], 27)
        self.assertEqual(anchor["welle_number"], 7)
        self.assertEqual(anchor["substrate_modul"], "recovery_workflow")
        self.assertEqual(anchor["schedule_role"], "final_sealing_welle")
        self.assertEqual(anchor["rollback_job"], "J2")
        self.assertEqual(anchor["doppel_welle_partner"], 6)


class TestSubstrateProvenance(unittest.TestCase):
    """The five cross-anchor substrate records are present."""

    def test_substrate_provenance_five_entries(self) -> None:
        agg = _load_aggregator()
        self.assertEqual(set(agg.SUBSTRATE_PROVENANCE.keys()), set(agg.STAGES))
        self.assertEqual(
            agg.SUBSTRATE_PROVENANCE["welle_7_producer"]["owner"], "Selin"
        )
        self.assertEqual(
            agg.SUBSTRATE_PROVENANCE["welle_7_audit_anchor"]["owner"], "Tomas"
        )
        for k in (
            "doppel_welle_coupling_gate",
            "iia_1130_pre_auditor_gate",
            "final_sealing_verification",
        ):
            self.assertEqual(agg.SUBSTRATE_PROVENANCE[k]["owner"], "Amara")
        self.assertEqual(
            agg.SUBSTRATE_PROVENANCE["iia_1130_pre_auditor_gate"][
                "decision_owner"
            ].startswith("AR-Hand"),
            True,
        )


class TestParallelSubstrateViews(unittest.TestCase):
    """Three parallel views are surfaced; ADR-0066/Run-Order are canonical."""

    def test_parallel_views_three_with_canonical_pins(self) -> None:
        agg = _load_aggregator()
        views = agg.PARALLEL_SUBSTRATE_VIEWS
        self.assertIn("marathon_rollback_runbook_view", views)
        self.assertIn("kw_24_acceptance_view", views)
        self.assertIn("pre_cutover_run_order_view", views)
        self.assertTrue(
            views["marathon_rollback_runbook_view"]["is_canonical_for_tag_75"]
        )
        self.assertTrue(
            views["pre_cutover_run_order_view"]["is_canonical_for_tag_75"]
        )
        self.assertFalse(
            views["kw_24_acceptance_view"]["is_canonical_for_tag_75"]
        )


class TestIIA1130PreAuditorSurface(unittest.TestCase):
    """IIA-1130 Pre-Auditor envelope surface present and well-typed."""

    def test_iia_1130_surface_fields(self) -> None:
        agg = _load_aggregator()
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            paths = _write_envelopes(tmp)
            envelopes = {
                "welle_7_producer": json.loads(paths["producer"].read_text()),
                "welle_7_audit_anchor": json.loads(paths["audit"].read_text()),
                "doppel_welle_coupling_gate": json.loads(paths["doppel"].read_text()),
                "iia_1130_pre_auditor_gate": json.loads(paths["pre_auditor"].read_text()),
                "final_sealing_verification": json.loads(paths["final_sealing"].read_text()),
            }
            env = agg.build_envelope(envelopes)
            iia = env["iia_1130_pre_auditor"]
            for field in (
                "anchor", "standard", "decision_file", "decision_owner",
                "decision_value_axis", "missing_state_axis",
                "malformed_state_axis",
            ):
                self.assertIn(field, iia, f"iia field missing: {field}")
            self.assertEqual(
                iia["decision_file"], "state/welle-7-pre-auditor-decision.json"
            )
            self.assertIn("AR-Hand", iia["decision_owner"])
            self.assertIn("APPROVED", iia["decision_value_axis"])
            self.assertIn("PENDING", iia["decision_value_axis"])
            self.assertIn("REJECTED", iia["decision_value_axis"])
            self.assertIn("IIA-1130", iia["standard"])
            self.assertIn("AP-7", iia["anchor"])

    def test_pre_auditor_verdict_map_five_surfaces(self) -> None:
        agg = _load_aggregator()
        pre_map = agg.IIA_1130_PRE_AUDITOR_VERDICT_MAP
        self.assertEqual(pre_map["PRE-AUDITOR-APPROVED"], "green")
        self.assertEqual(pre_map["PRE-AUDITOR-PENDING"], "yellow")
        self.assertEqual(pre_map["PRE-AUDITOR-MISSING"], "yellow")
        self.assertEqual(pre_map["PRE-AUDITOR-REJECTED"], "red")
        self.assertEqual(pre_map["PRE-AUDITOR-MALFORMED"], "red")
        self.assertEqual(len(pre_map), 5)


class TestFinalSealingSurface(unittest.TestCase):
    """Final-Sealing surface present with three Layer anchors."""

    def test_final_sealing_layer_anchors(self) -> None:
        agg = _load_aggregator()
        anchors = agg.GLOBAL_ACCEPTANCE_LAYER_ANCHORS
        self.assertEqual(set(anchors.keys()), {
            "l1_state_machine", "l3_marathon_schluss", "l2_record_validation",
        })
        # Canonical Layer-anchor paths per pre-cutover-acceptance-run-order.md
        self.assertEqual(
            anchors["l1_state_machine"]["path"],
            "tests/phase_3c/test_phase_3_final_regression.py",
        )
        self.assertEqual(
            anchors["l3_marathon_schluss"]["path"],
            "tests/phase_3c/test_marathon_schluss_acceptance_drill.py",
        )
        self.assertEqual(
            anchors["l2_record_validation"]["path"],
            "tests/phase_3c/test_cutover_day_e2e_drill.py",
        )
        # Canonical tag + tests_count
        self.assertEqual(anchors["l1_state_machine"]["tag"], "tag-40")
        self.assertEqual(anchors["l1_state_machine"]["tests_count"], 28)
        self.assertEqual(anchors["l3_marathon_schluss"]["tag"], "tag-43")
        self.assertEqual(anchors["l3_marathon_schluss"]["tests_count"], 27)
        self.assertEqual(anchors["l2_record_validation"]["tag"], "tag-41")
        self.assertEqual(anchors["l2_record_validation"]["tests_count"], 45)

    def test_final_sealing_verdict_map_three_surfaces(self) -> None:
        agg = _load_aggregator()
        fs_map = agg.FINAL_SEALING_VERIFICATION_VERDICT_MAP
        self.assertEqual(fs_map["FINAL-SEALING-READY"], "green")
        self.assertEqual(fs_map["FINAL-SEALING-PARTIAL"], "yellow")
        self.assertEqual(fs_map["FINAL-SEALING-BREAK"], "red")
        self.assertEqual(len(fs_map), 3)


class TestBriefVsCanonical(unittest.TestCase):
    """All three brief-vs-canonical reconciliations surface verbatim."""

    def test_three_reconciliations_present(self) -> None:
        agg = _load_aggregator()
        recon = agg.BRIEF_VS_CANONICAL_RECONCILIATION
        self.assertEqual(set(recon.keys()), {
            "welle_7_modul_framing",
            "anchor_trio_authority",
            "pre_auditor_disciplin_anchor_chain",
        })
        # Each entry has the four required reconciliation fields.
        for k, entry in recon.items():
            for field in ("brief_value", "canonical_value", "canonical_source", "resolution"):
                self.assertIn(field, entry, f"{k}: missing {field}")

    def test_anchor_chain_cites_ap_7_and_henrik(self) -> None:
        agg = _load_aggregator()
        entry = agg.BRIEF_VS_CANONICAL_RECONCILIATION[
            "pre_auditor_disciplin_anchor_chain"
        ]
        self.assertIn("AP-7", entry["canonical_value"])
        self.assertIn("AP-7", entry["canonical_source"])
        self.assertIn("Henrik", entry["canonical_source"])

    def test_anchor_trio_resolves_to_adr_0066(self) -> None:
        agg = _load_aggregator()
        entry = agg.BRIEF_VS_CANONICAL_RECONCILIATION["anchor_trio_authority"]
        self.assertIn("ADR-0066", entry["canonical_value"])
        self.assertIn("ADR-0066", entry["resolution"])


class TestSandboxBoundary(unittest.TestCase):
    """Sandbox-boundary axis is set correctly."""

    def test_sandbox_boundary_flags(self) -> None:
        agg = _load_aggregator()
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            paths = _write_envelopes(tmp)
            envelopes = {
                "welle_7_producer": json.loads(paths["producer"].read_text()),
                "welle_7_audit_anchor": json.loads(paths["audit"].read_text()),
                "doppel_welle_coupling_gate": json.loads(paths["doppel"].read_text()),
                "iia_1130_pre_auditor_gate": json.loads(paths["pre_auditor"].read_text()),
                "final_sealing_verification": json.loads(paths["final_sealing"].read_text()),
            }
            env = agg.build_envelope(envelopes)
            sb = env["sandbox_boundary"]
            self.assertTrue(sb["stdlib_only"])
            self.assertTrue(sb["no_network_io"])
            self.assertTrue(sb["no_actual_welle_7_dispatch"])
            self.assertTrue(sb["no_gh_workflow_run"])
            self.assertTrue(sb["no_ar_hand_pre_auditor_decision_emission"])


class TestWorkflowShape(unittest.TestCase):
    """The Tag-75 workflow declares six stages in canonical order."""

    def test_workflow_six_stages_present(self) -> None:
        wf = WF_PATH.read_text(encoding="utf-8")
        self.assertIn("Stage 1 -- Welle-7-Producer simulation", wf)
        self.assertIn("Stage 2 -- Welle-7-Audit-Anchor simulation", wf)
        self.assertIn("Stage 3 -- Doppel-Welle-6+7 Coupling-Gate", wf)
        self.assertIn("Stage 4 -- IIA-1130 Pre-Auditor-Gate", wf)
        self.assertIn("Stage 5 -- Final-Sealing-Verification", wf)
        self.assertIn("Stage 6 -- Aggregate WELLE-7-INTEGRATION verdict", wf)

    def test_workflow_dispatch_inputs(self) -> None:
        wf = WF_PATH.read_text(encoding="utf-8")
        self.assertIn("drift_inject", wf)
        self.assertIn("defect_inject", wf)
        # Five injectable stages
        self.assertIn("producer|audit_anchor|doppel_coupling|pre_auditor|final_sealing", wf)

    def test_workflow_permissions_read_only(self) -> None:
        wf = WF_PATH.read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", wf)

    def test_workflow_invokes_aggregator(self) -> None:
        wf = WF_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "python3 tooling/ci/aggregate_welle_7_integration.py", wf
        )
        # All five envelope arguments must be passed.
        for arg in (
            "--producer-envelope",
            "--audit-anchor-envelope",
            "--doppel-coupling-envelope",
            "--pre-auditor-envelope",
            "--final-sealing-envelope",
        ):
            self.assertIn(arg, wf)

    def test_workflow_artifact_uploads(self) -> None:
        wf = WF_PATH.read_text(encoding="utf-8")
        self.assertIn("Upload Welle-7-integration verdict envelope", wf)
        self.assertIn("Upload per-stage envelopes", wf)
        self.assertIn("welle-7-integration-verdict", wf)
        self.assertIn("welle-7-integration-stages", wf)

    def test_workflow_concurrency_and_terminal_gate(self) -> None:
        wf = WF_PATH.read_text(encoding="utf-8")
        self.assertIn("concurrency:", wf)
        self.assertIn("group: welle-7-integration-smoke-", wf)
        self.assertIn("Terminal-status gate", wf)
        # All three terminal outcomes covered.
        for v in ("WELLE-7-INTACT", "WELLE-7-DRIFT", "WELLE-7-DEFECT"):
            self.assertIn(v, wf)

    def test_workflow_sandbox_boundary_header(self) -> None:
        wf = WF_PATH.read_text(encoding="utf-8")
        self.assertIn("Sandbox boundary", wf)
        self.assertIn("feedback_sandbox_host_trennung.md", wf)
        self.assertIn("operator-hand", wf.lower())


if __name__ == "__main__":
    unittest.main()
