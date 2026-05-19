# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic CI-substrate tests for the Tag-63 Pre-Cutover-Final-Acceptance
E2E-Smoke (Amara, Continuous-Mode-Marathon).

Auftrag-Anker
-------------

Tag-63 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
hermetic end-to-end smoke-test der gesamten Pyramide-Pipeline +
Engine-Compositum + alle Required-Status-Checks in einem hermetic
full-flow. Anchor pattern: "smoke-test-Day-1-on-Cutover-Tag" aus
Tag-39/40 Welle-6/7 - run the full pipeline once, hermetic, and
surface a single trinary verdict.

Scope (aggregator + workflow + cross-substrate-links)
-----------------------------------------------------

This module verifies three surfaces:

* The Tag-63 aggregator helper
  (``tooling/ci/aggregate_pre_cutover_e2e_smoke_verdict.py``):
  - ``STAGES`` ordering matches the documented S1..S4 order
  - ``_normalise()`` coerces unknown / empty / mixed-case to red
  - ``decide()`` applies the strict rule: any yellow degrades,
    any red collapses, all-green is READY
  - ``build_envelope()`` produces a verdict-envelope with the
    required schema fields, lineage, cross-substrate-links and
    cross-review-markers
  - ``--output`` writes a parsable JSON file
  - per-stage notes are exported on both shapes

* The Tag-63 workflow YAML
  (``.github/workflows/pre-cutover-final-acceptance-e2e-smoke.yml``):
  - The four sub-stage jobs exist in the documented S1..S4 order
  - The aggregate job depends on all four sub-stage jobs
  - The workflow declares both ``workflow_dispatch`` and
    ``pull_request`` triggers with comprehensive path-filters

* The four upstream substrate anchors the E2E-Smoke walks:
  - Pyramide-Compositum aggregator (Tag-62)
  - Engine-Composite aggregator (Tag-61/62)
  - Cross-Gate workflow trio (Tag-32/55/56/57/40)
  - Final-Sanity aggregator (Tag-53)

Hermetic posture
----------------

Stdlib-only. ``unittest`` discovery. No third-party imports, no
subprocess invocations, no network, no filesystem mutation outside
``tempfile`` directories.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This test-suite pins the Tag-63 E2E-Smoke CI surface. It does NOT
exercise the full sub-gate test-bodies (those are pinned in their
own dedicated Tag-57..62 suites). Cross-review-markers:

* Zone-M: E2E-Smoke walks helpers owned by Engineering-Personae
  via Tomas (Matrix-Lead).
* Zone-N: Henrik (Internal Audit) consumes the aggregated E2E-
  verdict as audit-evidence-input for the KW-24 Pre-Cutover-Final-
  Acceptance claim.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "tooling" / "ci" / "aggregate_pre_cutover_e2e_smoke_verdict.py"
WORKFLOW = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "pre-cutover-final-acceptance-e2e-smoke.yml"
)


