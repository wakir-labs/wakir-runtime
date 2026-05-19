# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-64 - Cutover-Day-Morgen Auto-Scheduler tests (Selin).

The Tag-64 Cutover-Day-Morgen Auto-Scheduler aggregates the three
top-level pre-cutover-acceptance verdicts (engine_composite,
pyramide_composite, e2e_smoke) into a single
``CUTOVER-DAY-MORGEN-READY`` / ``CUTOVER-DAY-MORGEN-CAUTION`` /
``CUTOVER-DAY-MORGEN-BLOCK`` verdict that operator-hand / AR-Hand
read every Mo-Fr 06:00 UTC cutover-week morning.

This hermetic test-suite pins:

* the byte-shape of the aggregator helper at
  ``tooling/ci/aggregate_cutover_day_morgen_verdict.py``,
* the byte-shape of the workflow at
  ``.github/workflows/cutover-day-morgen-auto-scheduler.yml``,
* the trinary decision rule (READY / CAUTION / BLOCK) under the
  full 27-combination matrix of three-substrate states,
* the missing-envelope-as-red defensive default,
* the KW-24..27 window-gating helper.

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
byte-shape relations the Tag-64 scheduler stakes.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from itertools import product
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
AGGREGATOR_PATH = (
    REPO_ROOT / "tooling" / "ci" / "aggregate_cutover_day_morgen_verdict.py"
)
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "cutover-day-morgen-auto-scheduler.yml"
)


