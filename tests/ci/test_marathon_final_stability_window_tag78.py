# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic CI-substrate tests for the Tag-78 Marathon-Final-Smoke
Stability-Window-Probe (Amara, Continuous-Mode-Marathon-Polish).

Auftrag-Anker
-------------

Tag-78 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon-
Polish-Phase): Stability-Window-Probe for the Tag-77 Marathon-
Final-Smoke-E2E umbrella (PR #489). Analog to the Tag-69 Noa
Live-Smoke-Stability-Window-Pattern (Pool-8 Promotion-Pre-Run)
applied to the Marathon-Umbrella level: three back-to-back runs
of the Tag-77 aggregator on main with all-INTACT upstream
substrate inputs -> all three return MARATHON-FINAL-INTACT ->
STABILITY-WINDOW-CONFIRMED. Eligible-for-Pre-Cutover-Pre-Run-
reliable-signal claim for the Phase-3-Marathon-Polish-Phase
Pre-Cutover-Readiness gate.

Scope (aggregator + workflow + cross-substrate-links)
-----------------------------------------------------

This module verifies three surfaces:

* The Tag-78 aggregator helper
  (``tooling/ci/aggregate_marathon_final_stability_window.py``):
  - ``VALID_MARATHON_FINAL_VERDICTS`` and ``PER_RUN_STATUSES``
    tuples are the documented canonical values
  - ``_classify_marathon_final_verdict()`` maps MARATHON-FINAL-
    INTACT -> ready, MARATHON-FINAL-DRIFT/DEFECT -> not-ready,
    anything else -> defect
  - ``decide()`` applies the strict rule: any defect collapses,
    any not-ready degrades to NOT-YET, only all-ready-AND-
    all-runs-accounted-for is CONFIRMED
  - ``build_envelope()`` produces a verdict-envelope with the
    required schema fields, pattern-lineage, cross-substrate-
    links and cross-review-markers
  - ``--output`` writes a parsable JSON file
  - per-run notes are preserved on the envelope
  - the aggregator's exit-classification overrides the verdict-
    string when RUN_<i>_EXIT is non-zero

* The Tag-78 workflow YAML
  (``.github/workflows/marathon-final-stability-window-probe.yml``):
  - declared as ``workflow_dispatch`` only (operator-tool)
  - has the documented three stages plus self-verify
  - feeds the Tag-77 Marathon-Final-Smoke aggregator with all-
    INTACT Stage 1..10 envelopes to probe deterministic INTACT-
    given-INTACT behaviour
  - exits non-zero only on STABILITY-WINDOW-DEFECT

* The cross-substrate anchor surface:
  - the Tag-77 Marathon-Final-Smoke aggregator (PR #489, Amara)
    exists and exports the verdict-strings the Tag-78 aggregator
    classifies
  - the Tag-63 REUSE-Wrap Stability-Window-Probe and the Tag-65
    E2E-Smoke + Tag-69 Live-Smoke Stability-Window-Probes exist
    as the pattern-anchor references

Hermetic posture
----------------

stdlib + unittest. No subprocess into the network. The aggregator
is loaded as a module (same pattern as the Tag-65 and Tag-69
tests). Workflow YAML is parsed as bytes for marker presence
(avoids a PyYAML dependency in tests).

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This test pins only the Tag-78 Stability-Window-Probe substrate.
It does NOT probe persona definitions (Aisha-Domaene), WAT-core /
V-907 logic (Tomas-Domaene, Zone-K), identity-substrate (Reza-
Domaene, Zone-L), container-infra (Kai-Domaene, Zone-J), or
persona-engine substrate (Selin-Domaene, Zone-O).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_PATH = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "aggregate_marathon_final_stability_window.py"
)
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "marathon-final-stability-window-probe.yml"
)
TAG77_MARATHON_FINAL_AGGREGATOR_PATH = (
    REPO_ROOT / "tooling" / "ci" / "aggregate_marathon_final_smoke.py"
)
TAG77_MARATHON_FINAL_WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "marathon-final-smoke-e2e.yml"
)
REUSE_WRAP_PROBE_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "reuse-wrap-enforce-flip-stability-window-probe.yml"
)
E2E_SMOKE_PROBE_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "e2e-smoke-stability-window-probe.yml"
)
LIVE_SMOKE_PROBE_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "live-smoke-stability-window-probe.yml"
)


