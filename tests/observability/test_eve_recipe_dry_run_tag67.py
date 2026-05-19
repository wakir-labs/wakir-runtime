# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Tag-67 hermetic Dry-Run-Probe test-suite for the Tag-66 Operator-Hand
Cutover-Eve Final-Recipe.

Substance brief (>= 12 tests, suite carries 14):

  1. Helper module imports clean (no side-effects on import).
  2. Helper exposes the documented stage-class constants
     (EVE_CHECKS, T0_STEPS, WELLE_DAYS, ROLLBACK_PATHS, AR_TOUCHPOINTS).
  3. Helper CLI exits 0 on the current on-disk Tag-66 doc.
  4. Helper emits a parseable JSON envelope under --json.
  5. Helper JSON envelope carries 39 stage probes (12+10+6+5+6).
  6. Every Eve-Check (E1..E12) probe lands PASS on the current doc.
  7. Every T0-step (T0.0..T0.9) probe lands PASS.
  8. Every Welle-Day (T0+1..T0+6) probe lands PASS.
  9. Every Rollback (R1..R5) probe lands PASS.
 10. Every AR-Touchpoint (TP1..TP6) probe lands PASS.
 11. All §7 cross-reference paths resolve on disk (no misses).
 12. Helper flips to DEFECT when the doc is missing (synthetic fixture).
 13. Helper flips to DRIFT when an Eve-Check loses a required field
     (synthetic fixture, hermetic — no real doc mutated).
 14. Helper is hermetic: it does NOT import socket/urllib/subprocess
     for any network I/O code path (module-level surface check).

This suite is hermetic: zero network, zero podman, zero gh api. All
fixtures are synthesised in-memory and written to a tmp_path.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "dry_run_operator_eve_recipe.py"
DOC_PATH = (
    REPO_ROOT / "docs" / "operations" / "operator-hand-cutover-eve-final-recipe.md"
)

# Make tooling/ci importable for direct-API tests.
sys.path.insert(0, str(REPO_ROOT / "tooling" / "ci"))


@pytest.fixture(scope="module")
def helper_module():
    """Import the helper as a Python module for in-process probing.

    We register the module in ``sys.modules`` before ``exec_module``
    because the helper uses ``@dataclass``, and dataclass introspection
    in Python 3.14 reads ``sys.modules[cls.__module__]`` during
    ``_process_class`` (Python 3.14 dataclasses internal change).
    """
    assert HELPER_PATH.exists(), f"helper missing: {HELPER_PATH}"
    mod_name = "dry_run_operator_eve_recipe"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, HELPER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cli_json_envelope() -> dict:
    """Run the helper CLI in --json mode and parse the envelope."""
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
    assert hasattr(helper_module, "run_dry_run")
    assert hasattr(helper_module, "main")
    assert hasattr(helper_module, "DryRunReport")


# --------------------------------------------------------------------
# 2. Helper exposes stage-class constants
# --------------------------------------------------------------------


def test_02_helper_exposes_stage_class_constants(helper_module):
    assert helper_module.EVE_CHECKS == tuple(f"E{i}" for i in range(1, 13))
    assert helper_module.T0_STEPS == tuple(f"T0.{i}" for i in range(10))
    assert helper_module.WELLE_DAYS == tuple(f"T0+{i}" for i in range(1, 7))
    assert helper_module.ROLLBACK_PATHS == tuple(f"R{i}" for i in range(1, 6))
    assert helper_module.AR_TOUCHPOINTS == tuple(f"TP{i}" for i in range(1, 7))


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
        f"helper exited {proc.returncode}: stdout={proc.stdout} stderr={proc.stderr}"
    )
    assert "EVE-DRY-RUN-CLEAN" in proc.stdout


# --------------------------------------------------------------------
# 4. Helper JSON envelope is parseable
# --------------------------------------------------------------------


def test_04_helper_emits_parseable_json_envelope(cli_json_envelope):
    env = cli_json_envelope
    assert env["verdict"] == "EVE-DRY-RUN-CLEAN"
    assert "counts" in env
    assert "probes" in env
    assert "cross_ref_misses" in env


# --------------------------------------------------------------------
# 5. Helper JSON envelope carries 39 probes
# --------------------------------------------------------------------


def test_05_helper_envelope_has_39_probes(cli_json_envelope):
    probes = cli_json_envelope["probes"]
    # 12 Eve + 10 T0 + 6 Welle + 5 Rollback + 6 AR-TP = 39
    assert len(probes) == 39, f"expected 39 probes, got {len(probes)}"
    assert cli_json_envelope["counts"]["TOTAL"] == 39
    assert cli_json_envelope["counts"]["PASS"] == 39


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
    t0_probes = [p for p in cli_json_envelope["probes"] if p["stage_class"] == "T0"]
    assert len(t0_probes) == 10
    seen_ids = {p["stage_id"] for p in t0_probes}
    assert seen_ids == set(helper_module.T0_STEPS)
    for p in t0_probes:
        assert p["status"] == "PASS", (
            f"T0-step {p['stage_id']} not PASS: {p['detail']}"
        )


# --------------------------------------------------------------------
# 8. Every Welle-Day probe lands PASS
# --------------------------------------------------------------------


