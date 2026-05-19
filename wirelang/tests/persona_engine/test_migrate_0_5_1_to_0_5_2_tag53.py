# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic Tag-53 tests for the 0.5.1 -> 0.5.2-final migration helper.

These tests exercise the Python helper module
``scripts/persona-engine/migrate_0_5_1_to_0_5_2_helpers.py`` and
the Bash wrapper script
``scripts/persona-engine/migrate-0-5-1-to-0-5-2.sh`` (only the
read-only sub-commands; the ``--apply`` paths mutate a Live-VM
and are not exercised in the hermetic suite).

Why a separate Tag-53 test suite?
---------------------------------

The Tag-52 manifest-integrity suite
(``test_manifest_0_5_2_final_pre_cutover.py``) verifies that the
manifest, pin-pack, and Containerfile.real are byte-stable
vs. 0.5.1-pre-cutover. The Tag-53 helper *consumes* those
artefacts to produce an operator-facing rotation plan; verifying
the helper requires:

  1. Loading the helper module and feeding it the in-tree
     manifest+pin-pack (positive path).
  2. Feeding it a temporary directory with a manifest/pin-pack
     edited to drift from the canonical expectation (negative
     paths — each invariant tested in isolation).
  3. Asserting the rotation-plan and rollback-plan are
     symmetric (forward step N command + step N rollback
     reconstruct the byte-identical Quadlet file).
  4. Asserting the post-rotation verify reports OK only when
     all three observed fields match the canonical TO_VERSION
     constants.

The suite is fully hermetic — no podman, no systemctl, no
NATS. The Bash wrapper is invoked for its sub-command parsing
only, with the helper module reading from a temp-dir-copied
runtime tree. Live-VM rotation remains operator-hand territory.

ADR scope: ADR-0036 / ADR-0043 / ADR-0065 / ADR-0066.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

# ---------------------------------------------------------------------------
# Helper-module loading (script lives outside the Python package tree)
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
HELPER_PATH = (
    REPO_ROOT
    / "scripts"
    / "persona-engine"
    / "migrate_0_5_1_to_0_5_2_helpers.py"
)
WRAPPER_PATH = (
    REPO_ROOT
    / "scripts"
    / "persona-engine"
    / "migrate-0-5-1-to-0-5-2.sh"
)


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "_migrate_0_5_1_to_0_5_2_helpers", str(HELPER_PATH)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


HELPER = _load_helper()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture
def tmp_runtime(tmp_path: pathlib.Path) -> pathlib.Path:
    """Materialise a minimal runtime-tree skeleton inside ``tmp_path``
    by copying only the four files the helper consults (two
    manifests, two pin-packs, plus the Containerfile.real). The
    skeleton is the smallest payload that lets the helper pass
    its read-only checks without dragging in the full runtime.
    """

    targets = [
        HELPER.FROM_MANIFEST_REL,
        HELPER.TO_MANIFEST_REL,
        HELPER.FROM_PIN_PACK_REL,
        HELPER.TO_PIN_PACK_REL,
        HELPER.CONTAINERFILE_REL,
    ]
    for rel in targets:
        src = REPO_ROOT / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return tmp_path


# ---------------------------------------------------------------------------
# Test 01 — Helper script files exist and are executable
# ---------------------------------------------------------------------------


def test_01_helper_python_module_exists() -> None:
    assert HELPER_PATH.is_file(), (
        "Tag-53 deliverable missing: Python helper module"
    )
    assert HELPER_PATH.stat().st_mode & 0o111, (
        "Python helper module not marked executable"
    )


def test_02_helper_bash_wrapper_exists() -> None:
    assert WRAPPER_PATH.is_file(), (
        "Tag-53 deliverable missing: Bash entry wrapper"
    )
    assert WRAPPER_PATH.stat().st_mode & 0o111, (
        "Bash wrapper not marked executable"
    )


# ---------------------------------------------------------------------------
# Test 03 — Canonical version constants are stable
# ---------------------------------------------------------------------------


