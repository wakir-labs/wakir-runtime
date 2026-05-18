# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/persona-engine/legacy-env-flag-migration-detector.py
— Tag-51.

Hermetic, stdlib-only. The detector is loaded via importlib from its
hyphenated path under ``scripts/persona-engine/``. Repo-scan tests
use ``tmp_path``-backed fixtures; the spec-text cross-check test
reads the in-tree ``wirelang/specs/wirelang-spec-v0-4-2.md`` to
catch silent drift between the script's MIGRATION_MAPPING table and
Spec v0.4.2 §6.

Scope (14 tests, ≥ 12 requested)
--------------------------------

1.  test_module_loads_and_self_test_passes
2.  test_mapping_has_nine_entries_matching_spec_v0_4_2_section_6
3.  test_mapping_canonical_names_have_no_pe_infix
4.  test_mapping_includes_bridge_audit_multi_target
5.  test_mapping_canonical_form_is_removed_without_successor
6.  test_scan_repo_detects_legacy_flag_in_fixture
7.  test_scan_repo_emits_multi_finding_per_file
8.  test_scan_repo_detects_unknown_prefix_form
9.  test_scan_repo_respects_default_excludes
10. test_scan_repo_include_spec_files_overrides_excludes
11. test_scan_repo_empty_tree_yields_no_findings
12. test_build_report_shape_is_stable_and_sorted
13. test_cli_writes_out_file_and_returns_exit_codes
14. test_cli_quiet_suppresses_stderr_deprecation_warning
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


# ----------------------------------------------------------------------
# Module loading (hyphenated script path)
# ----------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DETECTOR_PATH = (
    REPO_ROOT
    / "scripts"
    / "persona-engine"
    / "legacy-env-flag-migration-detector.py"
)