def test_08_all_welle_day_probes_pass(cli_json_envelope, helper_module):
    welle_probes = [
        p for p in cli_json_envelope["probes"] if p["stage_class"] == "WELLE"
    ]
    assert len(welle_probes) == 6
    seen_ids = {p["stage_id"] for p in welle_probes}
    assert seen_ids == set(helper_module.WELLE_DAYS)
    for p in welle_probes:
        assert p["status"] == "PASS", (
            f"Welle-Day {p['stage_id']} not PASS: {p['detail']}"
        )


# --------------------------------------------------------------------
# 9. Every Rollback probe lands PASS
# --------------------------------------------------------------------


def test_09_all_rollback_probes_pass(cli_json_envelope, helper_module):
    rb_probes = [
        p for p in cli_json_envelope["probes"] if p["stage_class"] == "ROLLBACK"
    ]
    assert len(rb_probes) == 5
    seen_ids = {p["stage_id"] for p in rb_probes}
    assert seen_ids == set(helper_module.ROLLBACK_PATHS)
    for p in rb_probes:
        assert p["status"] == "PASS", (
            f"Rollback {p['stage_id']} not PASS: {p['detail']}"
        )


# --------------------------------------------------------------------
# 10. Every AR-Touchpoint probe lands PASS
# --------------------------------------------------------------------


def test_10_all_ar_touchpoint_probes_pass(cli_json_envelope, helper_module):
    tp_probes = [
        p for p in cli_json_envelope["probes"] if p["stage_class"] == "AR-TP"
    ]
    assert len(tp_probes) == 6
    seen_ids = {p["stage_id"] for p in tp_probes}
    assert seen_ids == set(helper_module.AR_TOUCHPOINTS)
    for p in tp_probes:
        assert p["status"] == "PASS", (
            f"AR-Touchpoint {p['stage_id']} not PASS: {p['detail']}"
        )


# --------------------------------------------------------------------
# 11. All §7 cross-reference paths resolve on disk
# --------------------------------------------------------------------


def test_11_all_cross_reference_paths_resolve(cli_json_envelope, helper_module):
    assert cli_json_envelope["cross_ref_misses"] == []
    # Sanity-check: probe_cross_refs returns [] for the live repo root.
    misses = helper_module.probe_cross_refs(REPO_ROOT)
    assert misses == [], f"unexpected cross-ref misses: {misses}"


# --------------------------------------------------------------------
# 12. Helper flips to DEFECT when doc is missing
# --------------------------------------------------------------------


def test_12_helper_flips_to_defect_when_doc_missing(tmp_path, helper_module):
    # Build an empty repo root with no doc.
    empty_root = tmp_path / "empty-repo"
    (empty_root / "docs" / "operations").mkdir(parents=True)
    # No file written → run_dry_run must report DEFECT.
    report = helper_module.run_dry_run(empty_root)
    assert report.verdict == "EVE-DRY-RUN-DEFECT"
    assert any("doc not found" in n for n in report.notes)


# --------------------------------------------------------------------
# 13. Helper flips to DRIFT on a corrupted Eve-Check fixture
# --------------------------------------------------------------------


def test_13_helper_flips_to_drift_on_corrupted_eve_check(tmp_path, helper_module):
    """Build a minimum-viable fixture missing one required field in E1."""
    fake_root = tmp_path / "fake-repo"
    op_dir = fake_root / "docs" / "operations"
    op_dir.mkdir(parents=True)

    # Copy the real doc into the fixture, then corrupt the E1 block by
    # removing the **Verdict-Marker** label line.
    real = DOC_PATH.read_text(encoding="utf-8")
    corrupted = real.replace(
        "- **Verdict-Marker**: `EVE-E1-READY` / `EVE-E1-HOLD`.",
        "- VERDICT-MARKER-LABEL-REMOVED-FOR-FIXTURE-TEST.",
        1,
    )
    assert corrupted != real, "fixture corruption no-op (label not found?)"
    (op_dir / "operator-hand-cutover-eve-final-recipe.md").write_text(
        corrupted, encoding="utf-8"
    )

    # Materialise cross-ref targets so CROSS_REF_MISSES stays 0 and we
    # can isolate the DRIFT verdict to the corrupted-field path.
    for rel in helper_module.CROSS_REF_PATHS:
        p = fake_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# fixture stub\n", encoding="utf-8")

    report = helper_module.run_dry_run(fake_root)
    assert report.verdict == "EVE-DRY-RUN-DRIFT", (
        f"expected DRIFT, got {report.verdict}; notes={report.notes}"
    )
    # Exactly one DRIFT probe, on E1, citing the missing Verdict-Marker.
    drift_probes = [p for p in report.probes if p.status == "DRIFT"]
    assert len(drift_probes) == 1
    assert drift_probes[0].stage_id == "E1"
    assert "**Verdict-Marker**" in drift_probes[0].detail


# --------------------------------------------------------------------
# 14. Helper is hermetic (no network-I/O imports in module body)
# --------------------------------------------------------------------


def test_14_helper_is_hermetic_no_network_imports():
    """Source-level surface check: the helper does not import network I/O
    modules (socket, urllib, http, requests, httpx) for any code path.
    """
    src = HELPER_PATH.read_text(encoding="utf-8")
    # Only inspect import lines, not comments / docstrings.
    forbidden = ("socket", "urllib", "http.client", "requests", "httpx")
    import_lines = [
        line
        for line in src.splitlines()
        if line.startswith("import ") or line.startswith("from ")
    ]
    for line in import_lines:
        for token in forbidden:
            assert token not in line, (
                f"hermetic-violation: helper imports network module '{token}': {line}"
            )
