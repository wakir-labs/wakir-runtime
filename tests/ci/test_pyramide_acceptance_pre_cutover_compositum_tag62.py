# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic CI-substrate tests for the Tag-62 Pyramide-Acceptance
Pre-Cutover-Compositum (Amara, Continuous-Mode-Marathon).

Auftrag-Anker
-------------

Tag-62 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
aggregate the four Tag-57/58/60/61 QA-substrate verdicts the
6-Layer Acceptance-Pyramide has accumulated into a single
``ACCEPTANCE-PYRAMIDE-READY`` / ``ACCEPTANCE-PYRAMIDE-DRIFT`` /
``ACCEPTANCE-PYRAMIDE-DEFECT`` verdict that the KW-24 cutover-day
auto-scheduler reads alongside Selin's Tag-61 persona-engine
compositum and the Tag-53 final-sanity-gate.

Scope (aggregator + workflow + cross-substrate-links)
-----------------------------------------------------

This module verifies three surfaces:

* The Tag-62 aggregator helper
  (``tooling/ci/aggregate_pyramide_acceptance_pre_cutover.py``):
  - ``SUBSTRATES`` ordering matches the documented G1..G4 order
  - ``_normalise()`` coerces unknown / empty / mixed-case to red
  - ``decide()`` applies the strict rule: any yellow degrades,
    any red collapses, all-green is READY
  - ``build_envelope()`` produces a verdict-envelope with the
    canonical keys (verdict, step_results, failed_steps, counts,
    decision_rule, substrate_lineage, cross_substrate_links,
    cross_review_markers, schema_version, workflow, tag, ...)
  - ``main()`` writes the envelope to ``--output`` and exits 0
  - The CLI surface mirrors Selin's Tag-61 helper for downstream
    parser-compatibility

* The Tag-62 workflow YAML
  (``.github/workflows/pyramide-acceptance-pre-cutover-compositum.yml``):
  - Has five jobs (g1..g4 substrate-probes + g5 compositum)
  - g5 needs all four g1..g4 jobs AND has ``if: always()``
  - Path-filter includes all four substrate sources + helper +
    test-suite + workflow self
  - Has workflow_dispatch with enforce input + pull_request trigger
  - Concurrency-group set + permissions: contents:read + actions:read

* The Tag-62 cross-substrate links:
  - All linked paths exist on HEAD (run-order doc + aggregator,
    layer-DAG helper + workflow, cross-run helper + workflow,
    allowlist file + suite, pyramide map, Selin engine compositum)

Hermetic-tests
--------------

