# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/ci/validate_demo_proof_report.py``.

The validator is the hard-fail half of the ``proof-path`` CI gate.
These tests pin its rules without running ``scripts/demo-proof.sh``:
each case builds a ``wakir-demo-proof/v1`` report in memory, mutates
one property, and asserts on the violation list plus the CLI exit
code. No network, no subprocess beyond ``python`` itself.

Profile note (2026-09-14, finding R1)
-------------------------------------

The validator used to be permissive by default and strict only with
``--require-external-verify-ok``; a deny-list of two statuses let
``skipped``, unknown statuses, mismatched exit codes and
self-contradicting detail flags through. It is now strict by default,
with a single named relaxation (``--allow-skipped-external-verify``)
that CI does not pass. The cases under "Negative matrix (finding R1)"
are the reproduction from the external re-review, turned into
regression tests.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "ci" / "validate_demo_proof_report.py"

COMMIT = "8465c49a8c0d6f1e2b3c4d5e6f708192a3b4c5d6"
OTHER_COMMIT = "0000000000000000000000000000000000000000"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_demo_proof_report", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_module()


#: What the driver writes into ``details`` for a *successful* step.
#: Mirrors ``scripts/demo-proof.sh`` (steps 2/3/4/5) and
#: ``do_external_verify`` in ``scripts/demo_proof_helpers.py``.
OK_DETAILS: Dict[str, Dict[str, Any]] = {
    "protocol_event": {},
    "runtime_bridge": {"bridge_status": "ok"},
    "merkle_manifest": {"envelope_projection_used": "false"},
    "inclusion_proof": {"verified": True},
    "external_verify": {
        "manifest_consistent": True,
        "root_match": True,
        "leaf_present": True,
        "proof_verified": True,
    },
}


def _step(name: str, status: str = "ok", code: int = 0, **details: Any) -> Dict[str, Any]:
    body = dict(OK_DETAILS.get(name, {})) if status == "ok" else {}
    body.update(details)
    return {"name": name, "status": status, "exit_code": code, "details": body}


def _valid_report(commit: str = COMMIT) -> Dict[str, Any]:
    steps = [_step(n) for n in validator.STEP_NAMES]
    return {
        "schema": "wakir-demo-proof/v1",
        "hour": "2026-05-17T12",
        "workdir": "/tmp/demo",
        "commits": {
            "wakir_runtime": commit,
            "wakir_protocol": "unknown",
            "wakir_verify": "unknown",
        },
        "steps": steps,
        "exit_code": 0,
    }


def _validate(
    report: Dict[str, Any],
    *,
    allow_skipped_ev: bool = False,
    commit: str | None = COMMIT,
) -> List[str]:
    """Strict profile by default — the profile ``proof-path.yml`` runs."""
    return validator.validate_report(
        report,
        allow_skipped_external_verify=allow_skipped_ev,
        expected_commit=commit,
    )


def _run_cli(tmp_path: Path, report: Dict[str, Any], *args: str, env_sha: str | None = None) -> subprocess.CompletedProcess:
    path = tmp_path / "demo-report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8"}
    if env_sha is not None:
        env["GITHUB_SHA"] = env_sha
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(path), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# Library-level rules
# ---------------------------------------------------------------------------


def test_valid_report_has_no_violations():
    assert _validate(_valid_report()) == []


def test_step_order_matches_driver_canonical_order():
    """The validator's step list must be the driver's. Guard against
    the two drifting apart silently."""
    helpers_path = REPO_ROOT / "scripts" / "demo_proof_helpers.py"
    spec = importlib.util.spec_from_file_location("demo_proof_helpers", helpers_path)
    assert spec is not None and spec.loader is not None
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    assert tuple(validator.STEP_NAMES) == tuple(helpers.STEP_NAMES)
    assert validator.REPORT_SCHEMA == helpers.REPORT_SCHEMA


