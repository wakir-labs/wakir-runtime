# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-61 - Persona-Engine Pre-Cutover-Final-Acceptance-Compositum tests (Selin).

The Tag-61 compositum aggregates four Tag-58/59/60 substrate
verdicts (v907_pin, drift_scanner, version_bump_coverage,
manifest_readiness) into a single PRE-CUTOVER-READY /
PRE-CUTOVER-DRIFT / PRE-CUTOVER-DEFECT verdict. This hermetic
test-suite pins the byte-shape of the aggregator helper at
``tooling/ci/aggregate_persona_engine_pre_cutover_final.py``
and the workflow file at
``.github/workflows/persona-engine-pre-cutover-final-acceptance-composite.yml``.

Hermetic envelope
-----------------
* No network. No NATS, no SPIRE, no gRPC.
* No subprocess (aggregator is imported, not shelled).
* No filesystem writes outside ``tempfile``.
* Deterministic - no clock-sensitive assertions.

Scope discipline (Selin)
------------------------
This file does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K), identity-
substrate design (Reza-Domaene, Zone-L), or container-infra
(Kai-Domaene, Zone-J). It only asserts the aggregator + workflow
byte-shape relations the Tag-61 compositum stakes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


# Repo root: parents[3] from tests/persona_engine/<file>.py.
REPO_ROOT = Path(__file__).resolve().parents[3]
AGGREGATOR_PATH = (
    REPO_ROOT / "tooling" / "ci" / "aggregate_persona_engine_pre_cutover_final.py"
)
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "persona-engine-pre-cutover-final-acceptance-composite.yml"
)


