# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tests for ``scripts/ci-live-vm-phase-3b-driver.sh`` — Tag-19 Mini-Welle.

The driver script is the matrix-cell hand-off declared in
``.github/workflows/live-vm-acceptance.yml`` and documented in
``docs/operations/live-vm-acceptance-phase-3b.md`` §4. These tests
exercise the driver via real subprocess invocations against the
``--mode=self-test`` surface, so the verdict JSON-schema, the CLI
argument-handling, and the latency-budget gate are validated against
the actual shell script — not a Python re-implementation.

Hermetic constraints
--------------------

* No SSH. Every test runs ``--mode=self-test`` so the driver bypasses
  the SSH path entirely. The hermetic claude-dev sandbox cannot reach
  192.168.178.* (see ``feedback_sandbox_host_trennung.md``), and even
  the GitHub-Actions hosted runner does not have an authorised key to
  the Pilot-VM at test time.
* No real persona-engine. The verdict-shape is driven by
  ``WAKIR_PHASE_3B_MOCK_*`` ENV-vars. The driver still applies the
  latency-budget gate to the mocked values, which is the substantial
  cross-check between this test surface and the production path.
* ``jq`` is a hard dependency of the driver. When the local runner
  does not have ``jq`` on PATH (e.g. the sandbox developer box), the
  whole test module skips cleanly. CI runners (ubuntu-latest +
  GitHub-Actions image) ship ``jq`` by default; if the surrounding
  workflow installs ``jq`` explicitly that path is also covered.

Scope (10 test vectors, all subprocess-driven)
----------------------------------------------

1. ``test_driver_script_exists_and_is_executable``
2. ``test_help_flag_exits_zero_and_documents_required_flags``
3. ``test_missing_required_flag_emits_usage_error_and_exits_64``
4. ``test_invalid_recovery_backend_rejected_at_cli_layer``
5. ``test_self_test_default_ok_emits_canonical_schema``
6. ``test_self_test_latency_budget_violation_flips_status``
7. ``test_self_test_explicit_fail_status_passthrough``
8. ``test_self_test_driver_not_present_status_passthrough``
9. ``test_self_test_component_fsm_maps_to_recovery``
10. ``test_self_test_exit_codes_match_documented_table``
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# jq is a hard dependency of the driver. The skipif lives on each
# subprocess-invocation test individually (not as a module-level
# ``pytestmark``), so the static-text / doc-anchor self-tests still
# run in jq-less sandboxes and continue to guard against schema drift.
# ---------------------------------------------------------------------------

