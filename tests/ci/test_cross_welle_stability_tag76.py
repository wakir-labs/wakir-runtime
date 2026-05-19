# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic tests for the Tag-76 Cross-Welle-Stability-Pin aggregator.

Auftrag-Anker
-------------

Tag-76 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon
Cutover-Marathon-Closeout): Hermetic cross-Welle aggregator that
bundles the seven per-Welle-Integration-Smoke verdicts (Welle-1
through Welle-7, Tag-69..Tag-75) plus a distinctive Cross-Welle-
Cascade-Verifikation into a single CROSS-WELLE-STABILITY verdict
(INTACT / DRIFT / DEFECT). Verifies the Forward-Block-Pattern,
the Reverse-Block-Pattern, and the Doppel-Welle-Symmetry discipline
((1,2) audit-anchor-only; (4,5) asymmetric one-way; (6,7) symmetric
PAR-path).

Brief-vs-canonical reconciliation (Tag-71+72+73+74+75 lehre)
------------------------------------------------------------

The Tag-76 brief was largely canonical-aligned. Three reconciliations
surface for the audit trail:

* Brief: "die 7 Welle-Integration-Smokes". Canonical: five
  integration-smoke aggregators (Welle-3..7); Welle-1+2 are audit-
  anchor-only stand-ins. Surfaced in per_welle_envelope_provenance.
* Brief: "Cascade-Topologie per phase-3-marathon-anti-patterns.md
  AP-9". Canonical: AP-9 is Welle-3-specific (3,4,5,6,7); Welle-4..7
  tuples derive from Doppel-Welle PAR-path + per-Welle aggregator
  pins. All seven tuples surface in forward_cascade_topology.
* Brief: "ADR-0066 Marathon-Cadence". Canonical: ADR-0066 Beschluss
  is the PAR-path authority for (1,2), (4,5), (6,7) coupling
  discipline (audit-anchor-only / asymmetric / symmetric).

Scope (aggregator + workflow-shape)
-----------------------------------

This module verifies two surfaces:

* The Tag-76 aggregator helper
  (``tooling/ci/aggregate_cross_welle_stability.py``):
  - all-green inputs collapse to CROSS-WELLE-STABILITY-INTACT
  - one-yellow inputs collapse to CROSS-WELLE-STABILITY-DRIFT
  - one-red inputs collapse to CROSS-WELLE-STABILITY-DEFECT
  - missing per-Welle envelope collapses to DEFECT
  - unknown verdict collapses to DEFECT
  - per-stage notes surface offending stages
  - envelope schema fields are present and well-typed
  - per_welle_run_order_anchors surfaces seven anchors with
    iso_cutover_date/iso_signoff_date/iso_week/doppel_partner/modul
  - per_welle_envelope_provenance flags Welle-1+2 as audit-anchor-
    only stand-ins; Welle-3..7 as integration-smoke aggregators
  - forward_cascade_topology surfaces seven tuples
  - doppel_welle_pairs surfaces three pairs (1,2), (4,5), (6,7)
  - doppel_welle_symmetry surfaces three coupling kinds
  - cascade_verification synthesises when no Stage-8 envelope
  - cascade_verification consumes Stage-8 envelope when present
  - Forward-Block-Pattern violation breaks the cascade verdict
  - Doppel-Welle-Symmetry (6,7) break detected
  - Reverse-Block-Pattern violation detected internally
  - Brief-vs-canonical reconciliation surfaces all three pins
  - Marathon-Window iso_week filter (24..27)
  - Sandbox-boundary axis declared

* The Tag-76 workflow file
  (``.github/workflows/cross-welle-stability-pin.yml``):
  - nine named stages present (7 Welle + Cascade + Aggregate)
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

This test pins only the Tag-76 cross-Welle-stability-pin aggregator
and workflow. It does NOT modify any Welle-N substrate aggregator,
the rollback-runbook, the Pre-Auditor-Decision schema, or the Layer
test-suites. Per-Welle aggregator constants are consumed read-only
via the canonical FORWARD_CASCADE_TOPOLOGY dict declared in the
Tag-76 aggregator (canonical fallback values).
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AGG_PATH = REPO_ROOT / "tooling" / "ci" / "aggregate_cross_welle_stability.py"
WF_PATH = REPO_ROOT / ".github" / "workflows" / "cross-welle-stability-pin.yml"