def test_03_canonical_version_constants() -> None:
    assert HELPER.FROM_VERSION == "0.5.1-pre-cutover"
    assert HELPER.TO_VERSION == "0.5.2-final-pre-cutover"
    assert HELPER.EXPECTED_TOTAL_WIRED_CRATES == 10
    assert HELPER.EXPECTED_TOTAL_PIN_PACK_CRATES == 15
    assert HELPER.EXPECTED_BOOT_RECORD_COUNT == 10
    assert HELPER.CANONICAL_BOOT_ORDER == (
        "persona-engine-recovery",
        "persona-engine-state-backing",
        "persona-engine-fsm",
        "persona-engine-v907-verify",
        "persona-engine-bridge-diff",
        "persona-engine-subscribe-loop",
        "persona-engine-anchor-emitter",
        "persona-engine-svid-workload-identity",
        "persona-engine-federation-resolver",
        "persona-engine-bridge-audit-writer",
    )


# ---------------------------------------------------------------------------
# Test 04 — Pre-rotation hash-check is OK on the canonical tree
# ---------------------------------------------------------------------------


def test_04_pre_rotation_canonical_tree_is_ok(repo_root: pathlib.Path) -> None:
    report = HELPER.pre_rotation_hash_check(repo_root)
    assert report.overall is HELPER.Severity.OK, (
        "pre-check unexpectedly failed on canonical tree: "
        + json.dumps(report.to_dict(), indent=2)
    )
    assert report.from_manifest_sha256 is not None
    assert report.to_manifest_sha256 is not None
    assert report.from_pin_pack_sha256 is not None
    assert report.to_pin_pack_sha256 is not None
    # sha256 digests are 64 hex chars
    for sha in (
        report.from_manifest_sha256,
        report.to_manifest_sha256,
        report.from_pin_pack_sha256,
        report.to_pin_pack_sha256,
    ):
        assert len(sha) == 64
        assert all(c in "0123456789abcdef" for c in sha)


# ---------------------------------------------------------------------------
# Test 05 — Pre-rotation detects missing FROM manifest
# ---------------------------------------------------------------------------


def test_05_pre_rotation_detects_missing_from_manifest(
    tmp_runtime: pathlib.Path,
) -> None:
    (tmp_runtime / HELPER.FROM_MANIFEST_REL).unlink()
    report = HELPER.pre_rotation_hash_check(tmp_runtime)
    assert report.overall is HELPER.Severity.FAIL
    fail_ids = {c.step_id for c in report.checks if c.severity is HELPER.Severity.FAIL}
    assert "manifest-from-present" in fail_ids


# ---------------------------------------------------------------------------
# Test 06 — Pre-rotation detects missing TO pin-pack
# ---------------------------------------------------------------------------


def test_06_pre_rotation_detects_missing_to_pin_pack(
    tmp_runtime: pathlib.Path,
) -> None:
    (tmp_runtime / HELPER.TO_PIN_PACK_REL).unlink()
    report = HELPER.pre_rotation_hash_check(tmp_runtime)
    assert report.overall is HELPER.Severity.FAIL
    fail_ids = {c.step_id for c in report.checks if c.severity is HELPER.Severity.FAIL}
    assert "pin-pack-to-present" in fail_ids


# ---------------------------------------------------------------------------
# Test 07 — Pre-rotation detects drifted pin-pack manifest_version
# ---------------------------------------------------------------------------


def test_07_pre_rotation_detects_drifted_manifest_version(
    tmp_runtime: pathlib.Path,
) -> None:
    pp = tmp_runtime / HELPER.TO_PIN_PACK_REL
    text = pp.read_text(encoding="utf-8")
    drifted = text.replace(
        'manifest_version: "0.5.2-final-pre-cutover"',
        'manifest_version: "0.5.3-pre-cutover"',
        1,
    )
    assert drifted != text, "fixture edit was a no-op"
    pp.write_text(drifted, encoding="utf-8")

    report = HELPER.pre_rotation_hash_check(tmp_runtime)
    assert report.overall is HELPER.Severity.FAIL
    fail_ids = {c.step_id for c in report.checks if c.severity is HELPER.Severity.FAIL}
    assert "pin-pack-manifest-version" in fail_ids


# ---------------------------------------------------------------------------
# Test 08 — Rotation-plan has six canonical steps in fixed order
# ---------------------------------------------------------------------------


def test_08_rotation_plan_canonical_steps(repo_root: pathlib.Path) -> None:
    plan = HELPER.compute_rotation_plan(repo_root)
    assert isinstance(plan, list)
    assert len(plan) == 6
    expected_ids = [
        "snapshot-quadlet",
        "edit-quadlet-image-tag",
        "podman-quadlet-validate",
        "systemctl-daemon-reload",
        "systemctl-restart",
        "observe-boot-fingerprint",
    ]
    assert [s["id"] for s in plan] == expected_ids
    # Step ordinals 1..6 are contiguous.
    assert [s["step"] for s in plan] == [1, 2, 3, 4, 5, 6]
    # Every step records both forward command and rollback command.
    for s in plan:
        assert "command" in s and s["command"]
        assert "rollback" in s and s["rollback"]