def test_missing_step_is_a_violation():
    report = _valid_report()
    report["steps"] = [s for s in report["steps"] if s["name"] != "merkle_manifest"]
    violations = _validate(report)
    assert any("expected exactly 5 steps, got 4" in v for v in violations)
    assert any("missing=['merkle_manifest']" in v for v in violations)


def test_wrong_step_order_is_a_violation():
    report = _valid_report()
    report["steps"][1], report["steps"][2] = report["steps"][2], report["steps"][1]
    violations = _validate(report)
    assert any("order differs" in v for v in violations)


def test_extra_step_is_a_violation():
    report = _valid_report()
    report["steps"].append(_step("bonus_step"))
    violations = _validate(report)
    assert any("unexpected=['bonus_step']" in v for v in violations)


def test_skipped_external_verify_fails_in_the_strict_default():
    """Was: only rejected with --require-external-verify-ok. The strict
    profile is now the default, so no flag is needed to reject it."""
    report = _valid_report()
    report["steps"][4] = _step(
        "external_verify", "skipped", 20, mode="library", reason="wakir_verify not importable"
    )
    violations = _validate(report)
    assert any(
        "status 'skipped' is not accepted" in v and "not importable" in v
        for v in violations
    )


def test_skipped_external_verify_passes_only_with_the_named_relaxation():
    report = _valid_report()
    report["steps"][4] = _step("external_verify", "skipped", 20, reason="offline")
    assert _validate(report, allow_skipped_ev=True) == []


def test_the_relaxation_covers_external_verify_and_nothing_else():
    for idx, name in enumerate(validator.STEP_NAMES[:-1]):
        report = _valid_report()
        report["steps"][idx] = _step(name, "skipped", 20, reason="offline")
        violations = _validate(report, allow_skipped_ev=True)
        assert any("status 'skipped' is not accepted" in v for v in violations), name


def test_require_flag_cancels_the_relaxation():
    report = _valid_report()
    report["steps"][4] = _step("external_verify", "skipped", 20, reason="offline")
    violations = validator.validate_report(
        report,
        allow_skipped_external_verify=True,
        require_external_verify_ok=True,
        expected_commit=COMMIT,
    )
    assert any("status 'skipped' is not accepted" in v for v in violations)


def test_failed_step_is_a_violation_regardless_of_flag():
    report = _valid_report()
    report["steps"][2] = _step(
        "merkle_manifest", "failed", 10, error="fault injected via DEMO_PROOF_FAIL_STEP"
    )
    report["exit_code"] = 10
    violations = _validate(report, allow_skipped_ev=True)
    assert any("status 'failed' is not accepted" in v and "fault injected" in v for v in violations)
    assert any("exit_code: expected 0, got 10" in v for v in violations)


def test_not_run_step_is_a_violation():
    report = _valid_report()
    report["steps"][3] = _step(
        "inclusion_proof", "not_run", 30, reason="short-circuited after step3_merkle_manifest failed"
    )
    violations = _validate(report, allow_skipped_ev=True)
    assert any("status 'not_run' is not accepted" in v for v in violations)


def test_wrong_commit_is_a_violation():
    violations = _validate(_valid_report(commit=OTHER_COMMIT), commit=COMMIT)
    assert violations == [
        f"commits.wakir_runtime: expected {COMMIT!r}, got {OTHER_COMMIT!r}"
    ]


def test_commit_check_skipped_when_no_expectation():
    assert _validate(_valid_report(commit="unknown"), commit=None) == []


def test_wrong_schema_is_a_violation():
    report = _valid_report()
    report["schema"] = "wakir-demo-proof/v0"
    violations = _validate(report)
    assert any("schema: expected 'wakir-demo-proof/v1'" in v for v in violations)


def test_step_without_status_or_exit_code_is_a_violation():
    report = _valid_report()
    del report["steps"][0]["status"]
    report["steps"][1]["exit_code"] = "0"
    violations = _validate(report)
    assert any("(protocol_event): status missing" in v for v in violations)
    assert any("(runtime_bridge): exit_code missing or not an integer" in v for v in violations)


def test_non_object_report_is_a_violation():
    assert _validate(["not", "a", "report"]) == ["report is not a JSON object"]


