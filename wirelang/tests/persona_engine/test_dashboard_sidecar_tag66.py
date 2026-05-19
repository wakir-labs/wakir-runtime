# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-66 - Dashboard-Sidecar wire-in tests (Selin).

The Tag-66 Cutover-Day-Morgen Auto-Scheduler Dashboard-Sidecar
adds a Stage 5 step to ``.github/workflows/cutover-day-morgen-
auto-scheduler.yml`` that, after the Stage 4 aggregator emits the
verdict-envelope, calls Noa-Tag-65's
``tooling/ci/render_cutover_day_morgen_tile.py`` helper to render
the marathon-dashboard-kachel Prometheus textfile-collector block.

This hermetic test-suite pins:

* the existence + ordering of the new Stage 5 step,
* the helper-call-shape (CLI flags, envelope-input path,
  textfile-output path),
* the envelope-consumption-pattern (Stage 4 envelope feeds
  Stage 5 sidecar with no separate artifact-fetch),
* the upload-artifact step for the rendered tile,
* the path-trigger surface includes the helper + this test file,
* the workflow's docstring + step-summary references the
  Tag-66 sidecar so operator-hand morning-read picks it up.

Hermetic envelope
-----------------
* No network. No NATS, no SPIRE, no gRPC, no Prometheus.
* No subprocess - the helper is imported, not shelled.
* No filesystem writes outside ``tempfile``.
* Deterministic - all assertions are byte-shape pins.

Scope discipline (Selin)
------------------------
This file does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K), identity-
substrate design (Reza-Domaene, Zone-L), or container-infra
(Kai-Domaene, Zone-J). It only asserts the workflow + helper
byte-shape relations the Tag-66 sidecar stakes.

Cross-persona coord
-------------------
The renderer-helper (Noa-Tag-65 PR #414) is consumed read-only;
this test-suite does not duplicate Noa's helper-internal tests,
it only pins the CLI-flag contract Selin's workflow depends on.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "cutover-day-morgen-auto-scheduler.yml"
)
HELPER_PATH = (
    REPO_ROOT / "tooling" / "ci" / "render_cutover_day_morgen_tile.py"
)
AGGREGATOR_PATH = (
    REPO_ROOT / "tooling" / "ci" / "aggregate_cutover_day_morgen_verdict.py"
)