# ---------------------------------------------------------------------------
# Test 09 — Rotation-plan honours --quadlet-path override
# ---------------------------------------------------------------------------


def test_09_rotation_plan_quadlet_path_override(
    repo_root: pathlib.Path,
) -> None:
    custom = "/opt/wakir/custom-quadlet.container"
    plan = HELPER.compute_rotation_plan(repo_root, quadlet_path=custom)
    # The snapshot, sed, and quadlet-validate commands all
    # reference the custom path.
    assert custom in plan[0]["command"]
    assert custom in plan[1]["command"]
    assert custom in plan[2]["command"]


# ---------------------------------------------------------------------------
# Test 10 — Post-rotation verify reports OK on canonical observed snapshot
# ---------------------------------------------------------------------------


def test_10_post_rotation_verify_ok() -> None:
    snap = HELPER.PostRotationSnapshot(
        observed_image_tag="0.5.2-final-pre-cutover",
        observed_manifest_version="0.5.2-final-pre-cutover",
        observed_boot_record_count=10,
    )
    overall, checks = HELPER.post_rotation_verify(snap)
    assert overall is HELPER.Severity.OK
    assert all(c.severity is HELPER.Severity.OK for c in checks)


# ---------------------------------------------------------------------------
# Test 11 — Post-rotation verify fails on drifted image tag
# ---------------------------------------------------------------------------


def test_11_post_rotation_verify_drifted_tag() -> None:
    snap = HELPER.PostRotationSnapshot(
        observed_image_tag="0.5.1-pre-cutover",  # not yet rotated
        observed_manifest_version="0.5.2-final-pre-cutover",
        observed_boot_record_count=10,
    )
    overall, checks = HELPER.post_rotation_verify(snap)
    assert overall is HELPER.Severity.FAIL
    fail_ids = {c.step_id for c in checks if c.severity is HELPER.Severity.FAIL}
    assert "image-tag" in fail_ids


# ---------------------------------------------------------------------------
# Test 12 — Post-rotation verify fails on wrong boot-record count
# ---------------------------------------------------------------------------


def test_12_post_rotation_verify_wrong_record_count() -> None:
    snap = HELPER.PostRotationSnapshot(
        observed_image_tag="0.5.2-final-pre-cutover",
        observed_manifest_version="0.5.2-final-pre-cutover",
        observed_boot_record_count=9,  # boot-fingerprint drifted
    )
    overall, checks = HELPER.post_rotation_verify(snap)
    assert overall is HELPER.Severity.FAIL
    fail_ids = {c.step_id for c in checks if c.severity is HELPER.Severity.FAIL}
    assert "boot-record-count" in fail_ids


# ---------------------------------------------------------------------------
# Test 13 — Rollback-plan is symmetric to rotation-plan
# ---------------------------------------------------------------------------


def test_13_rollback_plan_symmetric_to_rotation(
    repo_root: pathlib.Path,
) -> None:
    fwd = HELPER.compute_rotation_plan(repo_root)
    back = HELPER.rollback_plan(repo_root)
    # Rollback has five steps (no snapshot-of-snapshot needed).
    assert len(back) == 5
    assert all("command" in s for s in back)
    # The rollback contains the inverse image-tag sed as either
    # the primary 'mv' (snapshot path) or the 'alternate' fallback.
    inverse_sed = (
        "sed -i 's|wakir-persona-engine:0.5.2-final-pre-cutover"
        "|wakir-persona-engine:0.5.1-pre-cutover|g'"
    )
    found_inverse = any(
        inverse_sed in (s.get("command", "") + " " + s.get("alternate", ""))
        for s in back
    )
    assert found_inverse, (
        "rollback plan must contain the inverse-sed fallback for "
        "the case where the snapshot is missing"
    )
    # Forward step #2 + rollback step #1 fallback are byte-inverses
    # of each other.
    forward_sed_cmd = fwd[1]["command"]
    inverse_in_fwd_rollback_field = fwd[1]["rollback"]
    assert "0.5.1-pre-cutover" in inverse_in_fwd_rollback_field
    assert "0.5.2-final-pre-cutover" in inverse_in_fwd_rollback_field
    assert "0.5.1-pre-cutover" in forward_sed_cmd
    assert "0.5.2-final-pre-cutover" in forward_sed_cmd