Auftrag minimum: >= 15 hermetic tests. This module ships 27.
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


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HELPER_PATH = (
    REPO_ROOT / "tooling" / "ci" / "aggregate_pyramide_acceptance_pre_cutover.py"
)
PROBE_HELPER_PATH = (
    REPO_ROOT / "tooling" / "ci" / "probe_pyramide_compositum_substrates.py"
)
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "pyramide-acceptance-pre-cutover-compositum.yml"
)
SUITE_PATH = (
    REPO_ROOT
    / "tests"
    / "ci"
    / "test_pyramide_acceptance_pre_cutover_compositum_tag62.py"
)


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "aggregate_pyramide_acceptance_pre_cutover_helper",
        HELPER_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load helper from {HELPER_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HelperSurfaceTests(unittest.TestCase):
    """Surface-level invariants of the aggregator helper."""

    def test_01_helper_file_exists(self):
        self.assertTrue(
            HELPER_PATH.exists(),
            f"Tag-62 aggregator helper missing at {HELPER_PATH}",
        )

    def test_02_helper_is_importable_and_exposes_api(self):
        mod = _load_helper()
        for name in (
            "SUBSTRATES",
            "VALID_STATUSES",
            "VERDICT_READY",
            "VERDICT_DRIFT",
            "VERDICT_DEFECT",
            "SUBSTRATE_LINEAGE",
            "CROSS_SUBSTRATE_LINKS",
            "_normalise",
            "decide",
            "_env_key",
            "_note_key",
            "_parse_substrate_notes",
            "build_envelope",
            "main",
        ):
            self.assertTrue(
                hasattr(mod, name),
                f"helper missing public symbol {name!r}",
            )

    def test_03_substrate_order_matches_g1_g4_documented_order(self):
        mod = _load_helper()
        self.assertEqual(
            mod.SUBSTRATES,
            (
                "run_order_doc",
                "layer_dag",
                "cross_run_stability",
                "drift_allowlist",
            ),
            "SUBSTRATES ordering must mirror G1..G4 in workflow YAML",
        )

    def test_04_env_key_and_note_key_are_one_indexed(self):
        mod = _load_helper()
        self.assertEqual(mod._env_key("run_order_doc"), "G1_STATUS")
        self.assertEqual(mod._env_key("layer_dag"), "G2_STATUS")
        self.assertEqual(mod._env_key("cross_run_stability"), "G3_STATUS")
        self.assertEqual(mod._env_key("drift_allowlist"), "G4_STATUS")
        self.assertEqual(mod._note_key("run_order_doc"), "G1_NOTE")
        self.assertEqual(mod._note_key("drift_allowlist"), "G4_NOTE")


class NormaliseTests(unittest.TestCase):
    """``_normalise`` is the trust-boundary; defensive coverage."""

    def test_05_normalise_valid_lowercase_passthrough(self):
        mod = _load_helper()
        self.assertEqual(mod._normalise("green"), "green")
        self.assertEqual(mod._normalise("yellow"), "yellow")
        self.assertEqual(mod._normalise("red"), "red")

    def test_06_normalise_mixed_case_and_whitespace(self):
        mod = _load_helper()
        self.assertEqual(mod._normalise("  GREEN "), "green")
        self.assertEqual(mod._normalise("Yellow"), "yellow")
        self.assertEqual(mod._normalise("RED"), "red")

    def test_07_normalise_none_empty_and_unknown_collapse_to_red(self):
        mod = _load_helper()
        self.assertEqual(mod._normalise(None), "red")
        self.assertEqual(mod._normalise(""), "red")
        self.assertEqual(mod._normalise("   "), "red")
        self.assertEqual(mod._normalise("orange"), "red")
        self.assertEqual(mod._normalise("PASS"), "red")
        self.assertEqual(mod._normalise("FAIL"), "red")


class DecisionRuleTests(unittest.TestCase):
    """The decision rule is the only logic that matters for cutover."""

    def test_08_decide_all_green_is_ready(self):
        mod = _load_helper()
        steps = {s: "green" for s in mod.SUBSTRATES}
        self.assertEqual(mod.decide(steps), mod.VERDICT_READY)
        self.assertEqual(mod.VERDICT_READY, "ACCEPTANCE-PYRAMIDE-READY")

    def test_09_decide_any_yellow_zero_red_is_drift(self):
        mod = _load_helper()
        for s in mod.SUBSTRATES:
            steps = {x: "green" for x in mod.SUBSTRATES}
            steps[s] = "yellow"
            self.assertEqual(
                mod.decide(steps),
                mod.VERDICT_DRIFT,
                f"yellow on {s} alone must yield DRIFT",
            )

    def test_10_decide_any_red_is_defect_even_with_yellows(self):
        mod = _load_helper()
        for s in mod.SUBSTRATES:
            steps = {x: "yellow" for x in mod.SUBSTRATES}
            steps[s] = "red"
            self.assertEqual(
                mod.decide(steps),
                mod.VERDICT_DEFECT,
                f"red on {s} must yield DEFECT regardless of yellows",
            )

    def test_11_decide_two_yellows_one_red_is_defect(self):
        mod = _load_helper()
        steps = {
            "run_order_doc": "red",
            "layer_dag": "yellow",
            "cross_run_stability": "yellow",
            "drift_allowlist": "green",
        }
        self.assertEqual(mod.decide(steps), mod.VERDICT_DEFECT)

    def test_12_decide_all_yellow_is_drift_not_defect(self):
        mod = _load_helper()
        steps = {s: "yellow" for s in mod.SUBSTRATES}
        self.assertEqual(mod.decide(steps), mod.VERDICT_DRIFT)


class EnvelopeShapeTests(unittest.TestCase):
    """The envelope is the artifact the auto-scheduler consumes."""

    def test_13_envelope_has_canonical_top_level_keys(self):
        mod = _load_helper()
        envelope = mod.build_envelope({})
        for key in (
            "schema_version",
            "workflow",
            "tag",
            "emitted_at_utc",
            "verdict",
            "step_results",
            "failed_steps",
            "per_substrate_notes",
            "substrate_notes",
            "counts",
            "decision_rule",
            "substrate_lineage",
            "cross_substrate_links",
            "cross_review_markers",
        ):
            self.assertIn(key, envelope, f"envelope missing key {key!r}")

    def test_14_envelope_empty_env_all_red_is_defect(self):
        mod = _load_helper()
        envelope = mod.build_envelope({})
        self.assertEqual(envelope["verdict"], mod.VERDICT_DEFECT)
        self.assertEqual(envelope["counts"], {"green": 0, "yellow": 0, "red": 4})
        self.assertEqual(
            sorted(envelope["failed_steps"]), sorted(mod.SUBSTRATES)
        )

    def test_15_envelope_full_green_env_yields_ready(self):
        mod = _load_helper()
        env = {
            "G1_STATUS": "green",
            "G2_STATUS": "green",
            "G3_STATUS": "green",
            "G4_STATUS": "green",
        }
        envelope = mod.build_envelope(env)
        self.assertEqual(envelope["verdict"], mod.VERDICT_READY)
        self.assertEqual(envelope["counts"], {"green": 4, "yellow": 0, "red": 0})
        self.assertEqual(envelope["failed_steps"], [])

    def test_16_envelope_passes_per_substrate_notes(self):
        mod = _load_helper()
        env = {
            "G1_STATUS": "green",
            "G2_STATUS": "yellow",
            "G3_STATUS": "green",
            "G4_STATUS": "yellow",
            "G2_NOTE": "allowlist swallowed extras",
            "G4_NOTE": "3 entries with follow-up",
            "SUBSTRATE_NOTES": (
                "layer_dag:allowlist swallowed extras;"
                "drift_allowlist:3 entries with follow-up"
            ),
        }
        envelope = mod.build_envelope(env)
        self.assertEqual(envelope["verdict"], mod.VERDICT_DRIFT)
        self.assertEqual(
            envelope["per_substrate_notes"].get("layer_dag"),
            "allowlist swallowed extras",
        )
        self.assertEqual(
            envelope["per_substrate_notes"].get("drift_allowlist"),
            "3 entries with follow-up",
        )
        self.assertEqual(len(envelope["substrate_notes"]), 2)

    def test_17_envelope_workflow_and_tag_anchors(self):
        mod = _load_helper()
        envelope = mod.build_envelope({})
        self.assertEqual(
            envelope["workflow"],
            "pyramide-acceptance-pre-cutover-compositum",
        )
        self.assertEqual(envelope["tag"], "tag-62")
        self.assertEqual(envelope["schema_version"], 1)


class SubstrateLineageAndLinksTests(unittest.TestCase):
    """Cross-substrate links are audit-evidence-input for Henrik (Zone-N)."""

    def test_18_substrate_lineage_covers_all_four_substrates(self):
        mod = _load_helper()
        for substrate in mod.SUBSTRATES:
            self.assertIn(
                substrate,
                mod.SUBSTRATE_LINEAGE,
                f"SUBSTRATE_LINEAGE missing {substrate!r}",
            )
            self.assertTrue(
                mod.SUBSTRATE_LINEAGE[substrate].startswith("Tag-"),
                f"lineage for {substrate} must start with Tag-",
            )

    def test_19_cross_substrate_links_all_resolve_on_head(self):
        mod = _load_helper()
        # Every CROSS_SUBSTRATE_LINKS value must resolve to an
        # existing path on HEAD (modulo the auto-scheduler workflow
        # which may not yet exist on a fresh branch; we tolerate that
        # one path being absent, but every other must exist).
        tolerated_missing = {"auto_scheduler_workflow"}
        for key, rel in mod.CROSS_SUBSTRATE_LINKS.items():
            abs_path = REPO_ROOT / rel
            if key in tolerated_missing and not abs_path.exists():
                continue
            self.assertTrue(
                abs_path.exists(),
                f"cross-substrate link {key!r} resolves to missing "
                f"path: {rel}",
            )


class CLITests(unittest.TestCase):
    """End-to-end via subprocess: workflow uses ``python3 helper.py``."""

    def test_20_cli_writes_envelope_to_output_path(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "verdict.json"
            env = os.environ.copy()
            env.update(
                {
                    "G1_STATUS": "green",
                    "G2_STATUS": "green",
                    "G3_STATUS": "green",
                    "G4_STATUS": "green",
                    "SUBSTRATE_NOTES": "",
                }
            )
            result = subprocess.run(
                [sys.executable, str(HELPER_PATH), "--output", str(out)],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f"helper failed: {result.stderr}",
            )
            self.assertTrue(out.exists(), "verdict file not created")
            data = json.loads(out.read_text(encoding="utf-8"))
            mod = _load_helper()
            self.assertEqual(data["verdict"], mod.VERDICT_READY)

    def test_21_cli_print_stdout_flag_echoes_envelope(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "verdict.json"
            env = os.environ.copy()
            env.update({"G1_STATUS": "red"})
            result = subprocess.run(
                [
                    sys.executable,
                    str(HELPER_PATH),
                    "--output",
                    str(out),
                    "--print-stdout",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("ACCEPTANCE-PYRAMIDE-DEFECT", result.stdout)


class ProbeHelperTests(unittest.TestCase):
    """The probe helper is the shell-side adapter for G2 + G4."""

    def test_22_probe_helper_layer_dag_extracts_verdict(self):
        self.assertTrue(PROBE_HELPER_PATH.exists())
        payload = json.dumps({"verdict": "DAG-CONSISTENT", "extras": []})
        result = subprocess.run(
            [
                sys.executable,
                str(PROBE_HELPER_PATH),
                "--mode",
                "layer-dag-verdict",
            ],
            input=payload,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "DAG-CONSISTENT")

    def test_23_probe_helper_layer_dag_parse_error_on_garbage(self):
        result = subprocess.run(
            [
                sys.executable,
                str(PROBE_HELPER_PATH),
                "--mode",
                "layer-dag-verdict",
            ],
            input="not-json-at-all",
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "PARSE-ERROR")

    def test_24_probe_helper_drift_allowlist_ok_zero(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "al.json"
            p.write_text(
                json.dumps({"_schema": {"version": 1}, "entries": []}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROBE_HELPER_PATH),
                    "--mode",
                    "drift-allowlist",
                    "--path",
                    str(p),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "OK:0")

    def test_25_probe_helper_drift_allowlist_ok_nonzero_and_followup_missing(self):
        with tempfile.TemporaryDirectory() as td:
            # Two entries with follow-up - OK:2.
            p = Path(td) / "al.json"
            p.write_text(
                json.dumps(
                    {
                        "_schema": {"version": 1},
                        "entries": [
                            {
                                "from_layer": 1,
                                "to_layer": 2,
                                "reason": "legitimate cross-cite",
                                "follow_up": "ADR-0099",
                            },
                            {
                                "from_layer": 3,
                                "to_layer": 4,
                                "reason": "docstring soft-cite",
                                "follow_up": "issue #777",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROBE_HELPER_PATH),
                    "--mode",
                    "drift-allowlist",
                    "--path",
                    str(p),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.stdout.strip(), "OK:2")

            # One entry missing follow_up - NO-FOLLOWUP:0.
            p2 = Path(td) / "al2.json"
            p2.write_text(
                json.dumps(
                    {
                        "_schema": {"version": 1},
                        "entries": [
                            {
                                "from_layer": 1,
                                "to_layer": 2,
                                "reason": "legitimate cross-cite",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROBE_HELPER_PATH),
                    "--mode",
                    "drift-allowlist",
                    "--path",
                    str(p2),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertTrue(
                result.stdout.strip().startswith("NO-FOLLOWUP:"),
                f"expected NO-FOLLOWUP prefix, got {result.stdout!r}",
            )

    def test_26_probe_helper_drift_allowlist_schema_violations(self):
        with tempfile.TemporaryDirectory() as td:
            # Missing keys.
            p = Path(td) / "al.json"
            p.write_text(json.dumps({"_schema": {}}), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROBE_HELPER_PATH),
                    "--mode",
                    "drift-allowlist",
                    "--path",
                    str(p),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.stdout.strip(), "SCHEMA:missing-keys")

            # Malformed JSON.
            p2 = Path(td) / "al2.json"
            p2.write_text("{not-json", encoding="utf-8")
            result2 = subprocess.run(
                [
                    sys.executable,
                    str(PROBE_HELPER_PATH),
                    "--mode",
                    "drift-allowlist",
                    "--path",
                    str(p2),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertTrue(
                result2.stdout.strip().startswith("MALFORMED:"),
                f"expected MALFORMED prefix, got {result2.stdout!r}",
            )


class WorkflowYAMLTests(unittest.TestCase):
    """Workflow YAML wire-up checks (regex/substring, no PyYAML dep)."""

    def test_27_workflow_yaml_has_five_jobs_and_compositum_wires(self):
        self.assertTrue(WORKFLOW_PATH.exists())
        body = WORKFLOW_PATH.read_text(encoding="utf-8")
        # Five jobs.
        for job in (
            "g1-run-order-doc:",
            "g2-layer-dag:",
            "g3-cross-run-stability:",
            "g4-drift-allowlist:",
            "g5-compositum:",
        ):
            self.assertIn(job, body, f"workflow missing job {job}")
        # g5 needs all four upstream jobs.
        for need in (
            "g1-run-order-doc",
            "g2-layer-dag",
            "g3-cross-run-stability",
            "g4-drift-allowlist",
        ):
            self.assertIn(
                f"- {need}",
                body,
                f"compositum job missing dependency {need}",
            )
        # if: always() so g5 runs even on upstream failure.
        self.assertIn("if: always()", body)
        # Path-filter covers the four substrate sources + helper +
        # test-suite + workflow self.
        for path in (
            "docs/quality-gates/pre-cutover-acceptance-run-order.md",
            "tooling/ci/aggregate_pyramide_run_order_verdict.py",
            "tooling/ci/verify_layer_dependency_dag.py",
            "tooling/ci/verify_pyramide_cross_run_stability.py",
            "tooling/ci/layer-dag-drift-allowlist.json",
            "tooling/ci/aggregate_pyramide_acceptance_pre_cutover.py",
            "tooling/ci/probe_pyramide_compositum_substrates.py",
            "tests/ci/test_pyramide_acceptance_pre_cutover_compositum_tag62.py",
            ".github/workflows/pyramide-acceptance-pre-cutover-compositum.yml",
        ):
            self.assertIn(
                path, body,
                f"workflow path-filter missing {path}",
            )
        # workflow_dispatch + pull_request triggers.
        self.assertIn("workflow_dispatch:", body)
        self.assertIn("pull_request:", body)
        # Enforce input.
        self.assertIn("enforce:", body)
        # Concurrency + permissions.
        self.assertIn("concurrency:", body)
        self.assertIn("contents: read", body)
        self.assertIn("actions: read", body)
        # Aggregator invocation + artifact upload.
        self.assertIn(
            "tooling/ci/aggregate_pyramide_acceptance_pre_cutover.py", body,
        )
        self.assertIn("upload-artifact@v4", body)
        self.assertIn(
            "pyramide-acceptance-pre-cutover-compositum-verdict.json", body,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
