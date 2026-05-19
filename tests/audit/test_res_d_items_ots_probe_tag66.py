# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-66 hermetic invariants for the per-RES-Dn item OTS probe.

This suite covers the Tag-66 extension to
``tooling/ots/emit_wirelang_spec_ots_marker.py`` that introduces the
``--mode res-d-item-probe --res-d-item RES-D[1-5]`` flag pair, the
matrix-strategy block in
``.github/workflows/wirelang-spec-ots-pre-anchor-probe.yml``, and the
shared invariant that the v0.4.4 draft markdown file is NEVER
touched by the probe.

All tests are stdlib-only; no network I/O, no subprocess to ``ots``
CLI, no podman socket. The suite is a sibling of Tag-60's
``test_wirelang_spec_ots_pre_anchor_probe_tag60.py`` and reuses the
helper-loading pattern from that file.

Test count: 18 (>= 15 per Tag-66 brief).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling" / "ots" / "emit_wirelang_spec_ots_marker.py"
DRAFT_PATH = (
    REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-4-draft.md"
)
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "wirelang-spec-ots-pre-anchor-probe.yml"
)


def _load_helper_module():
    spec = importlib.util.spec_from_file_location(
        "emit_wirelang_spec_ots_marker_tag66", HELPER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper at {HELPER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HELPER = _load_helper_module()


FIXED_NOW = _dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.timezone.utc)


class TestResDItemConstants(unittest.TestCase):
    """Tag-66 constant-table invariants — pin the RES-D vocabulary."""

    def test_all_five_items_present(self):
        self.assertEqual(
            HELPER.RES_D_ITEM_IDS,
            ("RES-D1", "RES-D2", "RES-D3", "RES-D4", "RES-D5"),
        )

    def test_item_metadata_complete(self):
        for item in HELPER.RES_D_ITEM_IDS:
            meta = HELPER.RES_D_ITEM_METADATA[item]
            self.assertIn("topic", meta)
            self.assertIn("candidate_section", meta)
            self.assertIn("sample_block", meta)
            for key in ("topic", "candidate_section", "sample_block"):
                self.assertIsInstance(meta[key], str)
                self.assertGreater(len(meta[key]), 0)

    def test_verdict_required_keys_shape(self):
        # Tag-66 verdict must add res_d_item + item_metadata +
        # draft_untouched on top of the Tag-60 base shape.
        required = HELPER.RES_D_ITEM_VERDICT_REQUIRED_KEYS
        for k in (
            "schema_version", "kind", "mode", "verdict", "stages",
            "spec_sha256", "spec_size_bytes", "probed_at_utc",
            "ar_authorisation_required", "anchors",
            # Tag-66 additions:
            "res_d_item", "item_metadata", "draft_untouched",
        ):
            self.assertIn(k, required, f"missing required key: {k}")

    def test_stage_keys_include_item_simulation(self):
        self.assertIn("item_simulation", HELPER.RES_D_PROBE_STAGE_KEYS)
        self.assertEqual(len(HELPER.RES_D_PROBE_STAGE_KEYS), 5)


class TestPerItemProbeHappyPath(unittest.TestCase):
    """Per-item probe verdicts against the live v0.4.4 draft."""

    def test_all_five_items_probe_ready_against_live_draft(self):
        for item in HELPER.RES_D_ITEM_IDS:
            verdict = HELPER.run_res_d_item_probe(
                res_d_item=item,
                spec_path=DRAFT_PATH,
                actor="unit-test",
                now_utc=FIXED_NOW,
                repo_root=REPO_ROOT,
            )
            self.assertEqual(
                verdict["verdict"], "PROBE-READY",
                f"{item}: expected PROBE-READY, got {verdict}"
            )
            self.assertEqual(verdict["res_d_item"], item)
            self.assertTrue(verdict["draft_untouched"])
            self.assertTrue(verdict["ar_authorisation_required"])

    def test_verdict_envelope_shape_strict(self):
        verdict = HELPER.run_res_d_item_probe(
            res_d_item="RES-D1",
            spec_path=DRAFT_PATH,
            actor="unit-test",
            now_utc=FIXED_NOW,
            repo_root=REPO_ROOT,
        )
        self.assertEqual(
            set(verdict.keys()),
            HELPER.RES_D_ITEM_VERDICT_REQUIRED_KEYS,
        )
        self.assertEqual(verdict["schema_version"], 1)
        self.assertEqual(verdict["kind"], "ots-res-d-item-probe-verdict")
        self.assertEqual(verdict["mode"], "res-d-item-probe")

    def test_each_item_carries_its_own_metadata(self):
        for item in HELPER.RES_D_ITEM_IDS:
            verdict = HELPER.run_res_d_item_probe(
                res_d_item=item,
                spec_path=DRAFT_PATH,
                actor="unit-test",
                now_utc=FIXED_NOW,
                repo_root=REPO_ROOT,
            )
            self.assertEqual(
                verdict["item_metadata"]["topic"],
                HELPER.RES_D_ITEM_METADATA[item]["topic"],
            )
            self.assertEqual(
                verdict["item_metadata"]["candidate_section"],
                HELPER.RES_D_ITEM_METADATA[item]["candidate_section"],
            )

    def test_item_simulation_stage_runs_and_passes(self):
        verdict = HELPER.run_res_d_item_probe(
            res_d_item="RES-D3",
            spec_path=DRAFT_PATH,
            actor="unit-test",
            now_utc=FIXED_NOW,
            repo_root=REPO_ROOT,
        )
        self.assertIsInstance(verdict["stages"]["item_simulation"], str)
        self.assertTrue(
            verdict["stages"]["item_simulation"].startswith("OK"),
            f"item_simulation not OK: {verdict['stages']['item_simulation']}"
        )
        self.assertIn(
            "RES-D3", verdict["stages"]["item_simulation"]
        )
        self.assertIn(
            "draft untouched",
            verdict["stages"]["item_simulation"],
        )


class TestPerItemProbeDefectPaths(unittest.TestCase):
    """Negative cases — Tag-66 must produce PROBE-DEFECT correctly."""

    def test_unknown_item_yields_defect(self):
        verdict = HELPER.run_res_d_item_probe(
            res_d_item="RES-D99",
            spec_path=DRAFT_PATH,
            actor="unit-test",
            now_utc=FIXED_NOW,
            repo_root=REPO_ROOT,
        )
        self.assertEqual(verdict["verdict"], "PROBE-DEFECT")
        self.assertEqual(verdict["res_d_item"], "RES-D99")
        # Envelope shape stable even for unknown items.
        self.assertEqual(
            set(verdict.keys()),
            HELPER.RES_D_ITEM_VERDICT_REQUIRED_KEYS,
        )

    def test_wrong_spec_path_yields_defect(self):
        wrong = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"
        if not wrong.is_file():
            self.skipTest(f"v0-4-3 spec missing at {wrong}")
        verdict = HELPER.run_res_d_item_probe(
            res_d_item="RES-D2",
            spec_path=wrong,
            actor="unit-test",
            now_utc=FIXED_NOW,
            repo_root=REPO_ROOT,
        )
        self.assertEqual(verdict["verdict"], "PROBE-DEFECT")
        self.assertTrue(
            verdict["stages"]["input_validation"].startswith("FAIL"),
            verdict["stages"]["input_validation"],
        )

    def test_missing_spec_yields_defect(self):
        missing = REPO_ROOT / "wirelang" / "specs" / "does-not-exist.md"
        verdict = HELPER.run_res_d_item_probe(
            res_d_item="RES-D1",
            spec_path=missing,
            actor="unit-test",
            now_utc=FIXED_NOW,
            repo_root=REPO_ROOT,
        )
        self.assertEqual(verdict["verdict"], "PROBE-DEFECT")
        self.assertTrue(
            verdict["stages"]["input_validation"].startswith(
                "FAIL: spec not found"
            )
        )

    def test_simulate_with_missing_anchor_yields_fail(self):
        # Use a temp file that explicitly omits the RES-D2 anchors.
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("# Not the v0.4.4 draft\n\nNo RES-D anchors here.\n")
            tmp_path = Path(fh.name)
        try:
            result = HELPER._simulate_res_d_item_activation(
                res_d_item="RES-D2",
                spec_path=tmp_path,
            )
            self.assertTrue(result.startswith("FAIL"), result)
            self.assertIn("RES-D2", result)
        finally:
            tmp_path.unlink(missing_ok=True)


class TestDraftUntouchedInvariant(unittest.TestCase):
    """The Tag-66 ``draft_untouched`` invariant must hold absolutely."""

    def test_draft_hash_unchanged_after_full_probe_run(self):
        # Capture SHA-256 of v0.4.4 draft before and after running
        # the probe across all 5 items. The probe must never write
        # to the draft.
        before = hashlib.sha256(DRAFT_PATH.read_bytes()).hexdigest()
        for item in HELPER.RES_D_ITEM_IDS:
            HELPER.run_res_d_item_probe(
                res_d_item=item,
                spec_path=DRAFT_PATH,
                actor="unit-test",
                now_utc=FIXED_NOW,
                repo_root=REPO_ROOT,
            )
        after = hashlib.sha256(DRAFT_PATH.read_bytes()).hexdigest()
        self.assertEqual(
            before, after,
            "v0.4.4 draft was modified by Tag-66 probe — "
            "draft_untouched invariant violated",
        )

    def test_draft_untouched_flag_always_true(self):
        for item in HELPER.RES_D_ITEM_IDS + ("RES-D99",):
            verdict = HELPER.run_res_d_item_probe(
                res_d_item=item,
                spec_path=DRAFT_PATH,
                actor="unit-test",
                now_utc=FIXED_NOW,
                repo_root=REPO_ROOT,
            )
            self.assertTrue(
                verdict["draft_untouched"],
                f"draft_untouched not True for {item}",
            )


class TestSandboxBoundaryAndHermeticity(unittest.TestCase):
    """The probe must not perform network I/O or OTS-CLI calls."""

    def test_helper_module_imports_only_stdlib(self):
        # The helper is stdlib-only; verify its sys.modules
        # footprint at import-time contains no third-party packages
        # by scanning import statements only (not the docstring).
        src_lines = HELPER_PATH.read_text(encoding="utf-8").splitlines()
        # Filter to lines that look like import statements at module
        # top level (no leading whitespace) — keep the check tight
        # so the docstring narrative ("No subprocess calls") doesn't
        # produce a false positive.
        import_lines = [
            line for line in src_lines
            if line.startswith("import ") or line.startswith("from ")
        ]
        joined = "\n".join(import_lines)
        for forbidden in ("requests", "httpx", "opentimestamps",
                          "subprocess", "socket", "urllib.request"):
            self.assertNotIn(
                forbidden, joined,
                f"forbidden module imported by helper: {forbidden!r}\n"
                f"import lines: {import_lines}"
            )

    def test_sandbox_boundary_stage_always_ok(self):
        for item in HELPER.RES_D_ITEM_IDS:
            verdict = HELPER.run_res_d_item_probe(
                res_d_item=item,
                spec_path=DRAFT_PATH,
                actor="unit-test",
                now_utc=FIXED_NOW,
                repo_root=REPO_ROOT,
            )
            self.assertEqual(
                verdict["stages"]["sandbox_boundary"], "OK"
            )


class TestCLIDispatch(unittest.TestCase):
    """The new ``--mode res-d-item-probe`` CLI flag must dispatch."""

    def test_cli_requires_res_d_item_in_res_d_mode(self):
        # Capture stderr; missing --res-d-item should return exit-2.
        rc = HELPER.main([
            "--mode", "res-d-item-probe",
            "--spec", str(DRAFT_PATH),
            "--probe-verdict-out", "/tmp/tag66-cli-missing-item.json",
        ])
        self.assertEqual(rc, 2)

    def test_cli_emits_verdict_for_each_item(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "verdict.json"
            rc = HELPER.main([
                "--mode", "res-d-item-probe",
                "--res-d-item", "RES-D4",
                "--spec", str(DRAFT_PATH),
                "--probe-verdict-out", str(out),
                "--now", "2026-05-19T12:00:00+00:00",
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(out.is_file())
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["res_d_item"], "RES-D4")
            self.assertEqual(data["verdict"], "PROBE-READY")

    def test_cli_pre_activation_probe_mode_still_works(self):
        # Regression: Tag-60 mode must keep working untouched.
        v043 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"
        if not v043.is_file():
            self.skipTest(f"v0-4-3 spec missing at {v043}")
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "tag60.json"
            rc = HELPER.main([
                "--mode", "pre-activation-probe",
                "--spec", str(v043),
                "--probe-verdict-out", str(out),
                "--now", "2026-05-19T12:00:00+00:00",
            ])
            self.assertEqual(rc, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["kind"], "ots-pre-activation-probe-verdict")


class TestWorkflowWiring(unittest.TestCase):
    """The matrix-strategy in the workflow must list all 5 items."""

    def test_workflow_contains_matrix_strategy(self):
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("wirelang-spec-res-d-item-probe", text)
        self.assertIn("res_d_item:", text)
        for item in HELPER.RES_D_ITEM_IDS:
            self.assertIn(item, text,
                          f"workflow missing matrix entry for {item}")

    def test_workflow_aggregator_job_present(self):
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("wirelang-spec-res-d-aggregate", text)
        self.assertIn("test_res_d_items_ots_probe_tag66", text)

    def test_workflow_paths_include_v044_draft(self):
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("wirelang/specs/wirelang-spec-v0-4-4-draft.md", text)


if __name__ == "__main__":
    unittest.main()
