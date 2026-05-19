# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-59 — V-907 Persona-Hash-Pin-Build-Step (Selin, Persona-Engine).

Engine 0.5.3-rc1 (Tag-58, PR #372) is the final Pre-Cutover RC before
the KW-24 cutover gate opens. The V-907 persona-hash anchor binds
three authority surfaces:

  1. Manifest §1 — the ten-row component-inventory table
     (``wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md``).
  2. Pin-Pack ``boot_wired_crates`` — the YAML list section in
     ``infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml``.
  3. engine.py resolver-block — the import block + resolver-call
     sites in ``wirelang/persona_engine/engine.py``.

A baseline lock at ``wirelang/persona_engine/v907-hash-baseline.json``
pins the composite hash and per-segment hashes. The CI gate
``v907-persona-hash-pin-build-step.yml`` re-computes the composite
hash on every PR / push and refuses to merge on HASH-PIN-DRIFT.

This test-suite is stdlib-only (no pip install needed in CI) and is
hermetic against the live tree: it loads the live authority surfaces
+ the baseline + the verifier helper, and asserts:

* The verifier helper imports and exposes its public surface.
* The slice extractors return non-empty, deterministic bytes.
* The composite hash matches the baseline (HASH-PIN-INTACT).
* The baseline JSON contains exactly the expected keys.
* The baseline pins engine 0.5.3-rc1 (Tag-58 PR #372 carry-forward).
* All ten resolver-function names appear in the engine.py slice.
* The Manifest §1 slice starts with the §1 heading and contains all
  ten component-inventory rows.
* The Pin-Pack slice starts with ``boot_wired_crates:`` and contains
  the v907-verify entry.
* The verifier helper exit-code is 0 on a clean tree (HASH-PIN-INTACT).
* The composite-hash algorithm uses the canonical ASCII US separator.
* The drift envelope localises per-segment drift correctly.
* The CI workflow path-filter covers every authority surface.

The test-count is >= 12 (see ADR-0023b V-907-Annex test-floor
discipline; Tag-58 spec-seal probe set the precedent at 12).

Scope discipline (Selin, ADR-0036/0043/0065/0066): this file pins
the persona-engine CI surface. It does **not** modify persona
definitions (Aisha-Domäne), WAT-core / V-907 logic (Tomás-Domäne,
Zone-K), identity-substrate (Reza-Domäne, Zone-L), or container-
infra (Kai-Domäne, Zone-J). Cross-zone unangetastet.
"""

from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import unittest
from typing import Dict


# ---------------------------------------------------------------------------
# Repo-root resolution — walk up from this file until we find the marker
# files. The test is hermetic against the live tree.
# ---------------------------------------------------------------------------


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists() and (
            candidate / ".github" / "workflows"
        ).is_dir():
            return candidate
    raise RuntimeError("could not locate repository root from %s" % here)


REPO_ROOT = _repo_root()
VERIFIER_PATH = REPO_ROOT / "tooling" / "ci" / "verify_v907_persona_hash_pin.py"
BASELINE_PATH = (
    REPO_ROOT / "wirelang" / "persona_engine" / "v907-hash-baseline.json"
)
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "v907-persona-hash-pin-build-step.yml"
)
MANIFEST_PATH = (
    REPO_ROOT
    / "wirelang"
    / "persona_engine"
    / "MANIFEST-0.5.2-final-pre-cutover.md"
)
PIN_PACK_PATH = (
    REPO_ROOT
    / "infra"
    / "persona-engine"
    / "pin-pack-0.5.2-final-pre-cutover.yaml"
)
ENGINE_PY_PATH = REPO_ROOT / "wirelang" / "persona_engine" / "engine.py"


def _load_verifier_module():
    module_name = "_verify_v907_persona_hash_pin_tag59"
    spec = importlib.util.spec_from_file_location(module_name, VERIFIER_PATH)
    assert spec and spec.loader, "verifier spec failed to load"
    module = importlib.util.module_from_spec(spec)
    # Register before exec so ``@dataclasses.dataclass`` can resolve
    # the module via ``sys.modules.get(cls.__module__)`` on Python 3.12+
    # (where dataclass introspection touches the module dict).
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


VERIFIER = _load_verifier_module()


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


class VerifierHelperSurfaceTests(unittest.TestCase):
    """The verifier helper module exposes the expected public surface."""

    def test_01_helper_module_loads(self) -> None:
        self.assertTrue(hasattr(VERIFIER, "run_audit"))
        self.assertTrue(hasattr(VERIFIER, "compute_composite_hash"))
        self.assertTrue(hasattr(VERIFIER, "slice_manifest_section_1"))
        self.assertTrue(hasattr(VERIFIER, "slice_pin_pack_boot_wired_crates"))
        self.assertTrue(hasattr(VERIFIER, "slice_engine_py_resolvers"))
        self.assertTrue(hasattr(VERIFIER, "RESOLVER_NAMES"))
        self.assertTrue(hasattr(VERIFIER, "UNIT_SEPARATOR"))
        self.assertTrue(hasattr(VERIFIER, "HashPinEnvelope"))

    def test_02_resolver_names_are_ten_canonical_boot_records(self) -> None:
        expected = {
            "resolve_recovery_backend",
            "resolve_state_backing_backend",
            "resolve_fsm_backend",
            "resolve_v907_verify_backend",
            "resolve_bridge_diff_backend",
            "resolve_subscribe_loop_backend",
            "resolve_anchor_emitter_backend",
            "resolve_svid_workload_identity_backend",
            "resolve_federation_resolver_backend",
            "resolve_bridge_audit_writer_backend",
        }
        self.assertEqual(set(VERIFIER.RESOLVER_NAMES), expected)
        self.assertEqual(
            len(VERIFIER.RESOLVER_NAMES),
            10,
            "boot fan-out is exactly ten records — V-907 = record #4.",
        )

    def test_03_unit_separator_is_ascii_us(self) -> None:
        # The composite hash uses the ASCII unit-separator (U+001F)
        # between segments so segment re-ordering can never collide.
        # The value must be a single byte.
        self.assertEqual(VERIFIER.UNIT_SEPARATOR, "\x1f")
        self.assertEqual(len(VERIFIER.UNIT_SEPARATOR.encode("utf-8")), 1)


class AuthoritySurfacePresenceTests(unittest.TestCase):
    """All three authority-surface files + the baseline + the workflow exist."""

    def test_04_all_authority_surfaces_present(self) -> None:
        for label, path in (
            ("manifest", MANIFEST_PATH),
            ("pin_pack", PIN_PACK_PATH),
            ("engine_py", ENGINE_PY_PATH),
            ("baseline", BASELINE_PATH),
            ("verifier", VERIFIER_PATH),
            ("workflow", WORKFLOW_PATH),
        ):
            with self.subTest(surface=label):
                self.assertTrue(path.exists(), f"{label} missing: {path}")


class SliceExtractionTests(unittest.TestCase):
    """The slice extractors return non-empty, well-formed bytes."""

    def test_05_manifest_slice_starts_with_section_1_heading(self) -> None:
        text = MANIFEST_PATH.read_text(encoding="utf-8")
        sliced = VERIFIER.slice_manifest_section_1(text)
        first_line = sliced.splitlines()[0]
        self.assertTrue(
            first_line.startswith("## 1. Component Inventory"),
            f"manifest slice first line = {first_line!r}",
        )

    def test_06_manifest_slice_contains_all_ten_record_rows(self) -> None:
        text = MANIFEST_PATH.read_text(encoding="utf-8")
        sliced = VERIFIER.slice_manifest_section_1(text)
        # Each row in the §1 table starts with "| N |" where N is 1..10.
        for record_num in range(1, 11):
            with self.subTest(record=record_num):
                self.assertIn(
                    f"| {record_num} |",
                    sliced,
                    f"manifest §1 row #{record_num} missing from slice",
                )

    def test_07_pin_pack_slice_contains_v907_verify(self) -> None:
        text = PIN_PACK_PATH.read_text(encoding="utf-8")
        sliced = VERIFIER.slice_pin_pack_boot_wired_crates(text)
        self.assertTrue(sliced.startswith("boot_wired_crates:"))
        self.assertIn("persona-engine-v907-verify", sliced)
        self.assertIn("WAKIR_V907_VERIFY_BACKEND", sliced)
        # The slice MUST NOT include the next top-level key
        # ``boot_unwired_crates:`` as a non-comment line.
        for line in sliced.splitlines():
            if line.startswith("boot_unwired_crates:"):
                self.fail(
                    "pin_pack slice leaked into the next top-level key"
                )

    def test_08_engine_py_slice_mentions_all_ten_resolvers(self) -> None:
        text = ENGINE_PY_PATH.read_text(encoding="utf-8")
        sliced = VERIFIER.slice_engine_py_resolvers(text)
        for name in VERIFIER.RESOLVER_NAMES:
            with self.subTest(resolver=name):
                self.assertIn(name, sliced)


class CompositeHashTests(unittest.TestCase):
    """The composite hash uses a tamper-resistant joiner."""

    def test_09_composite_hash_uses_unit_separator(self) -> None:
        # If we re-order the three segments the hash MUST change.
        h1 = VERIFIER.compute_composite_hash("a", "b", "c")
        h2 = VERIFIER.compute_composite_hash("b", "a", "c")
        h3 = VERIFIER.compute_composite_hash("a", "c", "b")
        self.assertNotEqual(h1, h2)
        self.assertNotEqual(h1, h3)
        self.assertNotEqual(h2, h3)

    def test_10_composite_hash_is_deterministic(self) -> None:
        h1 = VERIFIER.compute_composite_hash("alpha", "beta", "gamma")
        h2 = VERIFIER.compute_composite_hash("alpha", "beta", "gamma")
        self.assertEqual(h1, h2)
        # SHA-256 hex is exactly 64 characters.
        self.assertEqual(len(h1), 64)
        int(h1, 16)  # raises if not valid hex


class BaselineLockTests(unittest.TestCase):
    """The baseline lock JSON has the expected shape."""

    def setUp(self) -> None:
        self.baseline = json.loads(
            BASELINE_PATH.read_text(encoding="utf-8")
        )

    def test_11_baseline_has_all_required_keys(self) -> None:
        required = {
            "engine_version",
            "baseline_tag",
            "baseline_emitted_utc",
            "baseline_carry_forward_pr",
            "manifest_relpath",
            "pin_pack_relpath",
            "engine_py_relpath",
            "segment_hashes",
            "segment_byte_lengths",
            "composite_hash",
            "composite_algorithm",
            "note",
        }
        self.assertTrue(
            required.issubset(self.baseline.keys()),
            f"baseline keys missing: {required - set(self.baseline.keys())}",
        )

    def test_12_baseline_pins_engine_0_5_3_rc1_tag_58_pr_372(self) -> None:
        self.assertEqual(self.baseline["engine_version"], "0.5.3-rc1")
        self.assertEqual(self.baseline["baseline_tag"], "tag-59")
        self.assertEqual(self.baseline["baseline_carry_forward_pr"], 372)

    def test_13_baseline_segment_hashes_have_three_canonical_keys(self) -> None:
        expected = {
            "manifest_section_1",
            "pin_pack_boot_wired_crates",
            "engine_py_resolvers",
        }
        self.assertEqual(set(self.baseline["segment_hashes"]), expected)
        for k, v in self.baseline["segment_hashes"].items():
            with self.subTest(segment=k):
                self.assertEqual(len(v), 64, f"segment {k} hash is not SHA-256 hex")
                int(v, 16)  # raises if not valid hex

    def test_14_baseline_composite_hash_is_sha256_hex(self) -> None:
        composite = self.baseline["composite_hash"]
        self.assertEqual(len(composite), 64)
        int(composite, 16)


class LiveVerdictTests(unittest.TestCase):
    """The live tree currently passes HASH-PIN-INTACT."""

    def test_15_run_audit_returns_intact_envelope(self) -> None:
        envelope = VERIFIER.run_audit(REPO_ROOT)
        self.assertEqual(envelope.verdict, "HASH-PIN-INTACT")
        self.assertEqual(envelope.verdict_class, "intact")
        self.assertEqual(envelope.engine_version, "0.5.3-rc1")
        self.assertEqual(envelope.drifted_segments, [])
        self.assertEqual(
            envelope.composite_hash, envelope.baseline_composite_hash
        )

    def test_16_verifier_cli_exits_zero_on_clean_tree(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(VERIFIER_PATH),
                "--repo-root",
                str(REPO_ROOT),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"verifier CLI exited {proc.returncode}; stderr={proc.stderr}",
        )
        envelope = json.loads(proc.stdout.strip())
        self.assertEqual(envelope["verdict"], "HASH-PIN-INTACT")
        self.assertEqual(envelope["verdict_class"], "intact")


class DriftLocalisationTests(unittest.TestCase):
    """A simulated drift in any single segment is localised correctly."""

    def _run_with_patched_baseline(self, patched: Dict) -> object:
        """Write a patched baseline to a temp file + run the audit."""
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(patched, fh)
            tmp_path = pathlib.Path(fh.name)
        try:
            return VERIFIER.run_audit(REPO_ROOT, baseline_path=tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_17_drift_in_manifest_segment_is_localised(self) -> None:
        clean = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        bad = json.loads(json.dumps(clean))
        bad["segment_hashes"]["manifest_section_1"] = "0" * 64
        bad["composite_hash"] = "0" * 64
        env = self._run_with_patched_baseline(bad)
        self.assertEqual(env.verdict, "HASH-PIN-DRIFT")
        self.assertEqual(env.drifted_segments, ["manifest_section_1"])
        self.assertTrue(env.verdict_class.startswith("single-segment-drift:"))
        self.assertIn("manifest_section_1", env.verdict_class)

    def test_18_drift_in_two_segments_classed_multi(self) -> None:
        clean = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        bad = json.loads(json.dumps(clean))
        bad["segment_hashes"]["manifest_section_1"] = "0" * 64
        bad["segment_hashes"]["engine_py_resolvers"] = "0" * 64
        bad["composite_hash"] = "0" * 64
        env = self._run_with_patched_baseline(bad)
        self.assertEqual(env.verdict, "HASH-PIN-DRIFT")
        self.assertEqual(
            sorted(env.drifted_segments),
            ["engine_py_resolvers", "manifest_section_1"],
        )
        self.assertEqual(env.verdict_class, "multi-segment-drift")


class WorkflowSurfaceTests(unittest.TestCase):
    """The CI workflow path-filter covers every authority surface."""

    def test_19_workflow_path_filter_covers_authority_surfaces(self) -> None:
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        # The workflow must trigger on edits to:
        # * wirelang/persona_engine/** (covers manifest, engine.py,
        #   __version__.py, baseline JSON, and all sibling modules)
        # * docs/persona-engine/** (release-notes)
        # * the dedicated pin-pack-0.5.2-final YAML
        # * the verifier helper
        # * the test-suite
        # * itself
        for needle in (
            "wirelang/persona_engine/**",
            "docs/persona-engine/**",
            "infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml",
            "tooling/ci/verify_v907_persona_hash_pin.py",
            "wirelang/tests/persona_engine/test_v907_hash_pin_build_step_tag59.py",
            ".github/workflows/v907-persona-hash-pin-build-step.yml",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_20_workflow_emits_intact_or_drift_verdict(self) -> None:
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("HASH-PIN-INTACT", text)
        self.assertIn("HASH-PIN-DRIFT", text)
        # Enforce mode default: 'true'.
        self.assertIn("default: 'true'", text)
        # Triggers: push, pull_request, workflow_dispatch.
        self.assertIn("push:", text)
        self.assertIn("pull_request:", text)
        self.assertIn("workflow_dispatch:", text)


if __name__ == "__main__":
    unittest.main()