# ---------------------------------------------------------------------------
# CLI contract (what proof-path.yml actually invokes)
# ---------------------------------------------------------------------------


def test_cli_valid_report_exits_zero_with_github_sha(tmp_path: Path):
    proc = _run_cli(tmp_path, _valid_report(), "--require-external-verify-ok", env_sha=COMMIT)
    assert proc.returncode == 0, proc.stderr
    assert "validate-demo-proof: OK" in proc.stdout
    assert f"commit={COMMIT}" in proc.stdout


def test_cli_github_sha_mismatch_exits_one(tmp_path: Path):
    proc = _run_cli(tmp_path, _valid_report(), "--require-external-verify-ok", env_sha=OTHER_COMMIT)
    assert proc.returncode == 1
    assert "commits.wakir_runtime: expected" in proc.stderr


def test_cli_expect_commit_flag_overrides_env(tmp_path: Path):
    proc = _run_cli(
        tmp_path,
        _valid_report(),
        "--require-external-verify-ok",
        "--expect-commit",
        COMMIT,
        env_sha=OTHER_COMMIT,
    )
    assert proc.returncode == 0, proc.stderr


def test_cli_skipped_external_verify_exits_one_when_required(tmp_path: Path):
    report = _valid_report()
    report["steps"][4] = _step("external_verify", "skipped", 20, reason="offline")
    proc = _run_cli(tmp_path, report, env_sha=COMMIT)
    assert proc.returncode == 1
    assert "status 'skipped' is not accepted" in proc.stderr


def test_cli_fault_injected_report_exits_one(tmp_path: Path):
    """Mirror of the fault-injection PR: step 3 failed, 4-5 not_run."""
    report = _valid_report()
    report["steps"][2] = _step("merkle_manifest", "failed", 10, error="fault injected")
    report["steps"][3] = _step("inclusion_proof", "not_run", 30, reason="short-circuited")
    report["steps"][4] = _step("external_verify", "not_run", 30, reason="short-circuited")
    report["exit_code"] = 10
    proc = _run_cli(tmp_path, report, "--require-external-verify-ok", env_sha=COMMIT)
    assert proc.returncode == 1
    assert "merkle_manifest): status 'failed'" in proc.stderr


def test_cli_missing_file_exits_two(tmp_path: Path):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(tmp_path / "nope.json")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "report not found" in proc.stderr


