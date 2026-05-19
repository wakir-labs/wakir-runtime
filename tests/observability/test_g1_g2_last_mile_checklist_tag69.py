# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Tag-69 hermetic test-suite for the Tag-69 G1+G2 Operator-Hand Last-Mile
Checklist + its verifier helper.

Substance brief (>= 12 tests; suite carries 15):

  1. Verifier module imports clean (no side-effects on import).
  2. Verifier exposes the documented stage-class constants
     (EVE_CHECKS, T0_STEPS, G1_WAVES, G2_SUBSTEPS, VERIFICATION_PROBES,
     FAILURE_TRIGGERS, REQUIRED_SECTION_IDS).
  3. Verifier CLI exits 0 on the live Tag-69 doc.
  4. Verifier emits a parseable JSON envelope under --json.
  5. JSON envelope carries 40 stage probes (12+10+4+3+6+5).
  6. Every Eve-Check (E1..E12) probe lands PASS.
  7. Every T0-step (T0.0..T0.9) probe lands PASS.
  8. Every G1 wave (G1.W1..G1.W4) probe lands PASS.
  9. Every G2 sub-step (G2.S1..G2.S3) probe lands PASS.
 10. Every verification probe (V1..V6) lands PASS.
 11. Every failure-recovery trigger (F1..F5) lands PASS.
 12. All §8.1 cross-reference paths resolve on disk.
 13. Verifier flips to DEFECT when the doc is missing (synthetic fixture).
 14. Verifier flips to DRIFT when an Eve-Check loses a required field
     (synthetic fixture, hermetic - no real doc mutated).
 15. Verifier is hermetic: no network-I/O imports.

Suite is hermetic: zero network, zero podman, zero gh api, zero cosign.
All synthetic fixtures live under tmp_path.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "verify_g1_g2_last_mile_checklist_doc.py"
DOC_PATH = REPO_ROOT / "docs" / "operations" / "g1-g2-last-mile-operator-checklist.md"

# Make tooling/ci importable for direct-API tests.
sys.path.insert(0, str(REPO_ROOT / "tooling" / "ci"))