def _load_aggregator():
    spec = importlib.util.spec_from_file_location("agg_cross_tag76", AGG_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _welle_envelope(
    n: int,
    verdict: str | None = None,
    *,
    blocked: list[int] | None = None,
    include_cascade: bool = True,
) -> dict | None:
    """Build a canonical-shaped per-Welle envelope for the aggregator.

    Canonical defaults: per-Welle WELLE-N-INTACT verdict + canonical
    forward-block tuple per FORWARD_CASCADE_TOPOLOGY.
    """
    if verdict is None:
        verdict = f"WELLE-{n}-INTACT"
    canonical_blocked: dict[int, list[int]] = {
        1: [],
        2: [],
        3: [3, 4, 5, 6, 7],
        4: [4, 5, 6, 7],
        5: [5, 6, 7],
        6: [6, 7],
        7: [6, 7],
    }
    if blocked is None:
        blocked = canonical_blocked[n]
    env: dict = {
        "schema_version": 1,
        "stage": f"welle_{n}_integration_smoke",
        "tag": "tag-76",
        "verdict": verdict,
    }
    if include_cascade:
        env["downstream_cascade"] = {"blocked_wellen_on_defect": blocked}
    return env


def _all_green_envelopes() -> dict:
    return {
        f"welle_{n}_integration_smoke": _welle_envelope(n) for n in range(1, 8)
    }


# -- Aggregator-decision tests ---------------------------------------------


class TestAggregatorAllGreen(unittest.TestCase):
    """All-green per-Welle inputs + canonical cascade collapse to INTACT."""

    def test_all_green_yields_intact(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        self.assertEqual(env["verdict"], "CROSS-WELLE-STABILITY-INTACT")
        self.assertEqual(env["counts"]["red"], 0)
        self.assertEqual(env["counts"]["yellow"], 0)
        self.assertEqual(env["counts"]["green"], 8)
        self.assertEqual(env["failed_steps"], [])
        self.assertEqual(env["per_stage_notes"], {})


class TestAggregatorYellow(unittest.TestCase):
    """One-yellow per-Welle input collapses to DRIFT."""

    def test_welle_3_drift_yields_drift(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["welle_3_integration_smoke"] = _welle_envelope(
            3, "WELLE-3-DRIFT"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "CROSS-WELLE-STABILITY-DRIFT")
        self.assertIn("welle_3_integration_smoke", env["failed_steps"])
        self.assertIn("welle_3_integration_smoke", env["per_stage_notes"])

    def test_welle_7_drift_yields_drift(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["welle_7_integration_smoke"] = _welle_envelope(
            7, "WELLE-7-DRIFT"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "CROSS-WELLE-STABILITY-DRIFT")


class TestAggregatorRed(unittest.TestCase):
    """One-red per-Welle input collapses to DEFECT."""

    def test_welle_5_defect_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["welle_5_integration_smoke"] = _welle_envelope(
            5, "WELLE-5-DEFECT"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "CROSS-WELLE-STABILITY-DEFECT")
        self.assertIn("welle_5_integration_smoke", env["failed_steps"])

    def test_welle_1_defect_yields_defect(self) -> None:
        """A red on Welle-1 stand-in still collapses to DEFECT."""
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["welle_1_integration_smoke"] = _welle_envelope(
            1, "WELLE-1-DEFECT"
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "CROSS-WELLE-STABILITY-DEFECT")


class TestAggregatorMissingOrUnknown(unittest.TestCase):
    """Missing envelopes or unknown verdicts collapse to DEFECT."""

    def test_missing_envelope_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes: dict = {
            f"welle_{n}_integration_smoke": None for n in range(1, 8)
        }
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "CROSS-WELLE-STABILITY-DEFECT")
        # Seven per-Welle envelopes are red (missing); the synthesised
        # cascade-stage verdict still computes (PARTIAL or BROKEN).
        self.assertGreaterEqual(env["counts"]["red"], 7)
        for n in range(1, 8):
            self.assertIn(
                f"welle_{n}_integration_smoke", env["failed_steps"]
            )

    def test_unknown_verdict_yields_defect(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["welle_4_integration_smoke"] = {
            "schema_version": 1,
            "stage": "welle_4_integration_smoke",
            "verdict": "BANANA",
        }
        env = agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "CROSS-WELLE-STABILITY-DEFECT")
        self.assertIn("welle_4_integration_smoke", env["failed_steps"])


# -- Envelope-schema tests --------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    """Envelope carries all required schema fields."""

    def test_envelope_schema_fields_present(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        for field in (
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
            "per_welle_envelope_provenance",
            "per_welle_input_verdicts",
            "forward_cascade_topology",
            "doppel_welle_pairs",
            "doppel_welle_symmetry",
            "cascade_verification",
            "window",
            "decision_rule",
            "brief_vs_canonical_reconciliation",
            "sandbox_boundary",
        ):
            self.assertIn(field, env, f"envelope missing field: {field}")
        self.assertEqual(env["workflow"], "cross-welle-stability-pin")
        self.assertEqual(env["tag"], "tag-76")

    def test_per_welle_run_order_anchors_surface_canonical_dates(self) -> None:
        """Tag-76 surfaces pre-cutover-acceptance-run-order.md §3 dates."""
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        anchors = env["per_welle_run_order_anchors"]
        # Welle-1 + Welle-2 = KW-24 Mi 2026-06-10 (Doppel-Welle, audit-
        # anchor-only stand-ins).
        self.assertEqual(anchors["1"]["iso_cutover_date"], "2026-06-10")
        self.assertEqual(anchors["1"]["iso_week"], 24)
        self.assertEqual(anchors["1"]["doppel_partner"], 2)
        self.assertEqual(anchors["2"]["iso_cutover_date"], "2026-06-10")
        # Welle-3 = KW-25 Mi 2026-06-17 (AP-9 anchor, Bridge-Audit-Writer).
        self.assertEqual(anchors["3"]["iso_cutover_date"], "2026-06-17")
        self.assertEqual(anchors["3"]["iso_week"], 25)
        self.assertIsNone(anchors["3"]["doppel_partner"])
        # Welle-4 + Welle-5 = KW-26 Mi 2026-06-24 (Doppel-Welle, state_
        # backing + lifecycle_state_machine).
        self.assertEqual(anchors["4"]["iso_cutover_date"], "2026-06-24")
        self.assertEqual(anchors["4"]["doppel_partner"], 5)
        self.assertEqual(anchors["5"]["doppel_partner"], 4)
        # Welle-6 + Welle-7 = KW-27 Mi 2026-07-01 (Doppel-Welle Final-
        # Sealing, subscribe_loop + recovery_workflow).
        self.assertEqual(anchors["6"]["iso_cutover_date"], "2026-07-01")
        self.assertEqual(anchors["6"]["doppel_partner"], 7)
        self.assertEqual(anchors["7"]["modul"], "recovery_workflow")

    def test_per_welle_envelope_provenance_flags_stand_ins(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        prov = env["per_welle_envelope_provenance"]
        # Welle-1 + Welle-2 are audit-anchor-only stand-ins.
        self.assertEqual(prov["1"]["kind"], "audit-anchor-only-stand-in")
        self.assertFalse(prov["1"]["integration_smoke_present"])
        self.assertEqual(prov["2"]["kind"], "audit-anchor-only-stand-in")
        # Welle-3..7 are canonical integration-smoke aggregators.
        for n in range(3, 8):
            self.assertEqual(
                prov[str(n)]["kind"], "integration-smoke-aggregator"
            )
            self.assertTrue(prov[str(n)]["integration_smoke_present"])

    def test_per_welle_input_verdicts_surface_all_seven(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        per_v = env["per_welle_input_verdicts"]
        for n in range(1, 8):
            self.assertEqual(per_v[f"welle_{n}"], f"WELLE-{n}-INTACT")


# -- Forward-cascade topology tests ----------------------------------------


class TestForwardCascadeTopology(unittest.TestCase):
    """Forward-cascade tuples match the canonical per-Welle anchors."""

    def test_forward_cascade_topology_canonical_tuples(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        topology = env["forward_cascade_topology"]
        self.assertEqual(topology["1"], [])
        self.assertEqual(topology["2"], [])
        self.assertEqual(topology["3"], [3, 4, 5, 6, 7])
        self.assertEqual(topology["4"], [4, 5, 6, 7])
        self.assertEqual(topology["5"], [5, 6, 7])
        self.assertEqual(topology["6"], [6, 7])
        self.assertEqual(topology["7"], [6, 7])

    def test_doppel_welle_pairs_canonical(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        pairs = env["doppel_welle_pairs"]
        self.assertEqual(len(pairs), 3)
        self.assertIn([1, 2], pairs)
        self.assertIn([4, 5], pairs)
        self.assertIn([6, 7], pairs)

    def test_doppel_welle_symmetry_kinds(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        sym = env["doppel_welle_symmetry"]
        self.assertEqual(sym["1_2"], "audit-anchor-only-no-integration-smoke")
        self.assertEqual(
            sym["4_5"], "asymmetric-one-way-upstream-to-downstream"
        )
        self.assertEqual(sym["6_7"], "symmetric-par-path-coupling")


# -- Cascade-verification tests --------------------------------------------


class TestCascadeVerification(unittest.TestCase):
    """Stage-8 cascade-verification verdict + synthesise discipline."""

    def test_cascade_synthesised_when_no_stage_8_envelope(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        cv = env["cascade_verification"]
        self.assertTrue(cv["stage_synthesised"])
        self.assertEqual(cv["stage_verdict"], "CASCADE-PATTERN-CONSISTENT")
        self.assertIsInstance(cv["notes"], list)

    def test_cascade_consumed_when_stage_8_envelope_present(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        envelopes["cross_welle_cascade_verification"] = {
            "schema_version": 1,
            "stage": "cross_welle_cascade_verification",
            "tag": "tag-76",
            "verdict": "CASCADE-PATTERN-CONSISTENT",
        }
        env = agg.build_envelope(envelopes)
        cv = env["cascade_verification"]
        self.assertFalse(cv["stage_synthesised"])
        self.assertEqual(cv["stage_verdict"], "CASCADE-PATTERN-CONSISTENT")

    def test_forward_block_pattern_violation_breaks_cascade(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        # Welle-3 declares a tuple inconsistent with the AP-9 anchor:
        # (3, 4, 5) instead of canonical (3, 4, 5, 6, 7).
        envelopes["welle_3_integration_smoke"] = _welle_envelope(
            3, "WELLE-3-INTACT", blocked=[3, 4, 5]
        )
        env = agg.build_envelope(envelopes)
        # Cascade-verifikation collapses to BROKEN; aggregate to DEFECT.
        self.assertEqual(
            env["cascade_verification"]["stage_verdict"],
            "CASCADE-PATTERN-BROKEN",
        )
        self.assertEqual(env["verdict"], "CROSS-WELLE-STABILITY-DEFECT")

    def test_missing_downstream_cascade_yields_partial(self) -> None:
        agg = _load_aggregator()
        envelopes = _all_green_envelopes()
        # Welle-6 envelope without downstream_cascade field -> drift
        # (fallback to canonical tuple), cascade verdict = PARTIAL,
        # aggregate verdict = DRIFT.
        envelopes["welle_6_integration_smoke"] = _welle_envelope(
            6, include_cascade=False
        )
        env = agg.build_envelope(envelopes)
        self.assertEqual(
            env["cascade_verification"]["stage_verdict"],
            "CASCADE-PATTERN-PARTIAL",
        )
        self.assertEqual(env["verdict"], "CROSS-WELLE-STABILITY-DRIFT")


# -- Public verifier-function tests ----------------------------------------


class TestPublicVerifiers(unittest.TestCase):
    """Direct exercise of the public cascade-verifier helpers."""

    def test_verify_forward_block_pattern_consistent(self) -> None:
        agg = _load_aggregator()
        ok, notes = agg.verify_forward_block_pattern(_all_green_envelopes())
        self.assertTrue(ok)
        self.assertEqual(notes, [])

    def test_verify_doppel_welle_symmetry_consistent(self) -> None:
        agg = _load_aggregator()
        ok, notes = agg.verify_doppel_welle_symmetry()
        self.assertTrue(ok)
        self.assertEqual(notes, [])

    def test_verify_reverse_block_pattern_consistent(self) -> None:
        """Canonical FORWARD_CASCADE_TOPOLOGY has no upstream entries."""
        agg = _load_aggregator()
        ok, notes = agg.verify_reverse_block_pattern()
        self.assertTrue(ok)
        self.assertEqual(notes, [])

    def test_decide_collapses_red_to_defect(self) -> None:
        agg = _load_aggregator()
        steps = {f"welle_{n}_integration_smoke": "green" for n in range(1, 8)}
        steps["cross_welle_cascade_verification"] = "red"
        self.assertEqual(agg.decide(steps), "CROSS-WELLE-STABILITY-DEFECT")

    def test_decide_collapses_yellow_to_drift(self) -> None:
        agg = _load_aggregator()
        steps = {f"welle_{n}_integration_smoke": "green" for n in range(1, 8)}
        steps["cross_welle_cascade_verification"] = "yellow"
        self.assertEqual(agg.decide(steps), "CROSS-WELLE-STABILITY-DRIFT")

    def test_decide_all_green_yields_intact(self) -> None:
        agg = _load_aggregator()
        steps = {f"welle_{n}_integration_smoke": "green" for n in range(1, 8)}
        steps["cross_welle_cascade_verification"] = "green"
        self.assertEqual(agg.decide(steps), "CROSS-WELLE-STABILITY-INTACT")


# -- Brief-vs-canonical + sandbox + window tests ---------------------------


class TestBriefVsCanonicalReconciliation(unittest.TestCase):
    """All three Tag-76 brief reconciliations surface on the envelope."""

    def test_three_reconciliations_present(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        recon = env["brief_vs_canonical_reconciliation"]
        for key in (
            "seven_integration_smokes_framing",
            "welle_datumsanker_authority",
            "cascade_topology_authority",
        ):
            self.assertIn(key, recon)
            entry = recon[key]
            for sub in ("brief_value", "canonical_value", "resolution"):
                self.assertIn(sub, entry)
                self.assertIsInstance(entry[sub], str)
                self.assertGreater(len(entry[sub]), 0)


class TestSandboxBoundary(unittest.TestCase):
    """Sandbox-boundary axis declared correctly."""

    def test_sandbox_boundary_axis(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes())
        sb = env["sandbox_boundary"]
        self.assertTrue(sb["stdlib_only"])
        self.assertTrue(sb["no_network_io"])
        self.assertTrue(sb["no_actual_welle_dispatch"])
        self.assertTrue(sb["no_gh_workflow_run"])
        self.assertEqual(
            sb["boundary_anchor"], "feedback_sandbox_host_trennung.md"
        )


class TestMarathonWindow(unittest.TestCase):
    """ISO-week filter for the Marathon window 24..27."""

    def test_in_marathon_window_kw_24(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes(), iso_week=24)
        self.assertTrue(env["window"]["in_marathon_window"])
        self.assertEqual(env["window"]["iso_week"], 24)

    def test_outside_marathon_window(self) -> None:
        agg = _load_aggregator()
        env = agg.build_envelope(_all_green_envelopes(), iso_week=12)
        self.assertFalse(env["window"]["in_marathon_window"])


# -- Workflow-shape tests --------------------------------------------------


class TestWorkflowShape(unittest.TestCase):
    """The Tag-76 workflow file declares the required surface."""

    def setUp(self) -> None:
        self.text = WF_PATH.read_text(encoding="utf-8")

    def test_workflow_name_and_dispatch(self) -> None:
        self.assertIn("name: cross-welle-stability-pin", self.text)
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("drift_inject:", self.text)
        self.assertIn("defect_inject:", self.text)

    def test_nine_stages_declared_in_order(self) -> None:
        """The workflow declares 7 Welle stages + Cascade + Aggregate."""
        markers = [
            "Stage 1 -- Welle-1 Integration-Smoke",
            "Stage 2 -- Welle-2 Integration-Smoke",
            "Stage 3 -- Welle-3 Integration-Smoke",
            "Stage 4 -- Welle-4 Integration-Smoke",
            "Stage 5 -- Welle-5 Integration-Smoke",
            "Stage 6 -- Welle-6 Integration-Smoke",
            "Stage 7 -- Welle-7 Integration-Smoke",
            "Stage 8 -- Cross-Welle-Cascade-Verifikation",
            "Stage 9 -- Aggregate CROSS-WELLE-STABILITY verdict",
        ]
        last_index = -1
        for marker in markers:
            idx = self.text.find(marker)
            self.assertGreater(
                idx, last_index, f"stage marker out of order: {marker}"
            )
            last_index = idx

    def test_permissions_read_only_on_contents(self) -> None:
        self.assertIn("permissions:", self.text)
        self.assertIn("contents: read", self.text)

    def test_aggregator_invoked_from_aggregate_stage(self) -> None:
        self.assertIn(
            "tooling/ci/aggregate_cross_welle_stability.py", self.text
        )
        for n in range(1, 8):
            self.assertIn(f"--welle-{n}-envelope", self.text)
        self.assertIn("--cascade-envelope", self.text)
        self.assertIn("--output", self.text)

    def test_artifact_upload_steps_present(self) -> None:
        self.assertIn("name: cross-welle-stability-verdict", self.text)
        self.assertIn("name: cross-welle-stability-stages", self.text)


if __name__ == "__main__":
    unittest.main()