def _load_aggregator():
    """Import the aggregator helper as a fresh module.

    Avoids polluting ``sys.modules`` with a top-level
    ``aggregate_persona_engine_pre_cutover_final`` entry that other
    test modules might inadvertently import. Each test gets its own
    fresh handle.
    """
    spec = importlib.util.spec_from_file_location(
        "tag61_aggregator_under_test", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None, AGGREGATOR_PATH
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Tag61CompositeAggregatorTests(unittest.TestCase):
    """Hermetic byte-shape pins for the Tag-61 aggregator helper."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.agg = _load_aggregator()

    # ---- 01..04 SUBSTRATES tuple shape -----------------------------------

    def test_01_substrates_tuple_has_four_entries(self) -> None:
        """The aggregator pins exactly four sub-gate substrates."""
        self.assertEqual(len(self.agg.SUBSTRATES), 4)

    def test_02_substrates_documented_order(self) -> None:
        """Sub-gate ordering matches the documented G1..G4 mapping."""
        self.assertEqual(
            self.agg.SUBSTRATES,
            (
                "v907_pin",
                "drift_scanner",
                "version_bump_coverage",
                "manifest_readiness",
            ),
        )

    def test_03_env_key_mapping(self) -> None:
        """``_env_key`` maps substrate-key -> ``G<n>_STATUS``."""
        self.assertEqual(self.agg._env_key("v907_pin"), "G1_STATUS")
        self.assertEqual(self.agg._env_key("drift_scanner"), "G2_STATUS")
        self.assertEqual(
            self.agg._env_key("version_bump_coverage"), "G3_STATUS"
        )
        self.assertEqual(
            self.agg._env_key("manifest_readiness"), "G4_STATUS"
        )

    def test_04_note_key_mapping(self) -> None:
        """``_note_key`` maps substrate-key -> ``G<n>_NOTE``."""
        self.assertEqual(self.agg._note_key("v907_pin"), "G1_NOTE")
        self.assertEqual(
            self.agg._note_key("manifest_readiness"), "G4_NOTE"
        )

    # ---- 05..09 _normalise + decide --------------------------------------

    def test_05_normalise_known_statuses(self) -> None:
        """``green``/``yellow``/``red`` pass through (case-insensitive)."""
        for s in ("green", "yellow", "red", "GREEN", "Red", "Yellow"):
            self.assertEqual(self.agg._normalise(s), s.lower())

    def test_06_normalise_none_and_empty_fall_back_to_red(self) -> None:
        """Missing / empty / unknown values collapse to red."""
        self.assertEqual(self.agg._normalise(None), "red")
        self.assertEqual(self.agg._normalise(""), "red")
        self.assertEqual(self.agg._normalise("   "), "red")
        self.assertEqual(self.agg._normalise("not-a-status"), "red")
        self.assertEqual(self.agg._normalise("orange"), "red")

    def test_07_decide_all_green_yields_ready(self) -> None:
        """Verdict = READY iff all four substrates are green."""
        steps = {s: "green" for s in self.agg.SUBSTRATES}
        self.assertEqual(self.agg.decide(steps), "PRE-CUTOVER-READY")

    def test_08_decide_any_yellow_yields_drift(self) -> None:
        """1..N yellow + zero red -> DRIFT (any yellow degrades)."""
        for sub in self.agg.SUBSTRATES:
            steps = {s: "green" for s in self.agg.SUBSTRATES}
            steps[sub] = "yellow"
            self.assertEqual(
                self.agg.decide(steps),
                "PRE-CUTOVER-DRIFT",
                f"yellow on {sub} should yield DRIFT",
            )

    def test_09_decide_any_red_yields_defect(self) -> None:
        """Any red collapses to DEFECT regardless of yellow count."""
        for sub in self.agg.SUBSTRATES:
            steps = {s: "green" for s in self.agg.SUBSTRATES}
            steps[sub] = "red"
            self.assertEqual(
                self.agg.decide(steps),
                "PRE-CUTOVER-DEFECT",
                f"red on {sub} should yield DEFECT",
            )
        # Mixed red+yellow: still DEFECT.
        steps = {
            "v907_pin": "yellow",
            "drift_scanner": "red",
            "version_bump_coverage": "green",
            "manifest_readiness": "yellow",
        }
        self.assertEqual(self.agg.decide(steps), "PRE-CUTOVER-DEFECT")

    # ---- 10..14 build_envelope -------------------------------------------

    def test_10_envelope_schema_version_and_workflow(self) -> None:
        env = {
            "G1_STATUS": "green",
            "G2_STATUS": "green",
            "G3_STATUS": "green",
            "G4_STATUS": "green",
        }
        e = self.agg.build_envelope(env)
        self.assertEqual(e["schema_version"], 1)
        self.assertEqual(
            e["workflow"],
            "persona-engine-pre-cutover-final-acceptance-composite",
        )
        self.assertEqual(e["tag"], "tag-61")
        self.assertEqual(e["engine_version"], "0.5.3")

    def test_11_envelope_all_green_ready_verdict(self) -> None:
        env = {f"G{i}_STATUS": "green" for i in range(1, 5)}
        e = self.agg.build_envelope(env)
        self.assertEqual(e["verdict"], "PRE-CUTOVER-READY")
        self.assertEqual(e["counts"], {"green": 4, "yellow": 0, "red": 0})
        self.assertEqual(e["failed_steps"], [])

    def test_12_envelope_drift_yellow_only(self) -> None:
        env = {
            "G1_STATUS": "green",
            "G2_STATUS": "yellow",
            "G3_STATUS": "green",
            "G4_STATUS": "green",
            "G2_NOTE": "allowlisted historical hits: 5",
        }
        e = self.agg.build_envelope(env)
        self.assertEqual(e["verdict"], "PRE-CUTOVER-DRIFT")
        self.assertEqual(e["counts"]["yellow"], 1)
        self.assertEqual(e["counts"]["red"], 0)
        self.assertIn("drift_scanner", e["failed_steps"])
        self.assertEqual(
            e["per_substrate_notes"]["drift_scanner"],
            "allowlisted historical hits: 5",
        )

    def test_13_envelope_defect_on_any_red(self) -> None:
        env = {
            "G1_STATUS": "red",
            "G2_STATUS": "green",
            "G3_STATUS": "green",
            "G4_STATUS": "green",
            "G1_NOTE": "hash-pin drift: multi-segment-drift",
        }
        e = self.agg.build_envelope(env)
        self.assertEqual(e["verdict"], "PRE-CUTOVER-DEFECT")
        self.assertEqual(e["counts"]["red"], 1)
        self.assertIn("v907_pin", e["failed_steps"])
        self.assertEqual(
            e["per_substrate_notes"]["v907_pin"],
            "hash-pin drift: multi-segment-drift",
        )

    def test_14_envelope_missing_env_defaults_to_red_defect(self) -> None:
        """Empty env -> all substrates red -> DEFECT."""
        e = self.agg.build_envelope({})
        self.assertEqual(e["verdict"], "PRE-CUTOVER-DEFECT")
        self.assertEqual(e["counts"], {"green": 0, "yellow": 0, "red": 4})
        for sub in self.agg.SUBSTRATES:
            self.assertEqual(e["step_results"][sub], "red")

    # ---- 15..17 envelope structural pins ---------------------------------

    def test_15_envelope_cross_substrate_links_complete(self) -> None:
        """Cross-substrate links cover every authority surface."""
        e = self.agg.build_envelope({f"G{i}_STATUS": "green" for i in range(1, 5)})
        links = e["cross_substrate_links"]
        for k in (
            "v907_verifier",
            "v907_baseline",
            "v907_workflow",
            "drift_scanner_script",
            "drift_scanner_allowlist",
            "version_anchor_module",
            "release_notes_doc",
            "manifest_doc",
            "pin_pack_yaml",
            "tag_53_sanity_workflow",
            "auto_scheduler_workflow",
        ):
            self.assertIn(k, links, f"link key '{k}' missing from envelope")

    def test_16_envelope_substrate_lineage_records_pr_refs(self) -> None:
        """Substrate-lineage records the Tag-58/59/60 PR provenance."""
        e = self.agg.build_envelope({f"G{i}_STATUS": "green" for i in range(1, 5)})
        lineage = e["substrate_lineage"]
        self.assertIn("PR #379", lineage["v907_pin"])  # Tag-59
        self.assertIn("PR #384", lineage["drift_scanner"])  # Tag-60
        self.assertIn("PR #372", lineage["version_bump_coverage"])  # Tag-58
        self.assertIn("PR #336", lineage["manifest_readiness"])  # Tag-52
        self.assertIn("PR #372", lineage["manifest_readiness"])  # Tag-58

    def test_17_envelope_decision_rule_records_three_outcomes(self) -> None:
        """Decision-rule field records all three verdict-bands."""
        e = self.agg.build_envelope({f"G{i}_STATUS": "green" for i in range(1, 5)})
        self.assertIn("ready", e["decision_rule"])
        self.assertIn("drift", e["decision_rule"])
        self.assertIn("defect", e["decision_rule"])
        # Make sure the substrates are referenced in the ready clause.
        self.assertIn("v907_pin", e["decision_rule"]["ready"])

    # ---- 18..20 main() round-trip via tempfile ---------------------------

    def test_18_main_writes_envelope_to_output_path(self) -> None:
        """``main()`` writes the envelope to ``--output``."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "verdict.json"
            # Mutate os.environ via patched mapping isn't ideal in stdlib;
            # use the lower-level build_envelope path through main by
            # mutating the real os.environ then restoring.
            saved = {k: os.environ.get(k) for k in (
                "G1_STATUS", "G2_STATUS", "G3_STATUS", "G4_STATUS",
            )}
            try:
                for i, v in enumerate(("green", "green", "yellow", "green"), 1):
                    os.environ[f"G{i}_STATUS"] = v
                rc = self.agg.main(["aggregator", "--output", str(out)])
                self.assertEqual(rc, 0)
                payload = json.loads(out.read_text(encoding="utf-8"))
                self.assertEqual(payload["verdict"], "PRE-CUTOVER-DRIFT")
                self.assertEqual(payload["step_results"]["version_bump_coverage"], "yellow")
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_19_main_creates_output_parent_directory(self) -> None:
        """``main()`` mkdirs the parent if missing."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "deeply" / "nested" / "verdict.json"
            saved = {k: os.environ.get(k) for k in (
                "G1_STATUS", "G2_STATUS", "G3_STATUS", "G4_STATUS",
            )}
            try:
                for i in range(1, 5):
                    os.environ[f"G{i}_STATUS"] = "green"
                rc = self.agg.main(["aggregator", "--output", str(out)])
                self.assertEqual(rc, 0)
                self.assertTrue(out.is_file())
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_20_main_print_stdout_flag(self) -> None:
        """``--print-stdout`` echoes the envelope on stdout."""
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "verdict.json"
            saved = {k: os.environ.get(k) for k in (
                "G1_STATUS", "G2_STATUS", "G3_STATUS", "G4_STATUS",
            )}
            try:
                for i in range(1, 5):
                    os.environ[f"G{i}_STATUS"] = "green"
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = self.agg.main([
                        "aggregator", "--output", str(out), "--print-stdout",
                    ])
                self.assertEqual(rc, 0)
                # Confirm the printed payload parses as JSON and carries
                # the expected verdict.
                printed = json.loads(buf.getvalue())
                self.assertEqual(printed["verdict"], "PRE-CUTOVER-READY")
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v


class Tag61CompositeWorkflowFileTests(unittest.TestCase):
    """Plain-text byte-shape pins for the composite workflow YAML.

    Avoids parsing YAML (no pyyaml in stdlib); asserts substring +
    line-presence relations the workflow contract stakes.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_21_workflow_name_matches_filename(self) -> None:
        self.assertIn(
            "name: persona-engine-pre-cutover-final-acceptance-composite",
            self.text,
        )

    def test_22_workflow_pulls_in_all_four_gate_jobs(self) -> None:
        """G1..G4 job-ids present in the workflow."""
        for job in (
            "g1-v907-pin:",
            "g2-drift-scanner:",
            "g3-version-bump-coverage:",
            "g4-manifest-readiness:",
            "g5-compositum:",
        ):
            self.assertIn(job, self.text, f"job '{job}' missing")

    def test_23_workflow_g5_depends_on_g1_through_g4(self) -> None:
        """The compositum job lists all four sub-gates in ``needs:``."""
        for need in (
            "- g1-v907-pin",
            "- g2-drift-scanner",
            "- g3-version-bump-coverage",
            "- g4-manifest-readiness",
        ):
            self.assertIn(need, self.text, f"needs '{need}' missing")

    def test_24_workflow_invokes_aggregator_helper(self) -> None:
        """The compositum step shells out to the aggregator helper."""
        self.assertIn(
            "tooling/ci/aggregate_persona_engine_pre_cutover_final.py",
            self.text,
        )

    def test_25_workflow_runs_hermetic_tag61_test_suite(self) -> None:
        """The compositum job runs this very test-suite before aggregating."""
        self.assertIn(
            "wirelang.tests.persona_engine.test_engine_pre_cutover_final_composite_tag61",
            self.text,
        )

    def test_26_workflow_uploads_verdict_artifact(self) -> None:
        """Verdict envelope is uploaded as a build artifact."""
        self.assertIn(
            "name: persona-engine-pre-cutover-final-composite-verdict",
            self.text,
        )
        self.assertIn(
            "path: out/persona-engine-pre-cutover-final-composite-verdict.json",
            self.text,
        )

    def test_27_workflow_path_filters_cover_engine_substrate(self) -> None:
        """Pull-request path-filters cover all engine-substrate axes."""
        for path in (
            "'wirelang/persona_engine/**'",
            "'docs/persona-engine/**'",
            "'infra/persona-engine/pin-pack-*.yaml'",
            "'tooling/ci/verify_v907_persona_hash_pin.py'",
            "'tooling/ci/scan_engine_version_drift.py'",
            "'tooling/ci/engine-version-drift-allowlist.json'",
            "'tooling/ci/aggregate_persona_engine_pre_cutover_final.py'",
            "'wirelang/tests/persona_engine/**'",
        ):
            self.assertIn(
                path, self.text, f"path-filter '{path}' missing"
            )

    def test_28_workflow_enforce_input_default_true(self) -> None:
        """``workflow_dispatch`` exposes ``enforce`` with default true."""
        self.assertIn("inputs:", self.text)
        self.assertIn("enforce:", self.text)
        # The default literal must be present near the enforce input.
        idx = self.text.find("enforce:")
        slice_ = self.text[idx:idx + 400]
        self.assertIn("default: 'true'", slice_)

    def test_29_workflow_concurrency_group_present(self) -> None:
        """Concurrency group is set so multi-trigger races don't pile up."""
        self.assertIn("concurrency:", self.text)
        self.assertIn(
            "persona-engine-pre-cutover-final-acceptance-composite",
            self.text,
        )
        # cancel-in-progress must be explicitly false so an in-flight
        # verdict is not aborted by a follow-up push.
        self.assertIn("cancel-in-progress: false", self.text)

    # REUSE-IgnoreStart
    def test_30_workflow_carries_apache_spdx_header(self) -> None:
        """The workflow file carries an Apache-2.0 SPDX header line."""
        first_line = self.text.splitlines()[0]
        self.assertTrue(
            first_line.startswith("# SPDX-License-Identifier: Apache-2.0"),
            f"first line was: {first_line!r}",
        )
    # REUSE-IgnoreEnd


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