@pytest.fixture(scope="module")
def helper_module():
    """Import the verifier as a Python module for in-process probing.

    Register the module in ``sys.modules`` before ``exec_module`` to
    avoid the Python 3.14 dataclass-introspection issue
    (``_process_class`` reads ``sys.modules[cls.__module__]``).
    """
    assert HELPER_PATH.exists(), f"helper missing: {HELPER_PATH}"
    mod_name = "verify_g1_g2_last_mile_checklist_doc"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, HELPER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cli_json_envelope() -> dict:
    """Run the verifier CLI in --json mode and parse the envelope."""
    proc = subprocess.run(
        [sys.executable, str(HELPER_PATH), "--json"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"helper CLI returned {proc.returncode}: stderr={proc.stderr}"
    )
    return json.loads(proc.stdout)


# --------------------------------------------------------------------
# 1. Helper module imports clean
# --------------------------------------------------------------------


def test_01_helper_module_imports_clean(helper_module):
    assert hasattr(helper_module, "run_verify")
    assert hasattr(helper_module, "main")
    assert hasattr(helper_module, "LastMileReport")
    assert hasattr(helper_module, "StageProbe")


# --------------------------------------------------------------------
# 2. Helper exposes stage-class constants
# --------------------------------------------------------------------


def test_02_helper_exposes_stage_class_constants(helper_module):
    assert helper_module.EVE_CHECKS == tuple(f"E{i}" for i in range(1, 13))
    assert helper_module.T0_STEPS == tuple(f"T0.{i}" for i in range(10))
    assert helper_module.G1_WAVES == tuple(f"G1.W{i}" for i in range(1, 5))
    assert helper_module.G2_SUBSTEPS == tuple(f"G2.S{i}" for i in range(1, 4))
    assert helper_module.VERIFICATION_PROBES == tuple(
        f"V{i}" for i in range(1, 7)
    )
    assert helper_module.FAILURE_TRIGGERS == tuple(f"F{i}" for i in range(1, 6))
    assert helper_module.REQUIRED_SECTION_IDS == tuple(
        f"§{i}" for i in range(1, 9)
    )


# --------------------------------------------------------------------
# 3. Helper CLI exits 0 on current doc
# --------------------------------------------------------------------


def test_03_helper_cli_exits_0_on_current_doc():
    proc = subprocess.run(
        [sys.executable, str(HELPER_PATH)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"helper exited {proc.returncode}: stdout={proc.stdout} "
        f"stderr={proc.stderr}"
    )
    assert "LAST-MILE-CLEAN" in proc.stdout


# --------------------------------------------------------------------
# 4. Helper JSON envelope is parseable
# --------------------------------------------------------------------


def test_04_helper_emits_parseable_json_envelope(cli_json_envelope):
    env = cli_json_envelope
    assert env["verdict"] == "LAST-MILE-CLEAN"
    assert "counts" in env
    assert "probes" in env
    assert "cross_ref_misses" in env


# --------------------------------------------------------------------
# 5. Helper JSON envelope carries 40 probes
# --------------------------------------------------------------------


def test_05_helper_envelope_has_40_probes(cli_json_envelope):
    probes = cli_json_envelope["probes"]
    # 12 Eve + 10 T0 + 4 G1 waves + 3 G2 sub-steps + 6 V + 5 F = 40.
    assert len(probes) == 40, f"expected 40 probes, got {len(probes)}"
    assert cli_json_envelope["counts"]["TOTAL"] == 40
    assert cli_json_envelope["counts"]["PASS"] == 40
    assert cli_json_envelope["counts"]["DRIFT"] == 0
    assert cli_json_envelope["counts"]["DEFECT"] == 0


# --------------------------------------------------------------------
# 6. Every Eve-Check probe lands PASS
# --------------------------------------------------------------------


def test_06_all_eve_check_probes_pass(cli_json_envelope, helper_module):
    eve_probes = [
        p for p in cli_json_envelope["probes"] if p["stage_class"] == "EVE"
    ]
    assert len(eve_probes) == 12
    seen_ids = {p["stage_id"] for p in eve_probes}
    assert seen_ids == set(helper_module.EVE_CHECKS)
    for p in eve_probes:
        assert p["status"] == "PASS", (
            f"Eve-Check {p['stage_id']} not PASS: {p['detail']}"
        )


# --------------------------------------------------------------------
# 7. Every T0-step probe lands PASS
# --------------------------------------------------------------------


def test_07_all_t0_step_probes_pass(cli_json_envelope, helper_module):
    t0_probes = [
        p for p in cli_json_envelope["probes"] if p["stage_class"] == "T0"
    ]
    assert len(t0_probes) == 10
    seen_ids = {p["stage_id"] for p in t0_probes}
    assert seen_ids == set(helper_module.T0_STEPS)
    for p in t0_probes:
        assert p["status"] == "PASS", (
            f"T0-step {p['stage_id']} not PASS: {p['detail']}"
        )


# --------------------------------------------------------------------
# 8. Every G1 wave probe lands PASS
# --------------------------------------------------------------------


def test_08_all_g1_wave_probes_pass(cli_json_envelope, helper_module):
    g1_probes = [
        p for p in cli_json_envelope["probes"] if p["stage_class"] == "G1"
    ]
    assert len(g1_probes) == 4
    seen_ids = {p["stage_id"] for p in g1_probes}
    assert seen_ids == set(helper_module.G1_WAVES)
    for p in g1_probes:
        assert p["status"] == "PASS", (
            f"G1 wave {p['stage_id']} not PASS: {p['detail']}"
        )


# --------------------------------------------------------------------
# 9. Every G2 sub-step probe lands PASS
# --------------------------------------------------------------------


def test_09_all_g2_substep_probes_pass(cli_json_envelope, helper_module):
    g2_probes = [
        p for p in cli_json_envelope["probes"] if p["stage_class"] == "G2"
    ]
    assert len(g2_probes) == 3
    seen_ids = {p["stage_id"] for p in g2_probes}
    assert seen_ids == set(helper_module.G2_SUBSTEPS)
    for p in g2_probes:
        assert p["status"] == "PASS", (
            f"G2 sub-step {p['stage_id']} not PASS: {p['detail']}"
        )


# --------------------------------------------------------------------
# 10. Every verification probe lands PASS
# --------------------------------------------------------------------


def test_10_all_verification_probes_pass(cli_json_envelope, helper_module):
    v_probes = [
        p for p in cli_json_envelope["probes"] if p["stage_class"] == "V"
    ]
    assert len(v_probes) == 6
    seen_ids = {p["stage_id"] for p in v_probes}
    assert seen_ids == set(helper_module.VERIFICATION_PROBES)
    for p in v_probes:
        assert p["status"] == "PASS", (
            f"Verification {p['stage_id']} not PASS: {p['detail']}"
        )


# --------------------------------------------------------------------
# 11. Every failure-recovery trigger lands PASS
# --------------------------------------------------------------------


def test_11_all_failure_trigger_probes_pass(cli_json_envelope, helper_module):
    f_probes = [
        p for p in cli_json_envelope["probes"] if p["stage_class"] == "F"
    ]
    assert len(f_probes) == 5
    seen_ids = {p["stage_id"] for p in f_probes}
    assert seen_ids == set(helper_module.FAILURE_TRIGGERS)
    for p in f_probes:
        assert p["status"] == "PASS", (
            f"Failure {p['stage_id']} not PASS: {p['detail']}"
        )


# --------------------------------------------------------------------
# 12. All §8.1 cross-reference paths resolve on disk
# --------------------------------------------------------------------


def test_12_all_cross_reference_paths_resolve(cli_json_envelope, helper_module):
    assert cli_json_envelope["cross_ref_misses"] == []
    misses = helper_module.probe_cross_refs(REPO_ROOT)
    assert misses == [], f"unexpected cross-ref misses: {misses}"


# --------------------------------------------------------------------
# 13. Helper flips to DEFECT when doc is missing
# --------------------------------------------------------------------


def test_13_helper_flips_to_defect_when_doc_missing(tmp_path, helper_module):
    empty_root = tmp_path / "empty-repo"
    (empty_root / "docs" / "operations").mkdir(parents=True)
    # No doc on disk -> run_verify must report DEFECT.
    report = helper_module.run_verify(empty_root)
    assert report.verdict == "LAST-MILE-DEFECT"
    assert any("doc not found" in n for n in report.notes)


# --------------------------------------------------------------------
# 14. Helper flips to DRIFT on a corrupted Eve-Check fixture
# --------------------------------------------------------------------


def test_14_helper_flips_to_drift_on_corrupted_eve_check(tmp_path, helper_module):
    """Build a minimum-viable fixture missing one required field in E1."""
    fake_root = tmp_path / "fake-repo"
    op_dir = fake_root / "docs" / "operations"
    op_dir.mkdir(parents=True)

    # Copy the real doc into the fixture, then corrupt the E1 block by
    # removing the **Verdict-Marker** label line.
    real = DOC_PATH.read_text(encoding="utf-8")
    corrupted = real.replace(
        "- **Verdict-Marker**: `EVE-E1-COSIGN-READY` / `EVE-E1-HOLD`.",
        "- VERDICT-MARKER-LABEL-REMOVED-FOR-FIXTURE-TEST.",
        1,
    )
    assert corrupted != real, "fixture corruption no-op (label not found?)"
    (op_dir / "g1-g2-last-mile-operator-checklist.md").write_text(
        corrupted, encoding="utf-8"
    )

    # Materialise cross-ref targets so CROSS_REF_MISSES stays 0; isolate
    # DRIFT to the corrupted-field path.
    for rel in helper_module.CROSS_REF_PATHS:
        p = fake_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# fixture stub\n", encoding="utf-8")

    report = helper_module.run_verify(fake_root)
    assert report.verdict == "LAST-MILE-DRIFT", (
        f"expected DRIFT, got {report.verdict}; notes={report.notes}"
    )
    drift_probes = [p for p in report.probes if p.status == "DRIFT"]
    assert len(drift_probes) == 1
    assert drift_probes[0].stage_id == "E1"
    assert "**Verdict-Marker**" in drift_probes[0].detail


# --------------------------------------------------------------------
# 15. Helper is hermetic (no network-I/O imports)
# --------------------------------------------------------------------


def test_15_helper_is_hermetic_no_network_imports():
    """Source-level surface check: the verifier does not import network
    I/O modules (socket, urllib, http.client, requests, httpx).
    """
    src = HELPER_PATH.read_text(encoding="utf-8")
    forbidden = ("socket", "urllib", "http.client", "requests", "httpx")
    import_lines = [
        line
        for line in src.splitlines()
        if line.startswith("import ") or line.startswith("from ")
    ]
    for line in import_lines:
        for token in forbidden:
            assert token not in line, (
                f"hermetic-violation: helper imports network module "
                f"'{token}': {line}"
            )