def test_cli_invalid_json_exits_two(tmp_path: Path):
    path = tmp_path / "demo-report.json"
    path.write_text("{not json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "not valid JSON" in proc.stderr


def test_validator_is_stdlib_only():
    """The gate must not depend on anything ``pip install -e .`` might
    fail to provide. Whitelist of imports in the script."""
    allowed = {"argparse", "json", "os", "sys", "pathlib", "typing", "__future__"}
    imported = set()
    for line in SCRIPT_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("import "):
            imported.add(stripped.split()[1].split(".")[0])
        elif stripped.startswith("from ") and " import " in stripped:
            imported.add(stripped.split()[1].split(".")[0])
    assert imported <= allowed, imported - allowed


# ---------------------------------------------------------------------------
# Negative matrix (finding R1, external re-review 2026-09-14)
# ---------------------------------------------------------------------------
#
# Every row below returned rc=0 from the CLI invocation that
# `proof-path.yml` runs, against the pre-fix validator. They are the
# regression net for the deny-list-instead-of-allow-list defect.


def test_r1_skipped_first_step_with_nonzero_exit_code_is_rejected():
    report = _valid_report()
    report["steps"][0] = _step("protocol_event", "skipped", 20)
    violations = _validate(report)
    assert any("status 'skipped' is not accepted" in v for v in violations)


def test_r1_unknown_status_string_is_rejected():
    """The old deny-list forbade two statuses and waved through every
    string nobody had thought of."""
    for bogus in ("banana", "passed", "OK", "ok "):
        report = _valid_report()
        report["steps"][0]["status"] = bogus
        violations = _validate(report)
        assert any("is not accepted" in v for v in violations), bogus


def test_r1_status_ok_with_nonzero_exit_code_is_rejected():
    report = _valid_report()
    report["steps"][2]["exit_code"] = 999
    violations = _validate(report)
    assert any(
        "status 'ok' requires exit_code 0, got 999" in v for v in violations
    )


def test_r1_boolean_exit_code_is_not_an_integer():
    """``isinstance(True, int)`` is True in Python; the report is JSON,
    where ``true`` is not 0."""
    report = _valid_report()
    report["steps"][0]["exit_code"] = False
    assert any("not an integer" in v for v in _validate(report))
    report = _valid_report()
    report["exit_code"] = False
    assert any("exit_code: expected 0" in v for v in _validate(report))


def test_r1_external_verify_ok_with_false_proof_verified_is_rejected():
    report = _valid_report()
    report["steps"][4]["details"]["proof_verified"] = False
    violations = _validate(report)
    assert any("contradicts details.proof_verified=False" in v for v in violations)


@pytest.mark.parametrize(
    "flag",
    ["manifest_consistent", "root_match", "leaf_present", "proof_verified"],
)
def test_r1_every_external_verify_flag_must_agree_with_the_status(flag: str):
    report = _valid_report()
    report["steps"][4]["details"][flag] = False
    assert any(f"contradicts details.{flag}=False" in v for v in _validate(report))

    report = _valid_report()
    del report["steps"][4]["details"][flag]
    assert any(f"details.{flag} is missing" in v for v in _validate(report))


def test_r1_inclusion_proof_ok_with_verified_false_is_rejected():
    report = _valid_report()
    report["steps"][3]["details"]["verified"] = False
    assert any("contradicts details.verified=False" in v for v in _validate(report))


def test_r1_runtime_bridge_ok_with_failed_bridge_status_is_rejected():
    report = _valid_report()
    report["steps"][1]["details"]["bridge_status"] = "wat-failed"
    violations = _validate(report)
    assert any("contradicts details.bridge_status='wat-failed'" in v for v in violations)


def test_r1_fault_injected_step_cannot_be_ok():
    report = _valid_report()
    report["steps"][0]["details"]["fault_injected"] = "true"
    assert any("contradicts details.fault_injected" in v for v in _validate(report))


def test_r5_projected_manifest_is_not_a_proof():
    """Finding R5: a manifest built from envelope-repaired spool input
    must not pass the strict gate, and the report must say which it
    was."""
    report = _valid_report()
    report["steps"][2]["details"]["envelope_projection_used"] = "true"
    assert any(
        "contradicts details.envelope_projection_used='true'" in v
        for v in _validate(report)
    )

    report = _valid_report()
    del report["steps"][2]["details"]["envelope_projection_used"]
    assert any(
        "details.envelope_projection_used is missing" in v for v in _validate(report)
    )


def test_r1_control_clean_report_still_passes():
    """Positive control: the fix must not make the honest report red."""
    assert _validate(_valid_report()) == []


def test_r1_cli_matrix_exit_codes(tmp_path: Path):
    """The matrix through the CLI, with the flags proof-path.yml uses."""
    cases = {
        "skipped_step": lambda r: r["steps"][0].update(status="skipped", exit_code=20),
        "unknown_status": lambda r: r["steps"][0].update(status="banana"),
        "ok_with_999": lambda r: r["steps"][2].update(exit_code=999),
        "contradicting_detail": lambda r: r["steps"][4]["details"].update(
            proof_verified=False
        ),
        "failed_step": lambda r: r["steps"][1].update(status="failed", exit_code=10),
    }
    for label, mutate in cases.items():
        report = _valid_report()
        mutate(report)
        proc = _run_cli(
            tmp_path, report, "--require-external-verify-ok", env_sha=COMMIT
        )
        assert proc.returncode == 1, f"{label} was accepted: {proc.stdout}"

    proc = _run_cli(
        tmp_path, _valid_report(), "--require-external-verify-ok", env_sha=COMMIT
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK [strict]" in proc.stdout