JQ_BIN = shutil.which("jq")
requires_jq = pytest.mark.skipif(
    JQ_BIN is None,
    reason="jq not available on PATH; the Phase-3b driver requires jq to "
    "emit the verdict-JSON. CI lanes (ubuntu-latest, GitHub-Actions image) "
    "ship jq; the hermetic developer sandbox does not. Skipping cleanly.",
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER_PATH = REPO_ROOT / "scripts" / "ci-live-vm-phase-3b-driver.sh"
DRIVER_DOC_PATH = (
    REPO_ROOT / "docs" / "operations" / "live-vm-acceptance-phase-3b.md"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_driver(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the driver script with the given argv and return the result.

    Hermetic: the call never touches SSH because every test passes
    ``--mode=self-test``. The PATH is preserved so the driver can find
    ``jq``; the rest of the environment is reset to a minimal baseline
    plus any test-supplied overrides.
    """
    base_env = {
        "PATH": os.environ.get("PATH", ""),
        "LC_ALL": "C",
        "LANG": "C",
    }
    if env:
        base_env.update(env)

    return subprocess.run(
        ["bash", str(DRIVER_PATH), *args],
        env=base_env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _canonical_self_test_args(report_path: Path, **overrides: str) -> list[str]:
    """Build a minimum-viable canonical argv for the self-test mode."""
    defaults: dict[str, str] = {
        "--target": "wakir-pilot",
        "--recovery-backend": "rust",
        "--state-backing-backend": "rust_natskv",
        "--latency-budget-ms": "1500",
        "--report-json": str(report_path),
        "--mode": "self-test",
    }
    defaults.update(overrides)
    out: list[str] = []
    for flag, value in defaults.items():
        out.extend([flag, value])
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_driver_script_exists_and_is_executable() -> None:
    """The driver script lives at the canonical path the workflow uses."""
    assert DRIVER_PATH.exists(), (
        f"driver script missing at {DRIVER_PATH}; the Tag-18 workflow at "
        f".github/workflows/live-vm-acceptance.yml:647 hard-codes this path."
    )
    assert os.access(DRIVER_PATH, os.X_OK), (
        f"driver script {DRIVER_PATH} is not executable; the workflow "
        f"checks `[[ -x \"${{DRIVER}}\" ]]` before invocation."
    )


@requires_jq
def test_help_flag_exits_zero_and_documents_required_flags() -> None:
    """`--help` prints the documented contract and exits 0."""
    result = _run_driver(["--help"])
    assert result.returncode == 0, (
        f"--help should exit 0 (rc={result.returncode}, "
        f"stderr={result.stderr!r})"
    )

    # The seven required flags from PR #168 §4 must each appear in help.
    required_flags = [
        "--target",
        "--ssh-user",
        "--ssh-key",
        "--recovery-backend",
        "--state-backing-backend",
        "--latency-budget-ms",
        "--report-json",
    ]
    for flag in required_flags:
        assert flag in result.stdout, (
            f"help output missing required flag mention: {flag!r}\n"
            f"stdout: {result.stdout!r}"
        )

    # The §4 driver-contract anchor must be referenced so an operator
    # reading --help knows where the authoritative schema is documented.
    assert "live-vm-acceptance-phase-3b.md" in result.stdout, (
        "help output must link back to the operator doc anchor at §4"
    )


@requires_jq
def test_missing_required_flag_emits_usage_error_and_exits_64(
    tmp_path: Path,
) -> None:
    """Missing `--report-json` should fail with usage exit-code 64."""
    args = _canonical_self_test_args(tmp_path / "report.json")
    # Drop --report-json + its value.
    idx = args.index("--report-json")
    args.pop(idx)  # remove flag
    args.pop(idx)  # remove value
    result = _run_driver(args)

    assert result.returncode == 64, (
        f"missing required flag should exit 64 (rc={result.returncode}, "
        f"stderr={result.stderr!r})"
    )
    assert "--report-json" in result.stderr, (
        f"usage error should name the missing flag\n"
        f"stderr: {result.stderr!r}"
    )


@requires_jq
def test_invalid_recovery_backend_rejected_at_cli_layer(
    tmp_path: Path,
) -> None:
    """`--recovery-backend=garbage` should fail at the CLI-validation layer."""
    args = _canonical_self_test_args(
        tmp_path / "report.json",
        **{"--recovery-backend": "garbage"},
    )
    result = _run_driver(args)
    assert result.returncode == 64, (
        f"invalid backend should exit 64 (rc={result.returncode}, "
        f"stderr={result.stderr!r})"
    )
    assert "recovery-backend" in result.stderr, (
        "usage error should name the offending flag"
    )
    # The report must NOT be written when CLI validation fails.
    assert not (tmp_path / "report.json").exists(), (
        "report.json should not be created when CLI validation fails"
    )


@requires_jq
def test_self_test_default_ok_emits_canonical_schema(tmp_path: Path) -> None:
    """Default self-test invocation produces a status=ok report with the
    canonical PR #168 §4 schema."""
    report_path = tmp_path / "report.json"
    args = _canonical_self_test_args(report_path)
    result = _run_driver(args)

    assert result.returncode == 0, (
        f"default self-test should exit 0 (rc={result.returncode}, "
        f"stderr={result.stderr!r})"
    )
    assert report_path.exists(), "self-test must write the report"

    report = json.loads(report_path.read_text())

    # Canonical schema fields from PR #168 §4 + Tag-19 driver-contract.
    expected_keys = {
        "target_vm",
        "recovery_backend",
        "state_backing_backend",
        "latency_budget_ms",
        "status",
        "final_state_hash",
        "recovery_latency_ms_p50",
        "recovery_latency_ms_p95",
        "state_latency_ms_p50",
        "state_latency_ms_p95",
        "fallback_reason",
        "backend_decision_record",
    }
    assert set(report.keys()) == expected_keys, (
        f"report schema drift: extra={set(report.keys()) - expected_keys}, "
        f"missing={expected_keys - set(report.keys())}"
    )

    # Field-value contract for the default-ok path.
    assert report["status"] == "ok"
    assert report["target_vm"] == "wakir-pilot"
    assert report["recovery_backend"] == "rust"
    assert report["state_backing_backend"] == "rust_natskv"
    assert report["latency_budget_ms"] == 1500
    assert isinstance(report["final_state_hash"], str)
    assert len(report["final_state_hash"]) == 64
    assert isinstance(report["recovery_latency_ms_p50"], int)
    assert isinstance(report["recovery_latency_ms_p95"], int)
    assert isinstance(report["state_latency_ms_p50"], int)
    assert isinstance(report["state_latency_ms_p95"], int)
    assert report["fallback_reason"] is None

    # Tag-19 backend_decision_record contract.
    bdr = report["backend_decision_record"]
    assert bdr["recovery_backend"] == "rust"
    assert bdr["state_backing_backend"] == "rust_natskv"
    assert bdr["component_focus"] == "both"
    assert bdr["fail_subkind"] is None  # ok path carries null subkind

    # The verdict-status codomain must stay within the three-token
    # set the workflow's per-permutation verdict-step accepts. The
    # richer failure-mode discrimination lives in
    # backend_decision_record.fail_subkind.
    assert report["status"] in {"ok", "fail", "driver-not-present"}


@requires_jq
def test_self_test_latency_budget_violation_flips_status(tmp_path: Path) -> None:
    """When mocked p95 exceeds the budget the verdict-JSON emits
    ``status=fail`` (workflow-accepted token) with
    ``backend_decision_record.fail_subkind == 'latency-budget'`` and
    exit-code 2 (operator-facing surface)."""
    report_path = tmp_path / "report.json"
    args = _canonical_self_test_args(
        report_path,
        **{"--latency-budget-ms": "100"},
    )
    # Inject a recovery-p95 that exceeds the 100 ms budget.
    env = {
        "WAKIR_PHASE_3B_MOCK_RECOVERY_P95": "999",
        "WAKIR_PHASE_3B_MOCK_RECOVERY_P50": "42",
        "WAKIR_PHASE_3B_MOCK_STATE_P95": "31",
        "WAKIR_PHASE_3B_MOCK_STATE_P50": "22",
    }
    result = _run_driver(args, env=env)

    assert result.returncode == 2, (
        f"latency-budget violation should exit 2 (operator-facing) "
        f"(rc={result.returncode}, stderr={result.stderr!r})"
    )
    report = json.loads(report_path.read_text())
    # Verdict-status is the workflow-accepted `fail`. The richer
    # latency-budget discriminator lives in the fail_subkind field.
    assert report["status"] == "fail"
    assert (
        report["backend_decision_record"]["fail_subkind"] == "latency-budget"
    )
    assert report["latency_budget_ms"] == 100
    assert report["recovery_latency_ms_p95"] == 999
    assert report["fallback_reason"] is not None
    assert "999" in report["fallback_reason"]
    assert "100" in report["fallback_reason"]


@requires_jq
def test_self_test_explicit_fail_status_passthrough(tmp_path: Path) -> None:
    """A self-test-injected ``fail`` status passes through to the verdict
    JSON with exit-code 4 (operator-facing on-VM-failure surface). The
    discriminator ``fail_subkind == 'on-vm'`` distinguishes this from
    latency-budget and driver-error failures."""
    report_path = tmp_path / "report.json"
    args = _canonical_self_test_args(report_path)
    env = {
        "WAKIR_PHASE_3B_MOCK_STATUS": "fail",
        "WAKIR_PHASE_3B_MOCK_FALLBACK_REASON": "on-vm-r1-recovery-mismatch",
    }
    result = _run_driver(args, env=env)

    assert result.returncode == 4, (
        f"status=fail (on-vm) should exit 4 "
        f"(rc={result.returncode}, stderr={result.stderr!r})"
    )
    report = json.loads(report_path.read_text())
    assert report["status"] == "fail"
    assert report["backend_decision_record"]["fail_subkind"] == "on-vm"
    assert report["fallback_reason"] == "on-vm-r1-recovery-mismatch"
    # Latency fields are null on the explicit-fail path.
    assert report["final_state_hash"] is None
    assert report["recovery_latency_ms_p95"] is None


@requires_jq
def test_self_test_driver_not_present_status_passthrough(
    tmp_path: Path,
) -> None:
    """The ``driver-not-present`` status is emitted with exit-code 0 —
    same as ``ok``, matching the workflow per-permutation verdict-step
    (live-vm-acceptance.yml:711-714 maps driver-not-present to a clean
    SKIP)."""
    report_path = tmp_path / "report.json"
    args = _canonical_self_test_args(report_path)
    env = {
        "WAKIR_PHASE_3B_MOCK_STATUS": "driver-not-present",
        "WAKIR_PHASE_3B_MOCK_FALLBACK_REASON": "self-test-injected-stub",
    }
    result = _run_driver(args, env=env)

    assert result.returncode == 0, (
        f"status=driver-not-present should exit 0 "
        f"(rc={result.returncode}, stderr={result.stderr!r})"
    )
    report = json.loads(report_path.read_text())
    assert report["status"] == "driver-not-present"
    assert report["fallback_reason"] == "self-test-injected-stub"
    assert report["final_state_hash"] is None
    assert report["backend_decision_record"]["fail_subkind"] is None


@requires_jq
def test_self_test_component_fsm_maps_to_recovery(tmp_path: Path) -> None:
    """`--component=fsm` is reserved for a future Phase-3c FSM-equivalence
    lane; the Tag-19 driver maps it to ``recovery`` so the workflow
    accepts the flag without exploding."""
    report_path = tmp_path / "report.json"
    args = _canonical_self_test_args(
        report_path,
        **{"--component": "fsm"},
    )
    result = _run_driver(args)

    assert result.returncode == 0, (
        f"component=fsm should be accepted (rc={result.returncode}, "
        f"stderr={result.stderr!r})"
    )
    report = json.loads(report_path.read_text())
    assert report["status"] == "ok"
    assert (
        report["backend_decision_record"]["component_focus"] == "recovery"
    ), (
        "component=fsm should map to component_focus=recovery in the "
        "backend_decision_record (Tag-19 placeholder for Phase-3c)"
    )


@requires_jq
def test_self_test_exit_codes_match_documented_table(
    tmp_path: Path,
) -> None:
    """Sweep the ``(injected status, expected exit-code, emitted status,
    emitted fail_subkind)`` matrix the driver header documents under
    ``Exit codes:``. The injected status uses the operator-facing token
    set ({ok, fail, fail-driver-error, driver-not-present}); the emitted
    verdict-status stays within the workflow-accepted three-token set
    ({ok, fail, driver-not-present}) with a structured fail_subkind
    discriminator carrying the richer failure-mode information."""
    cases: list[tuple[str, int, str, str | None, dict[str, str]]] = [
        # (label, expected_rc, emitted_status, emitted_fail_subkind, env)
        ("ok",                 0, "ok",                 None,          {}),
        (
            "fail",
            4,
            "fail",
            "on-vm",
            {"WAKIR_PHASE_3B_MOCK_STATUS": "fail"},
        ),
        (
            "fail-driver-error",
            3,
            "fail",
            "driver-error",
            {"WAKIR_PHASE_3B_MOCK_STATUS": "fail-driver-error"},
        ),
        (
            "driver-not-present",
            0,
            "driver-not-present",
            None,
            {"WAKIR_PHASE_3B_MOCK_STATUS": "driver-not-present"},
        ),
    ]
    for label, expected_rc, emitted_status, emitted_subkind, env in cases:
        report_path = tmp_path / f"report-{label}.json"
        args = _canonical_self_test_args(report_path)
        result = _run_driver(args, env=env)
        assert result.returncode == expected_rc, (
            f"status={label} expected exit-code {expected_rc}, "
            f"got {result.returncode}\nstderr: {result.stderr!r}"
        )
        report = json.loads(report_path.read_text())
        assert report["status"] == emitted_status, (
            f"status={label} expected emitted verdict {emitted_status!r}, "
            f"got {report['status']!r}"
        )
        assert (
            report["backend_decision_record"]["fail_subkind"]
            == emitted_subkind
        ), (
            f"status={label} expected fail_subkind={emitted_subkind!r}, "
            f"got {report['backend_decision_record']['fail_subkind']!r}"
        )
        # Every emitted status must stay within the workflow-accepted set.
        assert report["status"] in {"ok", "fail", "driver-not-present"}


# ---------------------------------------------------------------------------
# Doc-anchor self-test (cross-reference integrity)
# ---------------------------------------------------------------------------


def test_driver_doc_anchor_references_workflow_and_section_4() -> None:
    """The driver-contract doc PR #168 §4 must continue to anchor the
    driver script and its CLI-flag set. This is a sanity self-test that
    catches drift if either side is moved without the other.
    """
    assert DRIVER_DOC_PATH.exists(), (
        f"operator doc {DRIVER_DOC_PATH} missing"
    )
    doc_text = DRIVER_DOC_PATH.read_text()

    # §4 is the canonical driver-contract anchor — keep it parseable.
    assert "## 4. The driver script" in doc_text
    assert "scripts/ci-live-vm-phase-3b-driver.sh" in doc_text

    # Every required flag from the §4 invocation block must still be
    # listed; if someone renames a flag the doc must move with it.
    required_flag_mentions = [
        "--target",
        "--ssh-user",
        "--ssh-key",
        "--recovery-backend",
        "--state-backing-backend",
        "--latency-budget-ms",
        "--report-json",
    ]
    for flag in required_flag_mentions:
        assert flag in doc_text, (
            f"docs/operations/live-vm-acceptance-phase-3b.md §4 missing "
            f"flag mention: {flag!r}"
        )