def _load_detector():
    """Load the hyphenated detector module via importlib."""
    spec = importlib.util.spec_from_file_location(
        "legacy_env_flag_migration_detector", DETECTOR_PATH
    )
    assert spec is not None, "spec_from_file_location returned None"
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses can resolve cls.__module__.
    sys.modules[spec.name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def detector():
    return _load_detector()


# ----------------------------------------------------------------------
# 1. Module + self-test
# ----------------------------------------------------------------------


def test_module_loads_and_self_test_passes(detector):
    ok, errors = detector.self_test()
    assert ok, f"detector self-test failed: {errors}"
    # Public surface sanity:
    assert hasattr(detector, "MIGRATION_MAPPING")
    assert hasattr(detector, "DEFAULT_EXCLUDES")
    assert hasattr(detector, "LEGACY_PREFIX_RE")
    assert hasattr(detector, "scan_repo")
    assert hasattr(detector, "scan_file")
    assert hasattr(detector, "build_report")
    assert callable(detector.main)


# ----------------------------------------------------------------------
# 2-5. Mapping invariants vs. Spec v0.4.2 §6
# ----------------------------------------------------------------------


def test_mapping_has_nine_entries_matching_spec_v0_4_2_section_6(detector):
    """Mapping has exactly 9 keys, all of which also appear in the
    in-tree v0.4.2 spec §6 deprecation table (left column)."""
    mapping = detector.MIGRATION_MAPPING
    assert len(mapping) == 9, (
        f"Spec v0.4.2 §6 table has 9 rows; mapping has {len(mapping)}"
    )

    spec_path = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-2.md"
    text = spec_path.read_text(encoding="utf-8")
    for legacy in mapping:
        assert legacy in text, (
            f"legacy name {legacy!r} declared by detector but not "
            f"present in Spec v0.4.2 file"
        )


def test_mapping_canonical_names_have_no_pe_infix(detector):
    """No canonical name retains the legacy ``WAKIR_PE_`` infix."""
    for legacy, entry in detector.MIGRATION_MAPPING.items():
        canonical = entry["canonical"]
        if canonical is None:
            continue
        targets = (
            [canonical] if isinstance(canonical, str) else list(canonical)
        )
        for t in targets:
            assert "WAKIR_PE_" not in t, (
                f"canonical for {legacy!r} retains legacy infix: {t!r}"
            )
            assert t.startswith("WAKIR_"), t
            assert t.endswith("_BACKEND"), t


def test_mapping_includes_bridge_audit_multi_target(detector):
    """Bridge-audit deprecates to writer + diff-companion (two flags)."""
    entry = detector.MIGRATION_MAPPING["WAKIR_PE_BRIDGE_AUDIT_BACKEND"]
    canonical = entry["canonical"]
    assert isinstance(canonical, list), (
        "bridge-audit canonical must be a list (writer + diff)"
    )
    assert "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND" in canonical
    assert "WAKIR_BRIDGE_DIFF_BACKEND" in canonical


def test_mapping_canonical_form_is_removed_without_successor(detector):
    """canonical_form has no v0.4.2 successor (§4.1 FN-1)."""
    entry = detector.MIGRATION_MAPPING["WAKIR_PE_CANONICAL_FORM_BACKEND"]
    assert entry["canonical"] is None, (
        "canonical_form must be removed (None) per Spec v0.4.2 §4.1 FN-1"
    )
    # The classify() function maps None to mapping_status='removed'.
    status, canonical, _ = detector._classify(
        "WAKIR_PE_CANONICAL_FORM_BACKEND"
    )
    assert status == "removed"
    assert canonical is None


# ----------------------------------------------------------------------
# 6. Scan picks up a single fixture occurrence
# ----------------------------------------------------------------------


def test_scan_repo_detects_legacy_flag_in_fixture(detector, tmp_path):
    f = tmp_path / "operator.env"
    f.write_text(
        "# operator-local Quadlet drop-in\n"
        "WAKIR_PE_V907_BACKEND=rust\n",
        encoding="utf-8",
    )
    findings = detector.scan_repo(tmp_path, excludes=[])
    assert len(findings) == 1
    f0 = findings[0]
    assert f0.legacy_flag == "WAKIR_PE_V907_BACKEND"
    assert f0.line == 2
    assert f0.column == 1
    assert f0.mapping_status == "mapped"
    assert f0.canonical == "WAKIR_V907_VERIFY_BACKEND"


# ----------------------------------------------------------------------
# 7. Multiple findings per file (multi-occurrence, line ordering)
# ----------------------------------------------------------------------


def test_scan_repo_emits_multi_finding_per_file(detector, tmp_path):
    f = tmp_path / "shell.sh"
    f.write_text(
        "#!/bin/sh\n"
        "export WAKIR_PE_V907_BACKEND=rust\n"
        "export WAKIR_PE_SVID_BACKEND=python\n"
        "export WAKIR_PE_FSM_BACKEND=rust  # WAKIR_PE_FSM_BACKEND too\n",
        encoding="utf-8",
    )
    findings = detector.scan_repo(tmp_path, excludes=[])
    # 1 each on lines 2, 3; 2 on line 4 (export + comment) = 4 total
    assert len(findings) == 4
    # Findings ordered by (file, line, column).
    lines = [f.line for f in findings]
    assert lines == sorted(lines)
    flags = [f.legacy_flag for f in findings]
    assert flags.count("WAKIR_PE_FSM_BACKEND") == 2


# ----------------------------------------------------------------------
# 8. Unknown WAKIR_PE_* form classified as "unknown-prefix"
# ----------------------------------------------------------------------


def test_scan_repo_detects_unknown_prefix_form(detector, tmp_path):
    f = tmp_path / "future.yml"
    f.write_text(
        "env:\n  WAKIR_PE_FUTURE_FEATURE_BACKEND: rust\n",
        encoding="utf-8",
    )
    findings = detector.scan_repo(tmp_path, excludes=[])
    assert len(findings) == 1
    assert findings[0].legacy_flag == "WAKIR_PE_FUTURE_FEATURE_BACKEND"
    assert findings[0].mapping_status == "unknown-prefix"
    assert findings[0].canonical is None


# ----------------------------------------------------------------------
# 9. Default excludes prune spec/test/detector paths
# ----------------------------------------------------------------------


def test_scan_repo_respects_default_excludes(detector, tmp_path):
    # Mimic the repo-internal "legitimate occurrence" locations.
    spec_dir = tmp_path / "wirelang" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "wirelang-spec-v0-4-2.md").write_text(
        "Operator migration: WAKIR_PE_V907_BACKEND -> "
        "WAKIR_V907_VERIFY_BACKEND.\n",
        encoding="utf-8",
    )
    tests_specs = tmp_path / "tests" / "specs"
    tests_specs.mkdir(parents=True)
    (tests_specs / "test_wirelang_spec_v0_4_2_drift.py").write_text(
        '"""WAKIR_PE_FSM_BACKEND drift test."""\n',
        encoding="utf-8",
    )
    # Operator-side file that should still surface:
    (tmp_path / "operator.env").write_text(
        "WAKIR_PE_FSM_BACKEND=rust\n", encoding="utf-8"
    )
    findings = detector.scan_repo(tmp_path, excludes=detector.DEFAULT_EXCLUDES)
    paths = {f.path for f in findings}
    assert paths == {"operator.env"}, (
        f"default-excludes leaked spec/test occurrences: {paths}"
    )


# ----------------------------------------------------------------------
# 10. --include-spec-files surfaces excluded paths
# ----------------------------------------------------------------------


def test_scan_repo_include_spec_files_overrides_excludes(detector, tmp_path):
    spec_dir = tmp_path / "wirelang" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "wirelang-spec-v0-4-2.md").write_text(
        "row: WAKIR_PE_SVID_BACKEND -> WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND\n",
        encoding="utf-8",
    )
    # Passing an empty excludes list = "scan everything".
    findings_full = detector.scan_repo(tmp_path, excludes=[])
    paths_full = {f.path for f in findings_full}
    assert "wirelang/specs/wirelang-spec-v0-4-2.md" in paths_full


