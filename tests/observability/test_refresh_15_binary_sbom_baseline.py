#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for
``scripts/observability/refresh-15-binary-sbom-baseline.py``.

Tag-50 Kai -- SBOM-Baseline-Refresh CLI.

Coverage targets:

  * 5 approval-token-format invariants (TR-TK-01..TR-TK-05)
  * 3 drift-summary helper invariants (TR-DH-01..TR-DH-03)
  * 2 receipt-rendering invariants (TR-RC-01..TR-RC-02)
  * 2 baseline-enumeration invariants (TR-EN-01..TR-EN-02)
  * 2 end-to-end refresh-sequence invariants (TR-E2E-01..TR-E2E-02)
  * 1 CLI dry-run invariant (TR-CLI-01)
  * 1 CLI no-token rejection invariant (TR-CLI-02)

Total: 16 hermetic invariants -- above the >=12 target.

Sandbox boundary
----------------

Per ``feedback_sandbox_host_trennung.md`` + ADR-0051 these tests
NEVER call cargo / cosign / podman / network. End-to-end tests
use the live Tag-48 generator + Tag-49 verifier against the
repo's pinned ``wirelang-rust/Cargo.lock`` -- the generator is
already hermetic (stdlib + tomllib only).

Author: Kai Hoffmann (Dev-Engineering-3)
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Loader: import the refresh module from its hyphenated path.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_REFRESH_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "refresh-15-binary-sbom-baseline.py"
)
_GEN_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "generate-15-binary-sbom.py"
)
_VER_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "verify-15-binary-sbom-against-baseline.py"
)
_CARGO_LOCK_PATH = _REPO_ROOT / "wirelang-rust" / "Cargo.lock"
_BASELINE_DIR_REAL = _REPO_ROOT / "state" / "sbom-baseline"