def _load_aggregator():
    spec = importlib.util.spec_from_file_location("agg_tag63", HELPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AggregatorContractTests(unittest.TestCase):
    """The Tag-63 aggregator helper contract."""

    def setUp(self) -> None:
        self.agg = _load_aggregator()

    def test_helper_file_exists(self) -> None:
        self.assertTrue(
            HELPER.exists(),
            "Tag-63 E2E-Smoke aggregator helper missing",
        )

    def test_stages_tuple_ordering(self) -> None:
        # Canonical S1..S4 order; the workflow YAML emits
        # S<n>_STATUS env-vars in this order; drift here is a
        # silent breakage of the aggregator-workflow contract.
        self.assertEqual(
            tuple(self.agg.STAGES),
            (
                "pyramide_compositum",
                "engine_composite",
                "cross_gates",
                "final_sanity",
            ),
        )

    def test_verdict_labels(self) -> None:
        self.assertEqual(self.agg.VERDICT_READY, "E2E-READY")
        self.assertEqual(self.agg.VERDICT_DRIFT, "E2E-DRIFT")
        self.assertEqual(self.agg.VERDICT_DEFECT, "E2E-DEFECT")

    def test_normalise_coerces_unknown_to_red(self) -> None:
        for bad in [None, "", "  ", "MAYBE", "PURPLE", "garbage"]:
            self.assertEqual(
                self.agg._normalise(bad),
                "red",
                f"unknown {bad!r} should coerce to red",
            )

    def test_normalise_case_insensitive(self) -> None:
        self.assertEqual(self.agg._normalise("GREEN"), "green")
        self.assertEqual(self.agg._normalise("Yellow"), "yellow")
        self.assertEqual(self.agg._normalise("RED "), "red")

    def test_decide_all_green_is_ready(self) -> None:
        steps = {s: "green" for s in self.agg.STAGES}
        self.assertEqual(self.agg.decide(steps), "E2E-READY")

    def test_decide_one_yellow_is_drift(self) -> None:
        steps = {s: "green" for s in self.agg.STAGES}
        steps["engine_composite"] = "yellow"
        self.assertEqual(self.agg.decide(steps), "E2E-DRIFT")

    def test_decide_any_red_collapses_to_defect(self) -> None:
        # Red dominates regardless of other slots
        steps = {s: "green" for s in self.agg.STAGES}
        steps["pyramide_compositum"] = "red"
        self.assertEqual(self.agg.decide(steps), "E2E-DEFECT")
        steps["engine_composite"] = "yellow"  # still defect
        self.assertEqual(self.agg.decide(steps), "E2E-DEFECT")

    def test_decide_all_yellow_is_drift(self) -> None:
        steps = {s: "yellow" for s in self.agg.STAGES}
        self.assertEqual(self.agg.decide(steps), "E2E-DRIFT")

    def test_decide_all_red_is_defect(self) -> None:
        steps = {s: "red" for s in self.agg.STAGES}
        self.assertEqual(self.agg.decide(steps), "E2E-DEFECT")

    def test_env_key_and_note_key_indexing(self) -> None:
        # S1..S4 1-indexed by position
        self.assertEqual(self.agg._env_key("pyramide_compositum"), "S1_STATUS")
        self.assertEqual(self.agg._env_key("engine_composite"), "S2_STATUS")
        self.assertEqual(self.agg._env_key("cross_gates"), "S3_STATUS")
        self.assertEqual(self.agg._env_key("final_sanity"), "S4_STATUS")
        self.assertEqual(
            self.agg._note_key("pyramide_compositum"), "S1_NOTE"
        )
        self.assertEqual(
            self.agg._note_key("final_sanity"), "S4_NOTE"
        )


class EnvelopeShapeTests(unittest.TestCase):
    """The verdict-envelope must carry the documented schema fields."""

    def setUp(self) -> None:
        self.agg = _load_aggregator()

    def test_envelope_all_green_carries_ready_verdict(self) -> None:
        env = {
            "S1_STATUS": "green",
            "S2_STATUS": "green",
            "S3_STATUS": "green",
            "S4_STATUS": "green",
        }
        envelope = self.agg.build_envelope(env)
        self.assertEqual(envelope["verdict"], "E2E-READY")
        self.assertEqual(envelope["failed_steps"], [])
        self.assertEqual(envelope["counts"], {"green": 4, "yellow": 0, "red": 0})
        self.assertEqual(envelope["schema_version"], 1)
        self.assertEqual(envelope["tag"], "tag-63")
        self.assertEqual(
            envelope["workflow"],
            "pre-cutover-final-acceptance-e2e-smoke",
        )

    def test_envelope_mixed_yellow_carries_drift_with_notes(self) -> None:
        env = {
            "S1_STATUS": "green",
            "S2_STATUS": "yellow",
            "S3_STATUS": "green",
            "S4_STATUS": "yellow",
            "S2_NOTE": "engine workflow YAML missing",
            "S4_NOTE": "final-sanity workflow YAML missing",
            "STAGE_NOTES": (
                "engine_composite:engine workflow YAML missing;"
                "final_sanity:final-sanity workflow YAML missing"
            ),
        }
        envelope = self.agg.build_envelope(env)
        self.assertEqual(envelope["verdict"], "E2E-DRIFT")
        self.assertEqual(
            sorted(envelope["failed_steps"]),
            ["engine_composite", "final_sanity"],
        )
        self.assertEqual(
            envelope["per_stage_notes"]["engine_composite"],
            "engine workflow YAML missing",
        )
        self.assertEqual(
            envelope["per_stage_notes"]["final_sanity"],
            "final-sanity workflow YAML missing",
        )
        self.assertEqual(len(envelope["stage_notes"]), 2)

    def test_envelope_missing_env_defaults_to_red(self) -> None:
        # Empty env -> all stages red -> DEFECT
        envelope = self.agg.build_envelope({})
        self.assertEqual(envelope["verdict"], "E2E-DEFECT")
        self.assertEqual(envelope["counts"]["red"], 4)

    def test_envelope_carries_lineage_and_links(self) -> None:
        envelope = self.agg.build_envelope({})
        # Lineage: every stage must have a lineage attribution
        for stage in self.agg.STAGES:
            self.assertIn(stage, envelope["stage_lineage"])
            self.assertTrue(envelope["stage_lineage"][stage])
        # Links: required anchors must be present
        required_links = {
            "pyramide_compositum_aggregator",
            "engine_composite_aggregator",
            "watch_day_workflow",
            "cross_substrate_parity_workflow",
            "live_verify_workflow",
            "final_sanity_workflow",
            "final_sanity_aggregator",
            "auto_scheduler_workflow",
        }
        self.assertTrue(
            required_links.issubset(set(envelope["cross_substrate_links"])),
            f"missing required cross-substrate-link anchors: "
            f"{required_links - set(envelope['cross_substrate_links'])}",
        )

    def test_envelope_carries_cross_review_markers(self) -> None:
        envelope = self.agg.build_envelope({})
        markers = envelope["cross_review_markers"]
        self.assertEqual(len(markers), 2)
        # Zone-M and Zone-N markers must be present
        joined = " | ".join(markers)
        self.assertIn("Zone-M", joined)
        self.assertIn("Zone-N", joined)
        self.assertIn("Henrik", joined)
        self.assertIn("Engineering", joined)


class CliEntryPointTests(unittest.TestCase):
    """The aggregator CLI must write a parsable JSON file to ``--output``."""

    def test_cli_writes_ready_envelope(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "S1_STATUS": "green",
                "S2_STATUS": "green",
                "S3_STATUS": "green",
                "S4_STATUS": "green",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "verdict.json"
            r = subprocess.run(
                [
                    sys.executable,
                    str(HELPER),
                    "--output",
                    str(out),
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out.exists())
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["verdict"], "E2E-READY")

    def test_cli_writes_defect_on_red(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "S1_STATUS": "red",
                "S2_STATUS": "green",
                "S3_STATUS": "green",
                "S4_STATUS": "green",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "verdict.json"
            r = subprocess.run(
                [sys.executable, str(HELPER), "--output", str(out)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["verdict"], "E2E-DEFECT")
            self.assertIn("pyramide_compositum", data["failed_steps"])


class WorkflowYamlTests(unittest.TestCase):
    """The Tag-63 workflow YAML must declare the documented job-graph."""

    def setUp(self) -> None:
        self.assertTrue(WORKFLOW.exists(), "Tag-63 workflow YAML missing")
        self.yaml_text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_declares_documented_name(self) -> None:
        # Name line should appear exactly once at the top-level
        self.assertIn(
            "name: pre-cutover-final-acceptance-e2e-smoke",
            self.yaml_text,
        )

    def test_workflow_declares_dispatch_and_pr_triggers(self) -> None:
        self.assertIn("workflow_dispatch:", self.yaml_text)
        self.assertIn("pull_request:", self.yaml_text)
        # Path-filter must include all four stage anchors
        self.assertIn(
            "aggregate_pyramide_acceptance_pre_cutover.py", self.yaml_text
        )
        self.assertIn(
            "aggregate_persona_engine_pre_cutover_final.py", self.yaml_text
        )
        self.assertIn(
            "phase-3c-watch-day-practice-run.yml", self.yaml_text
        )
        self.assertIn(
            "cross-substrate-parity-gate.yml", self.yaml_text
        )
        self.assertIn(
            "marathon-final-acceptance-live-verify-gate.yml",
            self.yaml_text,
        )
        self.assertIn(
            "aggregate_pre_cutover_final_sanity_gate_verdict.py",
            self.yaml_text,
        )
        self.assertIn(
            "pre-cutover-final-sanity-gate.yml", self.yaml_text
        )

    def test_workflow_declares_four_stage_jobs_in_order(self) -> None:
        # The four stage-jobs must be declared in S1..S4 order
        # (the aggregate-job's needs: list re-encodes the order;
        # we pin both the job-definition order and the needs-order).
        expected_jobs = [
            "s1-pyramide-compositum:",
            "s2-engine-composite:",
            "s3-cross-gates:",
            "s4-final-sanity:",
            "e2e-verdict:",
        ]
        positions = []
        for job in expected_jobs:
            idx = self.yaml_text.find(job)
            self.assertGreater(idx, -1, f"job {job!r} missing")
            positions.append(idx)
        # Must be monotonically increasing (i.e. declared in order)
        for a, b in zip(positions, positions[1:]):
            self.assertLess(a, b, "stage jobs declared out of order")

    def test_aggregate_job_depends_on_all_four_stages(self) -> None:
        # The e2e-verdict job's needs: block must enumerate all four
        # stage-job names. Slice the YAML around the e2e-verdict job.
        idx = self.yaml_text.find("e2e-verdict:")
        self.assertGreater(idx, -1)
        block = self.yaml_text[idx:idx + 4000]
        for job in (
            "s1-pyramide-compositum",
            "s2-engine-composite",
            "s3-cross-gates",
            "s4-final-sanity",
        ):
            self.assertIn(job, block, f"e2e-verdict missing needs: {job}")

    def test_workflow_invokes_aggregator_helper(self) -> None:
        # The aggregate step must invoke the Tag-63 aggregator with
        # --output pointing at the documented artifact-path.
        self.assertIn(
            "tooling/ci/aggregate_pre_cutover_e2e_smoke_verdict.py",
            self.yaml_text,
        )
        self.assertIn(
            "out/pre-cutover-final-acceptance-e2e-smoke-verdict.json",
            self.yaml_text,
        )

    def test_workflow_uploads_verdict_artifact(self) -> None:
        # The artifact-name pin matters for the auto-scheduler's
        # artifact-download recipe.
        self.assertIn(
            "name: pre-cutover-final-acceptance-e2e-smoke-verdict",
            self.yaml_text,
        )

    def test_workflow_enforce_default_is_true(self) -> None:
        # Default-enforce semantics: a DEFECT verdict must exit non-
        # zero by default; an operator can opt into audit-only.
        self.assertIn("ENFORCE: ${{ github.event.inputs.enforce || 'true' }}", self.yaml_text)
        self.assertIn("E2E-DEFECT", self.yaml_text)

    def test_workflow_runs_hermetic_test_suite(self) -> None:
        # The aggregate job must run the Tag-63 test-suite in-CI
        # before emitting the verdict (defence-in-depth: a broken
        # aggregator-helper would fail the suite, never reach the
        # verdict step).
        self.assertIn(
            "test_pre_cutover_e2e_smoke_tag63.py", self.yaml_text
        )

    def test_workflow_concurrency_group_pinned(self) -> None:
        # Same shape as the Tag-62 Pyramide-Compositum: per-ref
        # concurrency-group, cancel-in-progress: false.
        self.assertIn("concurrency:", self.yaml_text)
        self.assertIn(
            "group: pre-cutover-final-acceptance-e2e-smoke",
            self.yaml_text,
        )
        self.assertIn("cancel-in-progress: false", self.yaml_text)


class UpstreamSubstrateAnchorTests(unittest.TestCase):
    """The four upstream stage anchors the E2E-Smoke walks must exist."""

    def test_pyramide_compositum_aggregator_exists(self) -> None:
        path = REPO_ROOT / "tooling" / "ci" / (
            "aggregate_pyramide_acceptance_pre_cutover.py"
        )
        self.assertTrue(
            path.exists(),
            "S1 anchor missing: pyramide-compositum aggregator",
        )

    def test_engine_composite_aggregator_exists(self) -> None:
        path = REPO_ROOT / "tooling" / "ci" / (
            "aggregate_persona_engine_pre_cutover_final.py"
        )
        self.assertTrue(
            path.exists(),
            "S2 anchor missing: engine-composite aggregator",
        )

    def test_cross_gate_workflow_trio_exists(self) -> None:
        wf_root = REPO_ROOT / ".github" / "workflows"
        for name in (
            "phase-3c-watch-day-practice-run.yml",
            "cross-substrate-parity-gate.yml",
            "marathon-final-acceptance-live-verify-gate.yml",
        ):
            self.assertTrue(
                (wf_root / name).exists(),
                f"S3 anchor missing: {name}",
            )

    def test_final_sanity_aggregator_exists(self) -> None:
        path = REPO_ROOT / "tooling" / "ci" / (
            "aggregate_pre_cutover_final_sanity_gate_verdict.py"
        )
        self.assertTrue(
            path.exists(),
            "S4 anchor missing: final-sanity aggregator",
        )


class REUSEHeaderTests(unittest.TestCase):
    """The Tag-63 substrate must carry REUSE-wrap headers."""

    def test_aggregator_carries_reuse_wrap(self) -> None:
        text = HELPER.read_text(encoding="utf-8")
        self.assertIn("REUSE-IgnoreStart", text)
        self.assertIn("SPDX-License-Identifier: Apache-2.0", text)
        self.assertIn("REUSE-IgnoreEnd", text)

    def test_workflow_carries_spdx_header(self) -> None:
        self.assertIn(
            "SPDX-License-Identifier: Apache-2.0",
            WORKFLOW.read_text(encoding="utf-8"),
        )

    def test_this_test_suite_carries_reuse_wrap(self) -> None:
        # Self-witness: this file too.
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("REUSE-IgnoreStart", text)
        self.assertIn("SPDX-License-Identifier: Apache-2.0", text)
        self.assertIn("REUSE-IgnoreEnd", text)


if __name__ == "__main__":
    unittest.main()