# ----------------------------------------------------------------------
# 11. Empty tree -> no findings, no crashes
# ----------------------------------------------------------------------


def test_scan_repo_empty_tree_yields_no_findings(detector, tmp_path):
    findings = detector.scan_repo(tmp_path, excludes=[])
    assert findings == []
    report = detector.build_report(findings, tmp_path, include_spec_files=False)
    assert report["total_findings"] == 0
    assert report["per_flag"] == {}
    assert report["per_path"] == {}
    # Mapping is still embedded for downstream consumers.
    assert len(report["mapping"]) == 9


# ----------------------------------------------------------------------
# 12. Report shape stable + sorted
# ----------------------------------------------------------------------


def test_build_report_shape_is_stable_and_sorted(detector, tmp_path):
    (tmp_path / "b.env").write_text(
        "WAKIR_PE_FSM_BACKEND=rust\n", encoding="utf-8"
    )
    (tmp_path / "a.env").write_text(
        "WAKIR_PE_V907_BACKEND=rust\n"
        "WAKIR_PE_RECOVERY_BACKEND=python\n",
        encoding="utf-8",
    )
    findings = detector.scan_repo(tmp_path, excludes=[])
    report = detector.build_report(
        findings, tmp_path, include_spec_files=False
    )
    # Per-path keys sorted.
    assert list(report["per_path"].keys()) == ["a.env", "b.env"]
    # Per-flag keys sorted.
    assert list(report["per_flag"].keys()) == sorted(report["per_flag"].keys())
    # Total = sum of per-path.
    assert report["total_findings"] == sum(report["per_path"].values())
    # Mapping pinned to 9.
    assert set(report["mapping"]) == set(detector.MIGRATION_MAPPING)
    # JSON-roundtrip-safe (no non-serialisable values).
    blob = json.dumps(report)
    assert "WAKIR_V907_VERIFY_BACKEND" in blob


# ----------------------------------------------------------------------
# 13. CLI writes JSON file and tri-state exits correctly
# ----------------------------------------------------------------------


def test_cli_writes_out_file_and_returns_exit_codes(detector, tmp_path):
    work = tmp_path / "repo"
    work.mkdir()
    (work / "operator.env").write_text(
        "WAKIR_PE_FSM_BACKEND=rust\n", encoding="utf-8"
    )
    out_findings = tmp_path / "report-findings.json"
    rc_findings = detector.main(
        [
            "--root",
            str(work),
            "--out",
            str(out_findings),
            "--include-spec-files",  # scan everything in fixture repo
            "--quiet",
        ]
    )
    assert rc_findings == 1, (
        "exit code 1 expected on findings without --fail-on-find"
    )
    assert out_findings.exists()
    d = json.loads(out_findings.read_text(encoding="utf-8"))
    assert d["total_findings"] == 1

    # --fail-on-find escalates to exit 2.
    out_fail = tmp_path / "report-fail.json"
    rc_fail = detector.main(
        [
            "--root",
            str(work),
            "--out",
            str(out_fail),
            "--include-spec-files",
            "--quiet",
            "--fail-on-find",
        ]
    )
    assert rc_fail == 2

    # Clean tree -> exit 0.
    empty = tmp_path / "empty"
    empty.mkdir()
    out_clean = tmp_path / "report-clean.json"
    rc_clean = detector.main(
        ["--root", str(empty), "--out", str(out_clean), "--quiet"]
    )
    assert rc_clean == 0


# ----------------------------------------------------------------------
# 14. --quiet suppresses deprecation-warning summary
# ----------------------------------------------------------------------


def test_cli_quiet_suppresses_stderr_deprecation_warning(tmp_path):
    work = tmp_path / "repo"
    work.mkdir()
    (work / "operator.env").write_text(
        "WAKIR_PE_FSM_BACKEND=rust\n", encoding="utf-8"
    )
    out_json = tmp_path / "r.json"

    # Run as subprocess so we can capture stderr distinctly.
    cmd_quiet = [
        sys.executable,
        str(DETECTOR_PATH),
        "--root",
        str(work),
        "--out",
        str(out_json),
        "--include-spec-files",
        "--quiet",
    ]
    proc_quiet = subprocess.run(cmd_quiet, capture_output=True, text=True)
    assert proc_quiet.returncode == 1
    assert "DeprecationWarning" not in proc_quiet.stderr

    cmd_loud = [
        sys.executable,
        str(DETECTOR_PATH),
        "--root",
        str(work),
        "--out",
        str(out_json),
        "--include-spec-files",
    ]
    proc_loud = subprocess.run(cmd_loud, capture_output=True, text=True)
    assert proc_loud.returncode == 1
    assert "DeprecationWarning" in proc_loud.stderr
    assert "Spec v0.4.2 §6" in proc_loud.stderr