def _load_aggregator():
    """Load the Tag-78 aggregator as a module."""
    mod_name = "aggregate_marathon_final_stability_window_tag78"
    spec = importlib.util.spec_from_file_location(mod_name, AGGREGATOR_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAggregatorConstants(unittest.TestCase):
    """The aggregator declares its canonical verdict-strings and tuples."""

    def setUp(self) -> None:
        self.m = _load_aggregator()

    def test_t01_verdict_constants_are_canonical(self) -> None:
        self.assertEqual(self.m.VERDICT_CONFIRMED, "STABILITY-WINDOW-CONFIRMED")
        self.assertEqual(self.m.VERDICT_NOT_YET, "STABILITY-WINDOW-NOT-YET")
        self.assertEqual(self.m.VERDICT_DEFECT, "STABILITY-WINDOW-DEFECT")

    def test_t02_valid_marathon_final_verdicts_match_tag77_aggregator(self) -> None:
        # Must match the Tag-77 Marathon-Final-Smoke aggregator's
        # verdict-set; the Tag-78 aggregator classifies all of these
        # as known (mapping INTACT -> ready and DRIFT/DEFECT -> not-
        # ready).
        self.assertEqual(
            tuple(self.m.VALID_MARATHON_FINAL_VERDICTS),
            (
                "MARATHON-FINAL-INTACT",
                "MARATHON-FINAL-DRIFT",
                "MARATHON-FINAL-DEFECT",
            ),
        )

    def test_t03_per_run_statuses_are_three_categories(self) -> None:
        self.assertEqual(
            tuple(self.m.PER_RUN_STATUSES),
            ("ready", "not-ready", "defect"),
        )


class TestClassifier(unittest.TestCase):
    """``_classify_marathon_final_verdict`` maps verdict-strings to categories."""

    def setUp(self) -> None:
        self.m = _load_aggregator()

    def test_t04_classify_intact_maps_to_ready(self) -> None:
        self.assertEqual(
            self.m._classify_marathon_final_verdict("MARATHON-FINAL-INTACT"),
            "ready",
        )

    def test_t05_classify_drift_and_defect_map_to_not_ready(self) -> None:
        self.assertEqual(
            self.m._classify_marathon_final_verdict("MARATHON-FINAL-DRIFT"),
            "not-ready",
        )
        self.assertEqual(
            self.m._classify_marathon_final_verdict("MARATHON-FINAL-DEFECT"),
            "not-ready",
        )

    def test_t06_classify_unknown_and_empty_collapse_to_defect(self) -> None:
        # Unknown verdict-strings, empty string, and None all
        # collapse to defect; the probe-substrate is broken if the
        # Tag-77 aggregator did not emit a recognisable verdict.
        self.assertEqual(
            self.m._classify_marathon_final_verdict(None), "defect"
        )
        self.assertEqual(self.m._classify_marathon_final_verdict(""), "defect")
        self.assertEqual(
            self.m._classify_marathon_final_verdict("MAYBE"), "defect"
        )
        self.assertEqual(
            self.m._classify_marathon_final_verdict("ready"), "defect"
        )
        # Lower-cased canonical also collapses (verdict-strings are
        # uppercase by Tag-77 convention).
        self.assertEqual(
            self.m._classify_marathon_final_verdict("marathon-final-intact"),
            "defect",
        )


class TestDecisionRule(unittest.TestCase):
    """``decide()`` applies the strict stability-window rule."""

    def setUp(self) -> None:
        self.m = _load_aggregator()

    def test_t07_all_three_ready_yields_confirmed(self) -> None:
        runs = [
            {"category": "ready"},
            {"category": "ready"},
            {"category": "ready"},
        ]
        self.assertEqual(self.m.decide(runs, 3), self.m.VERDICT_CONFIRMED)

    def test_t08_any_not_ready_yields_not_yet(self) -> None:
        # Exactly one not-ready in three runs -> NOT-YET.
        runs = [
            {"category": "ready"},
            {"category": "not-ready"},
            {"category": "ready"},
        ]
        self.assertEqual(self.m.decide(runs, 3), self.m.VERDICT_NOT_YET)
        # Two not-ready in three runs -> NOT-YET.
        runs = [
            {"category": "not-ready"},
            {"category": "not-ready"},
            {"category": "ready"},
        ]
        self.assertEqual(self.m.decide(runs, 3), self.m.VERDICT_NOT_YET)
        # Three not-ready in three runs -> NOT-YET (no defect, all
        # parsed cleanly, just not eligible).
        runs = [
            {"category": "not-ready"},
            {"category": "not-ready"},
            {"category": "not-ready"},
        ]
        self.assertEqual(self.m.decide(runs, 3), self.m.VERDICT_NOT_YET)

    def test_t09_any_defect_collapses_to_defect(self) -> None:
        # Defect wins over not-ready and ready in the priority order.
        runs = [
            {"category": "ready"},
            {"category": "ready"},
            {"category": "defect"},
        ]
        self.assertEqual(self.m.decide(runs, 3), self.m.VERDICT_DEFECT)
        runs = [
            {"category": "not-ready"},
            {"category": "defect"},
            {"category": "ready"},
        ]
        self.assertEqual(self.m.decide(runs, 3), self.m.VERDICT_DEFECT)

    def test_t10_short_run_count_not_confirmed(self) -> None:
        # Even all-ready cannot CONFIRM if the run-count does not
        # match (defends against a workflow that requests 3 runs
        # but only produces 2 envelopes; the aggregator must NOT
        # silently confirm).
        runs = [
            {"category": "ready"},
            {"category": "ready"},
        ]
        # 3 runs requested but only 2 returned -> NOT-YET.
        self.assertEqual(self.m.decide(runs, 3), self.m.VERDICT_NOT_YET)


class TestEnvelopeBuilder(unittest.TestCase):
    """``build_envelope()`` produces the documented JSON shape."""

    def setUp(self) -> None:
        self.m = _load_aggregator()

    def _env(
        self,
        run_count: int,
        verdicts: list[str],
        exits: list[str] | None = None,
    ) -> dict:
        env: dict[str, str] = {"RUN_COUNT": str(run_count)}
        for i, v in enumerate(verdicts, start=1):
            env[f"RUN_{i}_VERDICT"] = v
            env[f"RUN_{i}_NOTE"] = f"run-{i}-note"
            if exits is not None:
                env[f"RUN_{i}_EXIT"] = exits[i - 1]
        return env

    def test_t11_envelope_has_required_schema_fields(self) -> None:
        env = self._env(
            3,
            [
                "MARATHON-FINAL-INTACT",
                "MARATHON-FINAL-INTACT",
                "MARATHON-FINAL-INTACT",
            ],
        )
        envelope = self.m.build_envelope(env)
        for key in (
            "schema_version",
            "workflow",
            "tag",
            "emitted_at_utc",
            "verdict",
            "run_count",
            "per_run",
            "counts",
            "decision_rule",
            "pattern_lineage",
            "cross_substrate_links",
            "cross_review_markers",
        ):
            self.assertIn(key, envelope, f"missing envelope field {key!r}")
        self.assertEqual(envelope["schema_version"], 1)
        self.assertEqual(envelope["tag"], "tag-78")
        self.assertEqual(
            envelope["workflow"], "marathon-final-stability-window-probe"
        )

    def test_t12_envelope_all_ready_yields_confirmed(self) -> None:
        env = self._env(
            3,
            [
                "MARATHON-FINAL-INTACT",
                "MARATHON-FINAL-INTACT",
                "MARATHON-FINAL-INTACT",
            ],
        )
        envelope = self.m.build_envelope(env)
        self.assertEqual(envelope["verdict"], self.m.VERDICT_CONFIRMED)
        self.assertEqual(envelope["counts"]["ready"], 3)
        self.assertEqual(envelope["counts"]["not_ready"], 0)
        self.assertEqual(envelope["counts"]["defect"], 0)
        # Per-run notes preserved.
        self.assertEqual(envelope["per_run"][0]["note"], "run-1-note")

    def test_t13_envelope_one_drift_yields_not_yet(self) -> None:
        env = self._env(
            3,
            [
                "MARATHON-FINAL-INTACT",
                "MARATHON-FINAL-DRIFT",
                "MARATHON-FINAL-INTACT",
            ],
        )
        envelope = self.m.build_envelope(env)
        self.assertEqual(envelope["verdict"], self.m.VERDICT_NOT_YET)
        self.assertEqual(envelope["counts"]["ready"], 2)
        self.assertEqual(envelope["counts"]["not_ready"], 1)
        self.assertEqual(envelope["counts"]["defect"], 0)

    def test_t14_envelope_non_zero_exit_overrides_verdict_to_defect(self) -> None:
        # Even if a run's verdict-string is MARATHON-FINAL-INTACT, a
        # non-zero exit-code from the per-run aggregator invocation
        # must collapse that run to defect (the probe-substrate
        # itself is broken).
        env = self._env(
            3,
            [
                "MARATHON-FINAL-INTACT",
                "MARATHON-FINAL-INTACT",
                "MARATHON-FINAL-INTACT",
            ],
            exits=["0", "1", "0"],
        )
        envelope = self.m.build_envelope(env)
        self.assertEqual(envelope["verdict"], self.m.VERDICT_DEFECT)
        self.assertEqual(envelope["counts"]["defect"], 1)
        # The middle run's category is defect; the verdict-string
        # itself is preserved on the per_run record for forensics.
        self.assertEqual(envelope["per_run"][1]["category"], "defect")
        self.assertEqual(
            envelope["per_run"][1]["verdict"], "MARATHON-FINAL-INTACT"
        )
        self.assertEqual(envelope["per_run"][1]["exit"], "1")


class TestRunCountCoercion(unittest.TestCase):
    """``_coerce_run_count`` validates and clamps the input."""

    def setUp(self) -> None:
        self.m = _load_aggregator()

    def test_t15_default_run_count_is_three(self) -> None:
        self.assertEqual(self.m._coerce_run_count({}), 3)
        self.assertEqual(self.m._coerce_run_count({"RUN_COUNT": ""}), 3)

    def test_t16_run_count_clamped_to_bounds(self) -> None:
        self.assertEqual(self.m._coerce_run_count({"RUN_COUNT": "0"}), 1)
        self.assertEqual(self.m._coerce_run_count({"RUN_COUNT": "-5"}), 1)
        self.assertEqual(self.m._coerce_run_count({"RUN_COUNT": "11"}), 10)
        self.assertEqual(self.m._coerce_run_count({"RUN_COUNT": "100"}), 10)
        # In-range pass through.
        self.assertEqual(self.m._coerce_run_count({"RUN_COUNT": "5"}), 5)

    def test_t17_run_count_bad_string_falls_back_to_three(self) -> None:
        self.assertEqual(self.m._coerce_run_count({"RUN_COUNT": "abc"}), 3)
        self.assertEqual(self.m._coerce_run_count({"RUN_COUNT": "3.5"}), 3)


class TestCLI(unittest.TestCase):
    """The ``--output`` CLI writes a parseable JSON file."""

    def test_t18_cli_writes_parseable_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "verdict.json"
            env = {
                **os.environ,
                "RUN_COUNT": "3",
                "RUN_1_VERDICT": "MARATHON-FINAL-INTACT",
                "RUN_2_VERDICT": "MARATHON-FINAL-INTACT",
                "RUN_3_VERDICT": "MARATHON-FINAL-INTACT",
                "RUN_1_EXIT": "0",
                "RUN_2_EXIT": "0",
                "RUN_3_EXIT": "0",
            }
            # Strip any pre-existing RUN_<i>_NOTE from the test
            # environment so the CLI invocation is hermetic.
            for k in list(env):
                if k.endswith("_NOTE"):
                    env.pop(k, None)
            res = subprocess.run(
                [
                    sys.executable,
                    str(AGGREGATOR_PATH),
                    "--output",
                    str(out_path),
                ],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue(out_path.exists())
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["verdict"], "STABILITY-WINDOW-CONFIRMED"
            )
            self.assertEqual(payload["run_count"], 3)

    def test_t19_cli_print_stdout_emits_envelope(self) -> None:
        # --print-stdout should also write the envelope to stdout
        # (verifies the CLI dual-output surface).
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "verdict.json"
            env = {
                **os.environ,
                "RUN_COUNT": "3",
                "RUN_1_VERDICT": "MARATHON-FINAL-INTACT",
                "RUN_2_VERDICT": "MARATHON-FINAL-INTACT",
                "RUN_3_VERDICT": "MARATHON-FINAL-INTACT",
                "RUN_1_EXIT": "0",
                "RUN_2_EXIT": "0",
                "RUN_3_EXIT": "0",
            }
            for k in list(env):
                if k.endswith("_NOTE"):
                    env.pop(k, None)
            res = subprocess.run(
                [
                    sys.executable,
                    str(AGGREGATOR_PATH),
                    "--output",
                    str(out_path),
                    "--print-stdout",
                ],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("STABILITY-WINDOW-CONFIRMED", res.stdout)
            # stdout payload must be valid JSON.
            payload = json.loads(res.stdout)
            self.assertEqual(payload["tag"], "tag-78")


class TestWorkflowYAML(unittest.TestCase):
    """The workflow YAML declares the documented surface."""

    def setUp(self) -> None:
        self.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_t20_workflow_exists_with_canonical_name(self) -> None:
        self.assertTrue(WORKFLOW_PATH.exists(), f"missing {WORKFLOW_PATH}")
        self.assertIn(
            "name: marathon-final-stability-window-probe",
            self.text,
        )

    def test_t21_workflow_is_workflow_dispatch_only(self) -> None:
        # The Tag-78 probe is an operator-tool. It must NOT declare
        # pull_request or push triggers (would re-fire on every PR,
        # which is wasteful given the workflow consumes the Tag-77
        # umbrella aggregator).
        self.assertIn("workflow_dispatch:", self.text)
        # Explicit absence-checks for non-dispatch triggers.
        self.assertNotIn("\n  pull_request:", self.text)
        self.assertNotIn("\n  push:", self.text)
        self.assertNotIn("\n  schedule:", self.text)

    def test_t22_workflow_has_three_documented_stages_plus_self_verify(self) -> None:
        # Stage 0 (Validate), Stage 1 (Probe), Stage 2 (Self-verify),
        # Stage 3 (Aggregate). The self-verify is a sub-stage of the
        # three-stage docstring contract.
        for marker in (
            "Stage 0 - Validate inputs",
            "Stage 1 - Probe N consecutive Marathon-Final-Smoke aggregator runs",
            "Stage 2 - Self-verify aggregator substrate",
            "Stage 3 - Aggregate stability-window verdict",
        ):
            self.assertIn(marker, self.text, f"missing stage marker {marker!r}")

    def test_t23_workflow_invokes_tag77_marathon_final_smoke_aggregator(self) -> None:
        # The probe must invoke the Tag-77 Marathon-Final-Smoke
        # aggregator (otherwise it would not be probing the right
        # substrate).
        self.assertIn(
            "tooling/ci/aggregate_marathon_final_smoke.py",
            self.text,
        )

    def test_t24_workflow_exit_non_zero_only_on_defect(self) -> None:
        # The probe is informational; the only non-zero exit is on
        # STABILITY-WINDOW-DEFECT (mirrors the Tag-63 REUSE-Wrap +
        # Tag-65 E2E-Smoke + Tag-69 Live-Smoke Stability-Window-
        # Probes).
        self.assertIn('"${VERDICT}" = "STABILITY-WINDOW-DEFECT"', self.text)
        self.assertIn("exit 1", self.text)

    def test_t25_workflow_feeds_all_ten_stage_envelopes_to_tag77(self) -> None:
        # The probe must construct ten all-INTACT input envelopes
        # for the Tag-77 aggregator's ten-stage upstream surface.
        # Verifies the workflow does not silently drop a stage which
        # would make the probe's "deterministic green-given-green"
        # claim meaningless.
        for arg in (
            "--welle-1-envelope",
            "--welle-2-envelope",
            "--welle-3-envelope",
            "--welle-4-envelope",
            "--welle-5-envelope",
            "--welle-6-envelope",
            "--welle-7-envelope",
            "--cross-welle-stability-envelope",
            "--marathon-closeout-envelope",
            "--phase-3-complete-bundle-envelope",
        ):
            self.assertIn(arg, self.text, f"missing aggregator arg {arg!r}")

    def test_t26_workflow_uploads_verdict_artifact(self) -> None:
        # The verdict envelope must be uploaded as a CI artifact so
        # the operator and Henrik-Audit-sample can consume it after
        # the run completes.
        self.assertIn("upload-artifact@v4", self.text)
        self.assertIn(
            "marathon-final-stability-window-verdict", self.text
        )


class TestCrossSubstrateAnchors(unittest.TestCase):
    """The cross-substrate anchors the Tag-78 probe references all exist."""

    def test_t27_tag77_marathon_final_aggregator_exists(self) -> None:
        # The Tag-78 probe walks the Tag-77 Marathon-Final-Smoke
        # aggregator; if that anchor is missing, the probe is
        # meaningless.
        self.assertTrue(
            TAG77_MARATHON_FINAL_AGGREGATOR_PATH.exists(),
            f"missing Tag-77 aggregator {TAG77_MARATHON_FINAL_AGGREGATOR_PATH}",
        )

    def test_t28_tag77_marathon_final_workflow_exists(self) -> None:
        # The Tag-77 workflow YAML (PR #489) must exist; the Tag-78
        # probe inherits its umbrella verdict-string contract from
        # the Tag-77 aggregator + workflow.
        self.assertTrue(
            TAG77_MARATHON_FINAL_WORKFLOW_PATH.exists(),
            f"missing Tag-77 workflow {TAG77_MARATHON_FINAL_WORKFLOW_PATH}",
        )
        text = TAG77_MARATHON_FINAL_WORKFLOW_PATH.read_text(encoding="utf-8")
        # Tag-77 workflow must declare the MARATHON-FINAL-INTACT/
        # DRIFT/DEFECT verdict surface that the Tag-78 probe reads.
        self.assertIn("MARATHON-FINAL-INTACT", text)
        self.assertIn("MARATHON-FINAL-DRIFT", text)
        self.assertIn("MARATHON-FINAL-DEFECT", text)

    def test_t29_pattern_anchor_probes_exist(self) -> None:
        # The pattern-anchor Stability-Window-Probes (Tag-63 Tomas,
        # Tag-65 Amara, Tag-69 Noa) must exist; the Tag-78 probe
        # inherits its trinary verdict shape and exit-code semantics
        # from this lineage.
        self.assertTrue(
            REUSE_WRAP_PROBE_PATH.exists(),
            f"missing Tag-63 anchor {REUSE_WRAP_PROBE_PATH}",
        )
        self.assertTrue(
            E2E_SMOKE_PROBE_PATH.exists(),
            f"missing Tag-65 anchor {E2E_SMOKE_PROBE_PATH}",
        )
        self.assertTrue(
            LIVE_SMOKE_PROBE_PATH.exists(),
            f"missing Tag-69 anchor {LIVE_SMOKE_PROBE_PATH}",
        )


class TestCrossReviewMarkers(unittest.TestCase):
    """The aggregator emits the documented Zone-M / Zone-N markers."""

    def setUp(self) -> None:
        self.m = _load_aggregator()

    def test_t30_zone_m_and_zone_n_markers_present(self) -> None:
        env = {
            "RUN_COUNT": "3",
            "RUN_1_VERDICT": "MARATHON-FINAL-INTACT",
            "RUN_2_VERDICT": "MARATHON-FINAL-INTACT",
            "RUN_3_VERDICT": "MARATHON-FINAL-INTACT",
        }
        envelope = self.m.build_envelope(env)
        markers_text = "\n".join(envelope["cross_review_markers"])
        # Zone-M: walks Tag-77 Marathon-Final-Smoke (Amara's own
        # substrate, but cross-component because the umbrella
        # consumes ten substrate envelopes owned by Amara + Reza +
        # Tomas + audit-anchor stand-ins from Tomas+Selin).
        self.assertIn("Zone-M", markers_text)
        # Zone-N: Henrik consumes the verdict as audit-evidence-
        # input for the Phase-3-Marathon-Polish-Phase Pre-Cutover-
        # Readiness claim.
        self.assertIn("Zone-N", markers_text)
        self.assertIn("Henrik", markers_text)
        # Pattern-lineage records the upstream anchors.
        self.assertIn(
            "Tag-77",
            envelope["pattern_lineage"]["marathon_final_smoke_anchor"],
        )
        # Cross-substrate-links record the Tag-77 anchor paths.
        self.assertEqual(
            envelope["cross_substrate_links"][
                "marathon_final_smoke_aggregator"
            ],
            "tooling/ci/aggregate_marathon_final_smoke.py",
        )

    def test_t31_pattern_lineage_records_full_anchor_chain(self) -> None:
        # The pattern-lineage must record the full Tag-59 / 63 / 65 /
        # 69 / 77 ancestor chain plus the current owner. This is the
        # audit-trail evidence that the Tag-78 probe inherits its
        # surface from the documented lineage and is not a one-off.
        env = {
            "RUN_COUNT": "3",
            "RUN_1_VERDICT": "MARATHON-FINAL-INTACT",
            "RUN_2_VERDICT": "MARATHON-FINAL-INTACT",
            "RUN_3_VERDICT": "MARATHON-FINAL-INTACT",
        }
        envelope = self.m.build_envelope(env)
        lineage = envelope["pattern_lineage"]
        self.assertIn("Tag-59", lineage["n_run_pattern"])
        self.assertIn("Tag-63", lineage["reuse_wrap_anchor"])
        self.assertIn("Tag-65", lineage["e2e_smoke_anchor"])
        self.assertIn("Tag-69", lineage["live_smoke_anchor"])
        self.assertIn("Tag-77", lineage["marathon_final_smoke_anchor"])
        self.assertIn("Tag-78", lineage["current_owner"])


if __name__ == "__main__":  # pragma: no cover - CLI dispatch
    unittest.main()