def _load_helper():
    """Import the Tag-65 tile-renderer helper as a fresh module."""
    spec = importlib.util.spec_from_file_location(
        "tag65_tile_renderer_under_test", HELPER_PATH
    )
    assert spec is not None and spec.loader is not None, HELPER_PATH
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Tag66SidecarWorkflowShapeTests(unittest.TestCase):
    """Workflow byte-shape pins for the Tag-66 Stage-5 sidecar."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    # ---- 01 Workflow file exists ----------------------------------------

    def test_01_workflow_exists(self) -> None:
        self.assertTrue(WORKFLOW_PATH.exists(), WORKFLOW_PATH)
        self.assertTrue(WORKFLOW_PATH.is_file())

    # ---- 02 Stage 5 step-name appears -----------------------------------

    def test_02_stage_5_step_name_present(self) -> None:
        """Stage 5 step-name must be present for operator-hand readability."""
        self.assertIn(
            "Stage 5 -- Render Dashboard Tile + Emit Prometheus Textfile",
            self.text,
        )

    # ---- 03 Stage 5 invokes Noa's helper --------------------------------

    def test_03_stage_5_invokes_noa_helper(self) -> None:
        """Stage 5 must shell out to render_cutover_day_morgen_tile.py."""
        self.assertIn(
            "tooling/ci/render_cutover_day_morgen_tile.py", self.text
        )

    # ---- 04 Stage 5 passes --envelope (Stage 4 output) ------------------

    def test_04_stage_5_passes_envelope_flag(self) -> None:
        """Helper-call must use --envelope flag pointing at Stage 4 output."""
        self.assertIn("--envelope", self.text)
        self.assertIn(
            "out/cutover-day-morgen-verdict.json", self.text
        )

    # ---- 05 Stage 5 writes --output to tile.prom ------------------------

    def test_05_stage_5_writes_tile_prom_output(self) -> None:
        """Helper-call must use --output flag to write tile.prom."""
        self.assertIn("--output", self.text)
        self.assertIn(
            "out/cutover-day-morgen-tile.prom", self.text
        )

    # ---- 06 Stage 5 ordered AFTER Stage 4 --------------------------------

    def test_06_stage_5_ordered_after_stage_4(self) -> None:
        """Stage 5 must appear textually after Stage 4 aggregate step."""
        stage4_pos = self.text.find("Stage 4 -- Aggregate Cutover-Day-Morgen")
        stage5_pos = self.text.find(
            "Stage 5 -- Render Dashboard Tile + Emit Prometheus Textfile"
        )
        self.assertGreater(stage4_pos, 0, "Stage 4 step-name missing")
        self.assertGreater(stage5_pos, 0, "Stage 5 step-name missing")
        self.assertGreater(
            stage5_pos,
            stage4_pos,
            "Stage 5 must be ordered AFTER Stage 4 in the workflow",
        )

    # ---- 07 Sidecar consumes Stage-4 envelope (no fetch) ----------------

    def test_07_sidecar_consumes_stage_4_envelope_no_fetch(self) -> None:
        """
        Stage 5 must consume Stage 4's local artifact file, not
        gh-download a separate artifact. Pin: the renderer-call sits
        in the same job + reads out/cutover-day-morgen-verdict.json.
        """
        # Find the Stage-5 step block (anchor on the step-name to
        # skip the path-trigger entry that also references the
        # helper filename).
        stage5_anchor = self.text.find(
            "Stage 5 -- Render Dashboard Tile + Emit Prometheus Textfile"
        )
        self.assertGreater(stage5_anchor, 0)
        # Inspect the Stage-5 block (next ~1400 chars) for the
        # renderer-invocation + envelope-path + no fresh fetch.
        window = self.text[stage5_anchor : stage5_anchor + 1400]
        self.assertIn(
            "tooling/ci/render_cutover_day_morgen_tile.py", window
        )
        self.assertIn("out/cutover-day-morgen-verdict.json", window)
        self.assertNotIn("gh run download", window)

    # ---- 08 Upload-artifact for the rendered tile -----------------------

    def test_08_uploads_tile_artifact(self) -> None:
        """Rendered tile must be uploaded as a downstream artifact."""
        self.assertIn("name: cutover-day-morgen-tile", self.text)
        # The upload-artifact action is reused.
        self.assertIn("actions/upload-artifact@v4", self.text)
        # Path must match the renderer --output.
        self.assertIn(
            "path: out/cutover-day-morgen-tile.prom", self.text
        )

    # ---- 09 Path-trigger covers helper + new test file ------------------

    def test_09_path_trigger_covers_helper_and_test(self) -> None:
        """push.paths must include the Tag-65 helper and this test file."""
        self.assertIn(
            '- "tooling/ci/render_cutover_day_morgen_tile.py"', self.text
        )
        self.assertIn(
            '- "wirelang/tests/persona_engine/test_dashboard_sidecar_tag66.py"',
            self.text,
        )

    # ---- 10 Step-summary mentions Tag-66 dashboard tile -----------------

    def test_10_step_summary_mentions_tag_66_tile(self) -> None:
        """GITHUB_STEP_SUMMARY must surface the rendered tile."""
        self.assertIn(
            "Dashboard tile (Prometheus textfile, Tag-66)", self.text
        )

    # ---- 11 Workflow docstring references Tag-66 sidecar ----------------

    def test_11_workflow_docstring_references_tag_66(self) -> None:
        """Header docstring must announce the Tag-66 sidecar so the
        operator-hand morning-read picks it up next to Tag-64."""
        self.assertIn("Tag-66 sidecar", self.text)

    # ---- 12 Stage 0..4 ordering preserved (Tag-64 invariants) -----------

    def test_12_existing_stages_preserved(self) -> None:
        """
        Pin: Tag-64 Stages 1..4 must remain in canonical order so
        Tag-66 wire-in does not re-shape the upstream aggregator
        contract.
        """
        s1 = self.text.find("Stage 1 -- Fetch Engine-Composite verdict")
        s2 = self.text.find("Stage 2 -- Fetch Pyramide-Composite verdict")
        s3 = self.text.find("Stage 3 -- Fetch E2E-Smoke verdict")
        s4 = self.text.find("Stage 4 -- Aggregate Cutover-Day-Morgen verdict")
        for pos, name in ((s1, "S1"), (s2, "S2"), (s3, "S3"), (s4, "S4")):
            self.assertGreater(pos, 0, f"{name} step-name missing")
        self.assertLess(s1, s2)
        self.assertLess(s2, s3)
        self.assertLess(s3, s4)

    # ---- 13 Stage 5 audit-only (no notify / fan-out) --------------------

    def test_13_stage_5_audit_only_no_notify(self) -> None:
        """
        Per ``feedback_sandbox_host_trennung.md`` /
        ``feedback_continuous_mode_keine_push_frage.md`` the Stage 5
        sidecar is audit-only -- no notify-cascade, no
        ``gh workflow run`` fan-out.
        """
        idx = self.text.find(
            "Stage 5 -- Render Dashboard Tile + Emit Prometheus Textfile"
        )
        self.assertGreater(idx, 0)
        # Constrain inspection to the Stage 5 block (~1400 chars).
        block = self.text[idx : idx + 1400]
        self.assertNotIn("gh workflow run", block)
        self.assertNotIn("ntfy", block)
        self.assertNotIn("curl ", block)


class Tag66SidecarHelperContractTests(unittest.TestCase):
    """
    Cross-persona-coord pins on Noa-Tag-65 helper CLI shape the
    Tag-66 workflow depends on. Read-only - we do NOT duplicate
    Noa's helper-internal tests.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.helper = _load_helper()

    # ---- 14 Helper CLI module loadable ----------------------------------

    def test_14_helper_module_loadable(self) -> None:
        self.assertTrue(HELPER_PATH.exists(), HELPER_PATH)
        self.assertTrue(hasattr(self.helper, "main"))
        self.assertTrue(callable(self.helper.main))

    # ---- 15 Helper CLI flag-contract --envelope + --output --------------

    def test_15_helper_cli_flags_present(self) -> None:
        """
        The workflow shells out with ``--envelope`` and ``--output``.
        Pin both flags exist via the helper's arg-parser surface so
        a rename breaks unit-tests before it breaks the workflow.
        """
        parser = self.helper._build_arg_parser()
        # Collect flag-names from the parser actions.
        flags = []
        for action in parser._actions:  # noqa: SLF001
            flags.extend(action.option_strings)
        self.assertIn("--envelope", flags)
        self.assertIn("--output", flags)
        self.assertIn("--today", flags)

    # ---- 16 Helper consumes Tag-64 envelope verdict field ---------------

    def test_16_helper_consumes_tag_64_verdict_envelope(self) -> None:
        """
        End-to-end: build a Tag-64-shaped envelope, render the tile,
        assert the four series-blocks the dashboard panels read.
        """
        envelope = {
            "schema_version": 1,
            "workflow": "cutover-day-morgen-auto-scheduler",
            "tag": "tag-64",
            "emitted_at_utc": "2026-06-08T06:05:00+00:00",
            "verdict": "CUTOVER-DAY-MORGEN-READY",
            "step_results": {
                "engine_composite": "green",
                "pyramide_composite": "green",
                "e2e_smoke": "green",
            },
            "window": {"iso_week": 24},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            env_path = base / "verdict.json"
            out_path = base / "out" / "tile.prom"
            env_path.write_text(json.dumps(envelope), encoding="utf-8")
            rc = self.helper.main(
                [
                    "--envelope",
                    str(env_path),
                    "--today",
                    "2026-06-08",
                    "--output",
                    str(out_path),
                ]
            )
            self.assertEqual(rc, 0)
            block = out_path.read_text(encoding="utf-8")
            # Pin all four series-names the Tag-66 dashboard panels read.
            self.assertIn("wakir_cutover_day_morgen_verdict_class", block)
            self.assertIn(
                "wakir_cutover_day_morgen_verdict_emitted_at_seconds", block
            )
            self.assertIn(
                "wakir_cutover_day_morgen_window_days_remaining", block
            )
            self.assertIn(
                'wakir_cutover_day_morgen_substrate_class{substrate="engine_composite"}',
                block,
            )

    # ---- 17 Helper renders READY envelope as class 0 --------------------

    def test_17_helper_ready_class_zero(self) -> None:
        envelope = {
            "verdict": "CUTOVER-DAY-MORGEN-READY",
            "emitted_at_utc": "2026-06-08T06:05:00+00:00",
            "step_results": {
                "engine_composite": "green",
                "pyramide_composite": "green",
                "e2e_smoke": "green",
            },
            "window": {"iso_week": 24},
        }
        block = self.helper.render(envelope, today=date(2026, 6, 8))
        self.assertIn(
            "wakir_cutover_day_morgen_verdict_class 0", block
        )

    # ---- 18 Helper renders BLOCK envelope as class 2 --------------------

    def test_18_helper_block_class_two(self) -> None:
        envelope = {
            "verdict": "CUTOVER-DAY-MORGEN-BLOCK",
            "emitted_at_utc": "2026-06-08T06:05:00+00:00",
            "step_results": {
                "engine_composite": "red",
                "pyramide_composite": "green",
                "e2e_smoke": "green",
            },
            "window": {"iso_week": 24},
        }
        block = self.helper.render(envelope, today=date(2026, 6, 8))
        self.assertIn(
            "wakir_cutover_day_morgen_verdict_class 2", block
        )
        self.assertIn(
            'wakir_cutover_day_morgen_substrate_class{substrate="engine_composite"} 2',
            block,
        )

    # ---- 19 Aggregator + helper round-trip pin --------------------------

    def test_19_aggregator_to_helper_roundtrip(self) -> None:
        """
        Tag-64 aggregator -> Tag-65 helper byte-shape round-trip.
        Build a Tag-64 envelope via the aggregator helper, hand it
        to the Tag-65 renderer, assert the verdict-class line.
        """
        # Import aggregator fresh to avoid coupling with Tag-64 tests.
        spec = importlib.util.spec_from_file_location(
            "tag64_aggregator_under_test_tag66", AGGREGATOR_PATH
        )
        assert spec is not None and spec.loader is not None
        agg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(agg)
        envelopes = {
            "engine_composite": {"verdict": "PRE-CUTOVER-READY"},
            "pyramide_composite": {"verdict": "ACCEPTANCE-PYRAMIDE-READY"},
            "e2e_smoke": {"verdict": "E2E-READY"},
        }
        agg_env = agg.build_envelope(envelopes, iso_week=24)
        self.assertEqual(agg_env["verdict"], "CUTOVER-DAY-MORGEN-READY")
        block = self.helper.render(agg_env, today=date(2026, 6, 8))
        self.assertIn(
            "wakir_cutover_day_morgen_verdict_class 0", block
        )


if __name__ == "__main__":
    unittest.main()
