# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic CI-substrate tests for the Tag-65 E2E-Smoke Stability-Window-Probe
(Amara, Continuous-Mode-Marathon).

Auftrag-Anker
-------------

Tag-65 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
Stability-Window-Pre-Run for the Tag-63 Pre-Cutover-Final-
Acceptance E2E-Smoke (PR #400). Analog to the Tag-63 Tomas
Stability-Window-Probe-Pattern (PR #404, REUSE-Wrap-Lint) but
applied to E2E-Smoke instead. Three back-to-back runs on main,
all E2E-READY -> eligible-for-Required-Check-Promotion per the
Tag-64 Required-Status-Check-Wiring-Companion (PR #411 §4 #8).

Scope (aggregator + workflow + cross-substrate-links)
-----------------------------------------------------

This module verifies three surfaces:

* The Tag-65 aggregator helper
  (``tooling/ci/aggregate_e2e_stability_window.py``):
  - ``VALID_E2E_VERDICTS`` and ``PER_RUN_STATUSES`` tuples are
    the documented canonical values
  - ``_classify_e2e_verdict()`` maps E2E-READY -> ready,
    E2E-DRIFT/DEFECT -> not-ready, anything else -> defect
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

* The Tag-65 workflow YAML
  (``.github/workflows/e2e-smoke-stability-window-probe.yml``):
  - declared as ``workflow_dispatch`` only (operator-tool)
  - has the documented three stages plus self-verify
  - feeds the Tag-63 E2E-Smoke aggregator with all-green S1..S4
    inputs to probe deterministic green-given-green behaviour
  - exits non-zero only on STABILITY-WINDOW-DEFECT

* The cross-substrate anchor surface:
  - the Tag-63 E2E-Smoke aggregator (PR #400) exists and exports
    the verdict-strings the Tag-65 aggregator classifies
  - the Tag-63 REUSE-Wrap Stability-Window-Probe (PR #404)
    exists as the pattern-anchor reference
  - the Tag-64 Required-Status-Check-Wiring-Companion (PR #411)
    references the E2E-verdict job as Pool-Position #8

Hermetic posture
----------------

stdlib + unittest. No subprocess into the network. The aggregator
is loaded as a module (same pattern as the Tag-63 test). Workflow
YAML is parsed as bytes for marker presence (avoids a PyYAML
dependency in tests).

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This test pins only the Tag-65 Stability-Window-Probe substrate.
It does NOT probe persona definitions (Aisha-Domaene), WAT-core /
V-907 logic (Tomas-Domaene, Zone-K), identity-substrate (Reza-
Domaene, Zone-L), container-infra (Kai-Domaene, Zone-J), or
persona-engine substrate (Selin-Domaene, Zone-O).
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_PATH = (
    REPO_ROOT / "tooling" / "ci" / "aggregate_e2e_stability_window.py"
)
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "e2e-smoke-stability-window-probe.yml"
)
E2E_SMOKE_AGGREGATOR_PATH = (
    REPO_ROOT / "tooling" / "ci" / "aggregate_pre_cutover_e2e_smoke_verdict.py"
)
REUSE_WRAP_PROBE_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "reuse-wrap-enforce-flip-stability-window-probe.yml"
)
TAG64_COMPANION_DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "branch-protection-required-checks-tag64-companion.md"
)


def _load_aggregator():
    """Load the Tag-65 aggregator as a module."""
    mod_name = "aggregate_e2e_stability_window_tag65"
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

    def test_t02_valid_e2e_verdicts_match_tag63_aggregator(self) -> None:
        # Must match the Tag-63 E2E-Smoke aggregator's verdict-set;
        # the Tag-65 aggregator classifies all of these as known
        # (mapping READY -> ready and DRIFT/DEFECT -> not-ready).
        self.assertEqual(
            tuple(self.m.VALID_E2E_VERDICTS),
            ("E2E-READY", "E2E-DRIFT", "E2E-DEFECT"),
        )

    def test_t03_per_run_statuses_are_three_categories(self) -> None:
        self.assertEqual(
            tuple(self.m.PER_RUN_STATUSES),
            ("ready", "not-ready", "defect"),
        )


class TestClassifier(unittest.TestCase):
    """``_classify_e2e_verdict`` maps verdict-strings to categories."""

    def setUp(self) -> None:
        self.m = _load_aggregator()

    def test_t04_classify_ready_maps_to_ready(self) -> None:
        self.assertEqual(self.m._classify_e2e_verdict("E2E-READY"), "ready")

    def test_t05_classify_drift_and_defect_map_to_not_ready(self) -> None:
        self.assertEqual(
            self.m._classify_e2e_verdict("E2E-DRIFT"), "not-ready"
        )
        self.assertEqual(
            self.m._classify_e2e_verdict("E2E-DEFECT"), "not-ready"
        )

    def test_t06_classify_unknown_and_empty_collapse_to_defect(self) -> None:
        # Unknown verdict-strings, empty string, and None all
        # collapse to defect; the probe-substrate is broken if the
        # E2E-Smoke aggregator did not emit a recognisable verdict.
        self.assertEqual(self.m._classify_e2e_verdict(None), "defect")
        self.assertEqual(self.m._classify_e2e_verdict(""), "defect")
        self.assertEqual(self.m._classify_e2e_verdict("MAYBE"), "defect")
        self.assertEqual(self.m._classify_e2e_verdict("ready"), "defect")


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

    def _env(self, run_count: int, verdicts: list[str], exits: list[str] | None = None) -> dict:
        env: dict[str, str] = {"RUN_COUNT": str(run_count)}
        for i, v in enumerate(verdicts, start=1):
            env[f"RUN_{i}_VERDICT"] = v
            env[f"RUN_{i}_NOTE"] = f"run-{i}-note"
            if exits is not None:
                env[f"RUN_{i}_EXIT"] = exits[i - 1]
        return env

    def test_t11_envelope_has_required_schema_fields(self) -> None:
        env = self._env(3, ["E2E-READY", "E2E-READY", "E2E-READY"])
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
        self.assertEqual(envelope["tag"], "tag-65")
        self.assertEqual(
            envelope["workflow"], "e2e-smoke-stability-window-probe"
        )

    def test_t12_envelope_all_ready_yields_confirmed(self) -> None:
        env = self._env(3, ["E2E-READY", "E2E-READY", "E2E-READY"])
        envelope = self.m.build_envelope(env)
        self.assertEqual(envelope["verdict"], self.m.VERDICT_CONFIRMED)
        self.assertEqual(envelope["counts"]["ready"], 3)
        self.assertEqual(envelope["counts"]["not_ready"], 0)
        self.assertEqual(envelope["counts"]["defect"], 0)
        # Per-run notes preserved.
        self.assertEqual(envelope["per_run"][0]["note"], "run-1-note")

    def test_t13_envelope_one_drift_yields_not_yet(self) -> None:
        env = self._env(3, ["E2E-READY", "E2E-DRIFT", "E2E-READY"])
        envelope = self.m.build_envelope(env)
        self.assertEqual(envelope["verdict"], self.m.VERDICT_NOT_YET)
        self.assertEqual(envelope["counts"]["ready"], 2)
        self.assertEqual(envelope["counts"]["not_ready"], 1)
        self.assertEqual(envelope["counts"]["defect"], 0)

    def test_t14_envelope_non_zero_exit_overrides_verdict_to_defect(self) -> None:
        # Even if a run's verdict-string is E2E-READY, a non-zero
        # exit-code from the per-run aggregator invocation must
        # collapse that run to defect (the probe-substrate itself
        # is broken).
        env = self._env(
            3,
            ["E2E-READY", "E2E-READY", "E2E-READY"],
            exits=["0", "1", "0"],
        )
        envelope = self.m.build_envelope(env)
        self.assertEqual(envelope["verdict"], self.m.VERDICT_DEFECT)
        self.assertEqual(envelope["counts"]["defect"], 1)
        # The middle run's category is defect; the verdict-string
        # itself is preserved on the per_run record for forensics.
        self.assertEqual(envelope["per_run"][1]["category"], "defect")
        self.assertEqual(envelope["per_run"][1]["verdict"], "E2E-READY")
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
                "RUN_1_VERDICT": "E2E-READY",
                "RUN_2_VERDICT": "E2E-READY",
                "RUN_3_VERDICT": "E2E-READY",
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


class TestWorkflowYAML(unittest.TestCase):
    """The workflow YAML declares the documented surface."""

    def setUp(self) -> None:
        self.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_t19_workflow_exists_with_canonical_name(self) -> None:
        self.assertTrue(WORKFLOW_PATH.exists(), f"missing {WORKFLOW_PATH}")
        self.assertIn(
            "name: e2e-smoke-stability-window-probe",
            self.text,
        )

    def test_t20_workflow_is_workflow_dispatch_only(self) -> None:
        # The Tag-65 probe is an operator-tool. It must NOT declare
        # pull_request or push triggers (would re-fire on every PR,
        # which is wasteful given the workflow consumes the Tag-63
        # E2E-Smoke aggregator).
        self.assertIn("workflow_dispatch:", self.text)
        # Explicit absence-checks for non-dispatch triggers.
        self.assertNotIn("\n  pull_request:", self.text)
        self.assertNotIn("\n  push:", self.text)
        self.assertNotIn("\n  schedule:", self.text)

    def test_t21_workflow_has_three_documented_stages_plus_self_verify(self) -> None:
        # Stage 0 (Validate), Stage 1 (Probe), Stage 2 (Self-verify),
        # Stage 3 (Aggregate). The self-verify is a sub-stage of the
        # three-stage docstring contract.
        for marker in (
            "Stage 0 - Validate inputs",
            "Stage 1 - Probe N consecutive E2E-Smoke aggregator runs",
            "Stage 2 - Self-verify aggregator substrate",
            "Stage 3 - Aggregate stability-window verdict",
        ):
            self.assertIn(marker, self.text, f"missing stage marker {marker!r}")

    def test_t22_workflow_invokes_tag63_e2e_smoke_aggregator(self) -> None:
        # The probe must invoke the Tag-63 E2E-Smoke aggregator
        # (otherwise it would not be probing the right substrate).
        self.assertIn(
            "tooling/ci/aggregate_pre_cutover_e2e_smoke_verdict.py",
            self.text,
        )

    def test_t23_workflow_exit_non_zero_only_on_defect(self) -> None:
        # The probe is informational; the only non-zero exit is on
        # STABILITY-WINDOW-DEFECT (mirrors the Tag-63 REUSE-Wrap
        # Stability-Window-Probe semantics).
        self.assertIn('"${VERDICT}" = "STABILITY-WINDOW-DEFECT"', self.text)
        self.assertIn("exit 1", self.text)


class TestCrossSubstrateAnchors(unittest.TestCase):
    """The cross-substrate anchors the Tag-65 probe references all exist."""

    def test_t24_tag63_e2e_smoke_aggregator_exists(self) -> None:
        # The Tag-65 probe walks the Tag-63 E2E-Smoke aggregator;
        # if that anchor is missing, the probe is meaningless.
        self.assertTrue(
            E2E_SMOKE_AGGREGATOR_PATH.exists(),
            f"missing Tag-63 anchor {E2E_SMOKE_AGGREGATOR_PATH}",
        )

    def test_t25_tag63_reuse_wrap_probe_exists_as_pattern_anchor(self) -> None:
        # The pattern-anchor (Tomas Tag-63 PR #404) must exist; the
        # Tag-65 probe inherits its trinary verdict shape and exit-
        # code semantics.
        self.assertTrue(
            REUSE_WRAP_PROBE_PATH.exists(),
            f"missing pattern anchor {REUSE_WRAP_PROBE_PATH}",
        )

    def test_t26_tag64_companion_doc_references_e2e_verdict(self) -> None:
        # The Tag-64 Required-Status-Check-Wiring-Companion (PR #411)
        # references the E2E-verdict job as Pool-Position #8 and is
        # the consumer-side anchor for the stability-window claim.
        self.assertTrue(
            TAG64_COMPANION_DOC_PATH.exists(),
            f"missing companion doc {TAG64_COMPANION_DOC_PATH}",
        )
        text = TAG64_COMPANION_DOC_PATH.read_text(encoding="utf-8")
        # Confirm the doc references the E2E-verdict job's display
        # name (case-mix preserved per the companion-doc §3 falle).
        self.assertIn("E2E verdict", text)


class TestCrossReviewMarkers(unittest.TestCase):
    """The aggregator emits the documented Zone-M / Zone-N markers."""

    def setUp(self) -> None:
        self.m = _load_aggregator()

    def test_t27_zone_m_and_zone_n_markers_present(self) -> None:
        env = {
            "RUN_COUNT": "3",
            "RUN_1_VERDICT": "E2E-READY",
            "RUN_2_VERDICT": "E2E-READY",
            "RUN_3_VERDICT": "E2E-READY",
        }
        envelope = self.m.build_envelope(env)
        markers_text = "\n".join(envelope["cross_review_markers"])
        # Zone-M: walks Tag-63 E2E-Smoke (Amara's own substrate,
        # but cross-component for Engineering helpers underneath).
        self.assertIn("Zone-M", markers_text)
        # Zone-N: Henrik consumes the verdict as audit-evidence-
        # input for the Required-Status-Check promotion claim.
        self.assertIn("Zone-N", markers_text)
        self.assertIn("Henrik", markers_text)
        # Pattern-lineage records the upstream anchors.
        self.assertIn(
            "Tag-63 PR #400 (Amara)",
            envelope["pattern_lineage"]["e2e_smoke_anchor"],
        )
        self.assertIn(
            "Tag-63 PR #404 (Tomas)",
            envelope["pattern_lineage"]["reuse_wrap_anchor"],
        )
        # Cross-substrate-links record the workflow paths.
        self.assertEqual(
            envelope["cross_substrate_links"]["e2e_smoke_aggregator"],
            "tooling/ci/aggregate_pre_cutover_e2e_smoke_verdict.py",
        )
        self.assertEqual(
            envelope["cross_substrate_links"][
                "stability_window_probe_workflow"
            ],
            ".github/workflows/e2e-smoke-stability-window-probe.yml",
        )


if __name__ == "__main__":  # pragma: no cover - CLI dispatch
    unittest.main(verbosity=2)