def _load_aggregator():
    """Import the aggregator helper as a fresh module."""
    spec = importlib.util.spec_from_file_location(
        "tag64_aggregator_under_test", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None, AGGREGATOR_PATH
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- Verdict tokens per input substrate (for fixture generation) ----------

ENGINE_TOKENS = {
    "green": "PRE-CUTOVER-READY",
    "yellow": "PRE-CUTOVER-DRIFT",
    "red": "PRE-CUTOVER-DEFECT",
}
PYRAMIDE_TOKENS = {
    "green": "ACCEPTANCE-PYRAMIDE-READY",
    "yellow": "ACCEPTANCE-PYRAMIDE-DRIFT",
    "red": "ACCEPTANCE-PYRAMIDE-DEFECT",
}
E2E_TOKENS = {
    "green": "E2E-READY",
    "yellow": "E2E-DRIFT",
    "red": "E2E-DEFECT",
}


def _make_envelope(verdict: str) -> dict:
    """Minimal verdict-envelope shape (only ``verdict`` is read)."""
    return {"schema_version": 1, "verdict": verdict}


def _envelopes_for(
    *, engine: str, pyramide: str, e2e: str
) -> dict[str, dict]:
    return {
        "engine_composite": _make_envelope(ENGINE_TOKENS[engine]),
        "pyramide_composite": _make_envelope(PYRAMIDE_TOKENS[pyramide]),
        "e2e_smoke": _make_envelope(E2E_TOKENS[e2e]),
    }


class Tag64AggregatorShapeTests(unittest.TestCase):
    """Hermetic byte-shape pins for the Tag-64 aggregator helper."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.agg = _load_aggregator()

    # ---- 01 SUBSTRATES tuple shape --------------------------------------

    def test_01_substrates_tuple_canonical_order(self) -> None:
        """SUBSTRATES must be the exact canonical 3-tuple order."""
        self.assertEqual(
            self.agg.SUBSTRATES,
            ("engine_composite", "pyramide_composite", "e2e_smoke"),
        )

    # ---- 02 Verdict constants -------------------------------------------

    def test_02_verdict_constants_trinary_tokens(self) -> None:
        """Aggregated verdict constants are stable byte-strings."""
        self.assertEqual(self.agg.VERDICT_READY, "CUTOVER-DAY-MORGEN-READY")
        self.assertEqual(
            self.agg.VERDICT_CAUTION, "CUTOVER-DAY-MORGEN-CAUTION"
        )
        self.assertEqual(self.agg.VERDICT_BLOCK, "CUTOVER-DAY-MORGEN-BLOCK")

    # ---- 03 Per-substrate verdict-token maps ----------------------------

    def test_03_engine_verdict_map_complete(self) -> None:
        """Engine verdict-map covers exactly the three engine tokens."""
        self.assertEqual(
            set(self.agg.ENGINE_VERDICT_MAP.keys()),
            {"PRE-CUTOVER-READY", "PRE-CUTOVER-DRIFT", "PRE-CUTOVER-DEFECT"},
        )
        self.assertEqual(
            self.agg.ENGINE_VERDICT_MAP["PRE-CUTOVER-READY"], "green"
        )
        self.assertEqual(
            self.agg.ENGINE_VERDICT_MAP["PRE-CUTOVER-DRIFT"], "yellow"
        )
        self.assertEqual(
            self.agg.ENGINE_VERDICT_MAP["PRE-CUTOVER-DEFECT"], "red"
        )

    def test_04_pyramide_verdict_map_complete(self) -> None:
        """Pyramide verdict-map covers exactly the three pyramide tokens."""
        self.assertEqual(
            set(self.agg.PYRAMIDE_VERDICT_MAP.keys()),
            {
                "ACCEPTANCE-PYRAMIDE-READY",
                "ACCEPTANCE-PYRAMIDE-DRIFT",
                "ACCEPTANCE-PYRAMIDE-DEFECT",
            },
        )

    def test_05_e2e_verdict_map_complete(self) -> None:
        """E2E verdict-map covers exactly the three E2E tokens."""
        self.assertEqual(
            set(self.agg.E2E_VERDICT_MAP.keys()),
            {"E2E-READY", "E2E-DRIFT", "E2E-DEFECT"},
        )

    # ---- 06 Cutover-window helper ---------------------------------------

    def test_06_cutover_window_iso_weeks_exact(self) -> None:
        """Window constant is exactly KW-24..27."""
        self.assertEqual(
            self.agg.CUTOVER_WINDOW_ISO_WEEKS, (24, 25, 26, 27)
        )
        for wk in (24, 25, 26, 27):
            self.assertTrue(
                self.agg.is_in_cutover_window(wk), f"KW-{wk} should be in window"
            )
        for wk in (1, 23, 28, 53):
            self.assertFalse(
                self.agg.is_in_cutover_window(wk),
                f"KW-{wk} should be outside window",
            )
        self.assertFalse(self.agg.is_in_cutover_window(None))

    # ---- 07 decide() rule -- all-green path ------------------------------

    def test_07_decide_all_green_yields_ready(self) -> None:
        verdict = self.agg.decide(
            {"engine_composite": "green", "pyramide_composite": "green", "e2e_smoke": "green"}
        )
        self.assertEqual(verdict, "CUTOVER-DAY-MORGEN-READY")

    # ---- 08 decide() rule -- yellow degrades -----------------------------

    def test_08_decide_any_yellow_yields_caution(self) -> None:
        """A single yellow with zero reds collapses to CAUTION."""
        for substrate in ("engine_composite", "pyramide_composite", "e2e_smoke"):
            steps = {
                "engine_composite": "green",
                "pyramide_composite": "green",
                "e2e_smoke": "green",
            }
            steps[substrate] = "yellow"
            self.assertEqual(
                self.agg.decide(steps),
                "CUTOVER-DAY-MORGEN-CAUTION",
                f"yellow on {substrate} should yield CAUTION (got: {steps})",
            )

    # ---- 09 decide() rule -- red blocks ---------------------------------

    def test_09_decide_any_red_yields_block(self) -> None:
        """A single red anywhere collapses to BLOCK regardless of yellows."""
        for substrate in ("engine_composite", "pyramide_composite", "e2e_smoke"):
            steps = {
                "engine_composite": "green",
                "pyramide_composite": "yellow",
                "e2e_smoke": "green",
            }
            steps[substrate] = "red"
            self.assertEqual(
                self.agg.decide(steps),
                "CUTOVER-DAY-MORGEN-BLOCK",
                f"red on {substrate} should yield BLOCK (got: {steps})",
            )

    # ---- 10 decide() full 27-combination matrix --------------------------

    def test_10_decide_27_combination_matrix(self) -> None:
        """All 3**3=27 trinary combinations resolve deterministically."""
        for e, p, s in product(("green", "yellow", "red"), repeat=3):
            steps = {
                "engine_composite": e,
                "pyramide_composite": p,
                "e2e_smoke": s,
            }
            verdict = self.agg.decide(steps)
            if "red" in (e, p, s):
                expected = "CUTOVER-DAY-MORGEN-BLOCK"
            elif "yellow" in (e, p, s):
                expected = "CUTOVER-DAY-MORGEN-CAUTION"
            else:
                expected = "CUTOVER-DAY-MORGEN-READY"
            self.assertEqual(
                verdict,
                expected,
                f"({e},{p},{s}) -> expected {expected}, got {verdict}",
            )

    # ---- 11 build_envelope -- all-green happy path ----------------------

    def test_11_build_envelope_all_green_ready(self) -> None:
        envelopes = _envelopes_for(engine="green", pyramide="green", e2e="green")
        env = self.agg.build_envelope(envelopes, iso_week=24)
        self.assertEqual(env["verdict"], "CUTOVER-DAY-MORGEN-READY")
        self.assertEqual(env["counts"], {"green": 3, "yellow": 0, "red": 0})
        self.assertEqual(env["failed_steps"], [])
        self.assertEqual(env["window"]["iso_week"], 24)
        self.assertTrue(env["window"]["in_cutover_window"])
        self.assertEqual(env["window"]["cutover_iso_weeks"], [24, 25, 26, 27])

    # ---- 12 build_envelope -- yellow on pyramide -> CAUTION -------------

    def test_12_build_envelope_yellow_pyramide_caution(self) -> None:
        envelopes = _envelopes_for(
            engine="green", pyramide="yellow", e2e="green"
        )
        env = self.agg.build_envelope(envelopes, iso_week=25)
        self.assertEqual(env["verdict"], "CUTOVER-DAY-MORGEN-CAUTION")
        self.assertEqual(env["counts"], {"green": 2, "yellow": 1, "red": 0})
        self.assertEqual(env["failed_steps"], ["pyramide_composite"])
        self.assertIn("pyramide_composite", env["per_substrate_notes"])

    # ---- 13 build_envelope -- red on engine -> BLOCK --------------------

    def test_13_build_envelope_red_engine_block(self) -> None:
        envelopes = _envelopes_for(engine="red", pyramide="green", e2e="green")
        env = self.agg.build_envelope(envelopes, iso_week=26)
        self.assertEqual(env["verdict"], "CUTOVER-DAY-MORGEN-BLOCK")
        self.assertEqual(env["counts"], {"green": 2, "yellow": 0, "red": 1})
        self.assertEqual(env["failed_steps"], ["engine_composite"])

    # ---- 14 build_envelope -- missing envelope -> red defensive ---------

    def test_14_build_envelope_missing_envelope_is_red(self) -> None:
        """Missing input envelope normalises to red (block-on-missing)."""
        envelopes = {
            "engine_composite": None,
            "pyramide_composite": _make_envelope("ACCEPTANCE-PYRAMIDE-READY"),
            "e2e_smoke": _make_envelope("E2E-READY"),
        }
        env = self.agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "CUTOVER-DAY-MORGEN-BLOCK")
        self.assertEqual(env["step_results"]["engine_composite"], "red")
        self.assertIn("engine_composite", env["per_substrate_notes"])
        self.assertIn(
            "envelope missing",
            env["per_substrate_notes"]["engine_composite"],
        )
        self.assertIsNone(env["input_verdicts"]["engine_composite"])

    # ---- 15 build_envelope -- unknown verdict-token -> red --------------

    def test_15_build_envelope_unknown_verdict_token_red(self) -> None:
        envelopes = {
            "engine_composite": {"verdict": "PRE-CUTOVER-UNKNOWN-TOKEN"},
            "pyramide_composite": _make_envelope("ACCEPTANCE-PYRAMIDE-READY"),
            "e2e_smoke": _make_envelope("E2E-READY"),
        }
        env = self.agg.build_envelope(envelopes)
        self.assertEqual(env["verdict"], "CUTOVER-DAY-MORGEN-BLOCK")
        self.assertEqual(env["step_results"]["engine_composite"], "red")
        self.assertIn(
            "unknown verdict",
            env["per_substrate_notes"]["engine_composite"],
        )

    # ---- 16 build_envelope -- non-string verdict -> red -----------------

    def test_16_build_envelope_non_string_verdict_red(self) -> None:
        envelopes = {
            "engine_composite": {"verdict": 42},  # int, not string
            "pyramide_composite": _make_envelope("ACCEPTANCE-PYRAMIDE-READY"),
            "e2e_smoke": _make_envelope("E2E-READY"),
        }
        env = self.agg.build_envelope(envelopes)
        self.assertEqual(env["step_results"]["engine_composite"], "red")
        self.assertEqual(env["verdict"], "CUTOVER-DAY-MORGEN-BLOCK")

    # ---- 17 envelope schema -- required top-level keys ------------------

    def test_17_envelope_schema_required_top_level_keys(self) -> None:
        envelopes = _envelopes_for(engine="green", pyramide="green", e2e="green")
        env = self.agg.build_envelope(envelopes, iso_week=24)
        for key in (
            "schema_version",
            "workflow",
            "tag",
            "emitted_at_utc",
            "verdict",
            "step_results",
            "failed_steps",
            "per_substrate_notes",
            "counts",
            "window",
            "input_verdicts",
            "decision_rule",
        ):
            self.assertIn(key, env, f"envelope must carry {key}")
        self.assertEqual(env["schema_version"], 1)
        self.assertEqual(env["workflow"], "cutover-day-morgen-auto-scheduler")
        self.assertEqual(env["tag"], "tag-64")

    # ---- 18 _load_envelope -- file missing returns None -----------------

    def test_18_load_envelope_missing_file_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "nope.json"
            self.assertIsNone(self.agg._load_envelope(missing))
        self.assertIsNone(self.agg._load_envelope(None))

    # ---- 19 _load_envelope -- invalid JSON returns None -----------------

    def test_19_load_envelope_invalid_json_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "bad.json"
            bad.write_text("{not valid json", encoding="utf-8")
            self.assertIsNone(self.agg._load_envelope(bad))

    # ---- 20 _load_envelope -- non-object JSON returns None --------------

    def test_20_load_envelope_non_object_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            arr = Path(tmpdir) / "arr.json"
            arr.write_text("[1, 2, 3]", encoding="utf-8")
            self.assertIsNone(self.agg._load_envelope(arr))

    # ---- 21 CLI -- end-to-end write produces a valid envelope -----------

    def test_21_cli_main_writes_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            eng = base / "engine.json"
            pyr = base / "pyramide.json"
            e2e = base / "e2e.json"
            out = base / "out" / "verdict.json"
            eng.write_text(
                json.dumps({"verdict": "PRE-CUTOVER-READY"}), encoding="utf-8"
            )
            pyr.write_text(
                json.dumps({"verdict": "ACCEPTANCE-PYRAMIDE-READY"}),
                encoding="utf-8",
            )
            e2e.write_text(
                json.dumps({"verdict": "E2E-READY"}), encoding="utf-8"
            )
            rc = self.agg.main(
                [
                    "--engine-envelope",
                    str(eng),
                    "--pyramide-envelope",
                    str(pyr),
                    "--e2e-envelope",
                    str(e2e),
                    "--iso-week",
                    "24",
                    "--output",
                    str(out),
                ]
            )
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["verdict"], "CUTOVER-DAY-MORGEN-READY")
            self.assertEqual(payload["window"]["iso_week"], 24)

    # ---- 22 CLI -- missing all three envelopes yields BLOCK -------------

    def test_22_cli_main_all_missing_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            out = base / "v.json"
            rc = self.agg.main(["--output", str(out)])
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["verdict"], "CUTOVER-DAY-MORGEN-BLOCK")
            self.assertEqual(payload["counts"]["red"], 3)


class Tag64WorkflowShapeTests(unittest.TestCase):
    """Hermetic byte-shape pins for the workflow YAML (regex-shape only)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_23_workflow_exists_and_is_yaml(self) -> None:
        self.assertTrue(WORKFLOW_PATH.exists(), WORKFLOW_PATH)
        self.assertTrue(WORKFLOW_PATH.is_file())

    def test_24_workflow_name_matches(self) -> None:
        self.assertIn("name: cutover-day-morgen-auto-scheduler", self.text)

    def test_25_workflow_cron_window_gating(self) -> None:
        """Cron must be Mo-Fr 06:00 UTC -- ``0 6 * * 1-5``."""
        self.assertIn('- cron: "0 6 * * 1-5"', self.text)

    def test_26_workflow_invokes_aggregator(self) -> None:
        """Stage 4 must invoke the Tag-64 aggregator helper."""
        self.assertIn(
            "tooling/ci/aggregate_cutover_day_morgen_verdict.py", self.text
        )

    def test_27_workflow_reads_all_three_top_level_workflows(self) -> None:
        """The three Stage-N fetch steps reference the three workflows."""
        self.assertIn(
            "persona-engine-pre-cutover-final-acceptance-composite.yml",
            self.text,
        )
        self.assertIn(
            "pyramide-acceptance-pre-cutover-compositum.yml", self.text
        )
        self.assertIn(
            "pre-cutover-final-acceptance-e2e-smoke.yml", self.text
        )

    def test_28_workflow_has_workflow_dispatch_force_iso_week(self) -> None:
        """workflow_dispatch surface must expose force_iso_week input."""
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("force_iso_week:", self.text)

    def test_29_workflow_uploads_verdict_artifact(self) -> None:
        """The verdict envelope must be uploaded as a downstream artifact."""
        self.assertIn("name: cutover-day-morgen-verdict", self.text)
        self.assertIn("actions/upload-artifact@v4", self.text)

    def test_30_workflow_has_three_named_stages(self) -> None:
        """Stage-1..4 step-name discipline (operator-hand readability)."""
        self.assertIn(
            "Stage 1 -- Fetch Engine-Composite verdict (Selin Tag-61/63)",
            self.text,
        )
        self.assertIn(
            "Stage 2 -- Fetch Pyramide-Composite verdict (Amara Tag-62)",
            self.text,
        )
        self.assertIn(
            "Stage 3 -- Fetch E2E-Smoke verdict (Amara Tag-63)",
            self.text,
        )
        self.assertIn(
            "Stage 4 -- Aggregate Cutover-Day-Morgen verdict", self.text
        )


if __name__ == "__main__":
    unittest.main()