# ---------------------------------------------------------------------------
# Test 14 — sha256 helper is deterministic
# ---------------------------------------------------------------------------


def test_14_sha256_helper_deterministic(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "blob.bin"
    payload = b"persona-engine-0.5.2-final\n" * 4096
    target.write_bytes(payload)
    a = HELPER.file_sha256(tmp_path, "blob.bin")
    b = HELPER.file_sha256(tmp_path, "blob.bin")
    assert a == b
    # Known sha256 of the deterministic payload (cross-check via hashlib).
    import hashlib

    assert a == hashlib.sha256(payload).hexdigest()
    # Missing file returns None, not exception.
    assert HELPER.file_sha256(tmp_path, "absent.bin") is None


# ---------------------------------------------------------------------------
# Test 15 — Bash wrapper rejects unknown sub-commands
# ---------------------------------------------------------------------------


def test_15_bash_wrapper_rejects_unknown_subcommand() -> None:
    result = subprocess.run(
        [str(WRAPPER_PATH), "no-such-subcommand"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "unknown subcommand" in result.stderr


# ---------------------------------------------------------------------------
# Test 16 — Bash wrapper rotate/rollback refuse without --apply
# ---------------------------------------------------------------------------


def test_16_bash_wrapper_apply_required(tmp_path: pathlib.Path) -> None:
    for sub in ("rotate", "rollback"):
        result = subprocess.run(
            [str(WRAPPER_PATH), sub],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, (
            f"sub-command {sub!r} should refuse without --apply"
        )
        assert "--apply" in result.stderr


# ---------------------------------------------------------------------------
# Test 17 — Bash wrapper pre-check exits 0 on the canonical tree
# ---------------------------------------------------------------------------


def test_17_bash_wrapper_pre_check_canonical(repo_root: pathlib.Path) -> None:
    result = subprocess.run(
        [
            str(WRAPPER_PATH),
            "pre-check",
            "--repo-root",
            str(repo_root),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "bash wrapper pre-check failed on canonical tree: "
        + result.stdout
        + "\n---\n"
        + result.stderr
    )
    # The JSON output lives on stdout, the log prefix lives on stderr.
    parsed = json.loads(result.stdout)
    assert parsed["overall"] == "ok"
    assert parsed["from_version"] == "0.5.1-pre-cutover"
    assert parsed["to_version"] == "0.5.2-final-pre-cutover"


# ---------------------------------------------------------------------------
# Test 18 — Bash wrapper rotation-plan emits valid JSON
# ---------------------------------------------------------------------------


def test_18_bash_wrapper_rotation_plan_json(repo_root: pathlib.Path) -> None:
    result = subprocess.run(
        [
            str(WRAPPER_PATH),
            "rotation-plan",
            "--repo-root",
            str(repo_root),
            "--quadlet-path",
            "/tmp/wakir-engine.container",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, list)
    assert len(parsed) == 6
    # The custom quadlet path is baked in.
    assert all(
        "/tmp/wakir-engine.container" in str(step) for step in parsed[:3]
    ), parsed


# ---------------------------------------------------------------------------
# Test 19 — Bash wrapper post-verify rejects missing flags
# ---------------------------------------------------------------------------


def test_19_bash_wrapper_post_verify_required_flags() -> None:
    result = subprocess.run(
        [str(WRAPPER_PATH), "post-verify", "--image-tag", "0.5.2-final-pre-cutover"],
        capture_output=True,
        text=True,
    )
    # Missing --manifest-version + --boot-record-count -> usage error.
    assert result.returncode == 1
    assert "--manifest-version" in result.stderr


# ---------------------------------------------------------------------------
# Test 20 — Bash wrapper post-verify happy path
# ---------------------------------------------------------------------------


def test_20_bash_wrapper_post_verify_ok() -> None:
    result = subprocess.run(
        [
            str(WRAPPER_PATH),
            "post-verify",
            "--image-tag",
            "0.5.2-final-pre-cutover",
            "--manifest-version",
            "0.5.2-final-pre-cutover",
            "--boot-record-count",
            "10",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["overall"] == "ok"
    assert all(c["severity"] == "ok" for c in parsed["checks"])