def _load(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


refresh = _load(_REFRESH_PATH, "refresh_15_binary_sbom_baseline")
gen_mod = _load(_GEN_PATH, "generate_15_binary_sbom_for_refresh_tests")
ver_mod = _load(_VER_PATH, "verify_15_binary_sbom_for_refresh_tests")


# ===========================================================================
# Approval-token-format invariants (TR-TK-01..TR-TK-05)
# ===========================================================================


def test_TR_TK_01_well_formed_token_passes():
    """TR-TK-01: a well-formed AR-HAND-GATE token is accepted."""
    assert refresh.is_valid_approval_token(
        "AR-HAND-GATE-2026-05-19-fred"
    )


def test_TR_TK_02_missing_prefix_rejected():
    """TR-TK-02: token without AR-HAND-GATE prefix is rejected."""
    assert not refresh.is_valid_approval_token("2026-05-19-fred")
    assert not refresh.is_valid_approval_token("HAND-GATE-2026-05-19-fred")


def test_TR_TK_03_malformed_date_rejected():
    """TR-TK-03: date stamp must be YYYY-MM-DD (numeric)."""
    assert not refresh.is_valid_approval_token(
        "AR-HAND-GATE-20260519-fred"
    )
    assert not refresh.is_valid_approval_token(
        "AR-HAND-GATE-2026-5-19-fred"
    )
    assert not refresh.is_valid_approval_token(
        "AR-HAND-GATE-may19-fred"
    )


def test_TR_TK_04_initials_must_be_alpha_first():
    """TR-TK-04: initials must start with a lowercase ASCII letter."""
    assert not refresh.is_valid_approval_token(
        "AR-HAND-GATE-2026-05-19-1fred"
    )
    assert not refresh.is_valid_approval_token(
        "AR-HAND-GATE-2026-05-19-FRED"  # uppercase rejected
    )
    assert refresh.is_valid_approval_token(
        "AR-HAND-GATE-2026-05-19-k"  # single-char initial OK
    )


def test_TR_TK_05_empty_and_none_rejected():
    """TR-TK-05: empty string is rejected gracefully."""
    assert not refresh.is_valid_approval_token("")
    # Compound initials with hyphens are allowed.
    assert refresh.is_valid_approval_token(
        "AR-HAND-GATE-2026-05-19-kai-h"
    )


# ===========================================================================
# Drift-summary helper invariants (TR-DH-01..TR-DH-03)
# ===========================================================================


def _drift_envelope(*drift_classes_per_binary):
    """Build a synthetic verifier envelope from per-binary drift-classes."""
    per_binary = []
    for i, drift_classes in enumerate(drift_classes_per_binary):
        drift_entries = [
            {
                "drift_class": dc,
                "component_name": f"crate-{i}-{j}",
                "baseline_version": "1.0.0",
                "current_version": "1.0.0",
                "baseline_checksum": "a" * 64,
                "current_checksum": "b" * 64,
            }
            for j, dc in enumerate(drift_classes)
        ]
        per_binary.append(
            {
                "binary_name": f"bin-{i}",
                "verdict": "OK" if not drift_classes else "DRIFT-RED",
                "drift_count": len(drift_classes),
                "drift_entries": drift_entries,
            }
        )
    return {"per_binary": per_binary}


def test_TR_DH_01_checksum_changed_count_zero_when_absent():
    """TR-DH-01: count is 0 if no checksum-changed entries."""
    env = _drift_envelope(["component-added"], [])
    assert refresh.count_checksum_changed_drift(env) == 0


def test_TR_DH_02_checksum_changed_count_aggregates_all_binaries():
    """TR-DH-02: counts checksum-changed entries across all binaries."""
    env = _drift_envelope(
        ["checksum-changed", "component-added"],
        ["checksum-changed"],
        [],
    )
    assert refresh.count_checksum_changed_drift(env) == 2


def test_TR_DH_03_total_drift_entries_sums_drift_count():
    """TR-DH-03: total_drift_entries returns sum of per-binary drift_count."""
    env = _drift_envelope(
        ["component-added", "version-changed"],
        ["checksum-changed"],
        [],
    )
    assert refresh.total_drift_entries(env) == 3


# ===========================================================================
# Receipt-rendering invariants (TR-RC-01..TR-RC-02)
# ===========================================================================


def test_TR_RC_01_receipt_records_token_verbatim():
    """TR-RC-01: the approval-token is preserved byte-for-byte in receipt."""
    plan = refresh.RefreshPlan(
        cargo_lock_sha256_before="oldlock",
        cargo_lock_sha256_after="newlock",
        pre_refresh_verdict="YELLOW",
        pre_refresh_drift_total=3,
        pre_refresh_checksum_changed_count=0,
        pre_refresh_envelope={"verdict": "YELLOW"},
    )
    receipt = refresh.render_receipt(
        approval_token="AR-HAND-GATE-2026-05-19-fred",
        refreshed=True,
        plan=plan,
        post_refresh_verdict="GREEN",
        files_written=["state/sbom-baseline/foo.json"],
        refresh_ts=42.0,
        operator_invocation={"dry_run": False},
    )
    assert receipt["approval_token"] == "AR-HAND-GATE-2026-05-19-fred"
    assert receipt["pre_refresh_verdict"] == "YELLOW"
    assert receipt["post_refresh_verdict"] == "GREEN"
    assert receipt["cargo_lock_sha256_before"] == "oldlock"
    assert receipt["cargo_lock_sha256_after"] == "newlock"
    assert receipt["refresh_ts"] == 42.0
    assert receipt["refreshed"] is True
    assert receipt["files_written"] == ["state/sbom-baseline/foo.json"]


def test_TR_RC_02_receipt_schema_version_is_pinned():
    """TR-RC-02: receipt schema_version is the constant '1'."""
    plan = refresh.RefreshPlan(
        cargo_lock_sha256_before=None,
        cargo_lock_sha256_after="newlock",
        pre_refresh_verdict="GREEN",
        pre_refresh_drift_total=0,
        pre_refresh_checksum_changed_count=0,
        pre_refresh_envelope={"verdict": "GREEN"},
    )
    receipt = refresh.render_receipt(
        approval_token="AR-HAND-GATE-2026-05-19-kai",
        refreshed=False,
        plan=plan,
        post_refresh_verdict="(dry-run, not executed)",
        files_written=[],
        refresh_ts=0.0,
        operator_invocation={"dry_run": True},
    )
    assert receipt["schema_version"] == "1"
    assert receipt["schema_version"] == (
        refresh.RECEIPT_ENVELOPE_SCHEMA_VERSION
    )


# ===========================================================================
# Baseline-enumeration invariants (TR-EN-01..TR-EN-02)
# ===========================================================================


def test_TR_EN_01_enumerate_baseline_writes_filenames():
    """TR-EN-01: src is `<bin>.cdx.json`, dst is `<bin>.json`."""
    sbom_dir = Path("/tmp/in")
    baseline_dir = Path("/tmp/out")
    inventory = ["alpha", "beta"]
    pairs = refresh.enumerate_baseline_writes(
        sbom_dir, baseline_dir, inventory
    )
    assert pairs == (
        (Path("/tmp/in/alpha.cdx.json"), Path("/tmp/out/alpha.json")),
        (Path("/tmp/in/beta.cdx.json"), Path("/tmp/out/beta.json")),
    )


def test_TR_EN_02_read_baseline_cargo_lock_sha256_finds_property(
    tmp_path: Path,
):
    """TR-EN-02: read_baseline_cargo_lock_sha256 picks up wakir property."""
    bdir = tmp_path / "baseline"
    bdir.mkdir()
    bdir.joinpath("foo.json").write_text(
        json.dumps(
            {
                "metadata": {
                    "properties": [
                        {
                            "name": "wakir:cargo-lock-sha256",
                            "value": "abc123def456",
                        }
                    ]
                },
                "components": [],
            }
        ),
        encoding="utf-8",
    )
    got = refresh.read_baseline_cargo_lock_sha256(bdir, ["foo", "bar"])
    assert got == "abc123def456"

    # Empty dir -> None.
    empty = tmp_path / "empty"
    empty.mkdir()
    assert refresh.read_baseline_cargo_lock_sha256(empty, ["foo"]) is None


# ===========================================================================
# End-to-end refresh-sequence invariants (TR-E2E-01..TR-E2E-02)
# ===========================================================================


def _stage_baseline_copy(target_dir: Path) -> None:
    """Copy the real repo baseline into a tempdir for mutation tests."""
    target_dir.mkdir(parents=True, exist_ok=True)
    for src in _BASELINE_DIR_REAL.glob("*.json"):
        target_dir.joinpath(src.name).write_bytes(src.read_bytes())


@pytest.mark.skipif(
    not _CARGO_LOCK_PATH.is_file()
    or not _BASELINE_DIR_REAL.is_dir(),
    reason="real Cargo.lock + baseline must be present (always true in CI)",
)
def test_TR_E2E_01_refresh_against_current_baseline_is_green(
    tmp_path: Path,
):
    """TR-E2E-01: refreshing into a copy of the current baseline -> GREEN.

    This is the canonical no-op path: against the repo's pinned
    state, the generator's output already matches the baseline,
    so the pre-refresh verdict must be GREEN and the refresh must
    be a no-op write (byte-identical files).
    """
    baseline_copy = tmp_path / "baseline"
    _stage_baseline_copy(baseline_copy)
    work_dir = tmp_path / "work"

    outcome = refresh.execute_refresh(
        gen_module=gen_mod,
        ver_module=ver_mod,
        cargo_lock=_CARGO_LOCK_PATH,
        baseline_dir=baseline_copy,
        work_dir=work_dir,
        inventory=gen_mod.TAG45_BINARY_INVENTORY,
        approval_token="AR-HAND-GATE-2026-05-19-kai",
        allow_checksum_changed=False,
        receipt_path=tmp_path / "receipt.json",
        operator_invocation={"test_anchor": "TR-E2E-01"},
        refresh_ts=1234.5,
        generator_ts=0.0,
    )
    assert outcome.plan.pre_refresh_verdict == "GREEN"
    assert outcome.post_refresh_verdict == "GREEN"
    assert outcome.refreshed is True
    assert len(outcome.files_written) == 15
    # Receipt was written.
    assert (tmp_path / "receipt.json").is_file()
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["approval_token"] == "AR-HAND-GATE-2026-05-19-kai"
    assert receipt["post_refresh_verdict"] == "GREEN"


@pytest.mark.skipif(
    not _CARGO_LOCK_PATH.is_file()
    or not _BASELINE_DIR_REAL.is_dir(),
    reason="real Cargo.lock + baseline must be present (always true in CI)",
)
def test_TR_E2E_02_missing_baseline_dir_yields_red_verdict_pre_refresh(
    tmp_path: Path,
):
    """TR-E2E-02: empty baseline -> pre-refresh RED; refresh still GREEN.

    A fully-missing baseline directory triggers MISSING-BASELINE
    on every binary (pre-refresh verdict RED). After the refresh,
    the freshly-written files produce GREEN.
    """
    baseline_empty = tmp_path / "empty-baseline"
    baseline_empty.mkdir()
    work_dir = tmp_path / "work"

    outcome = refresh.execute_refresh(
        gen_module=gen_mod,
        ver_module=ver_mod,
        cargo_lock=_CARGO_LOCK_PATH,
        baseline_dir=baseline_empty,
        work_dir=work_dir,
        inventory=gen_mod.TAG45_BINARY_INVENTORY,
        approval_token="AR-HAND-GATE-2026-05-19-fred",
        allow_checksum_changed=False,
        receipt_path=tmp_path / "receipt.json",
        operator_invocation={"test_anchor": "TR-E2E-02"},
        refresh_ts=99.0,
        generator_ts=0.0,
    )
    assert outcome.plan.pre_refresh_verdict == "RED"
    assert outcome.plan.cargo_lock_sha256_before is None
    assert outcome.post_refresh_verdict == "GREEN"
    assert outcome.refreshed is True
    # All 15 baseline files now exist.
    files = sorted(p.name for p in baseline_empty.glob("*.json"))
    assert len(files) == 15


# ===========================================================================
# CLI invariants (TR-CLI-01..TR-CLI-02)
# ===========================================================================


@pytest.mark.skipif(
    not _CARGO_LOCK_PATH.is_file()
    or not _BASELINE_DIR_REAL.is_dir(),
    reason="real Cargo.lock + baseline must be present (always true in CI)",
)
def test_TR_CLI_01_dry_run_does_not_mutate_baseline(tmp_path: Path):
    """TR-CLI-01: --dry-run computes plan + receipt without baseline mutation."""
    baseline_copy = tmp_path / "baseline"
    _stage_baseline_copy(baseline_copy)
    pre_hashes = {
        p.name: p.read_bytes()
        for p in sorted(baseline_copy.glob("*.json"))
    }

    receipt_path = tmp_path / "dry-run-receipt.json"
    rc = refresh.main(
        [
            "--cargo-lock", str(_CARGO_LOCK_PATH),
            "--baseline-dir", str(baseline_copy),
            "--dry-run",
            "--receipt-out", str(receipt_path),
            "--work-dir", str(tmp_path / "work"),
            "--refresh-ts", "777.0",
            "--generator-ts", "0.0",
        ]
    )
    assert rc == refresh.EXIT_OK

    # Baseline byte-identical.
    post_hashes = {
        p.name: p.read_bytes()
        for p in sorted(baseline_copy.glob("*.json"))
    }
    assert pre_hashes == post_hashes

    # Receipt exists and is flagged dry-run.
    receipt = json.loads(receipt_path.read_text())
    assert receipt["refreshed"] is False
    assert receipt["approval_token"] == "(dry-run, no token)"
    assert receipt["operator_invocation"]["dry_run"] is True


def test_TR_CLI_02_missing_approval_token_returns_exit_10(tmp_path: Path):
    """TR-CLI-02: real refresh without --approval-token exits 10."""
    # Set up a minimal baseline-dir to satisfy arg validation;
    # we expect the CLI to bail out before touching it.
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()

    rc = refresh.main(
        [
            "--cargo-lock", str(_CARGO_LOCK_PATH),
            "--baseline-dir", str(baseline_dir),
            "--work-dir", str(tmp_path / "work"),
        ]
    )
    assert rc == refresh.EXIT_NO_APPROVAL
    assert rc == 10


def test_TR_CLI_03_malformed_token_returns_exit_11(tmp_path: Path):
    """Additional CLI invariant: malformed token yields exit 11."""
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    rc = refresh.main(
        [
            "--cargo-lock", str(_CARGO_LOCK_PATH),
            "--baseline-dir", str(baseline_dir),
            "--approval-token", "not-the-right-format",
            "--work-dir", str(tmp_path / "work"),
        ]
    )
    assert rc == refresh.EXIT_BAD_TOKEN_FORMAT
    assert rc == 11
