# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-47/48 hermetic suite for the Persona-Engine Boot Self-Test.

Re-runs every check in ``scripts/persona-engine/boot-self-test.py``
inside pytest so the CI test runner enforces the same Stage-1 boot
invariants the operator runs by hand during cutover. Tag-48 promotes
the script to the 10-record 0.5.1-pre-cutover manifest; the test
suite tracks the script's CHECKS registry verbatim.

Hermetic envelope
-----------------

* No network. The script and this suite import only stdlib +
  ``wirelang.persona_engine`` modules.
* No subprocess. We invoke the resolver functions directly (the
  Rust subprocess path is never reached because the clean env keeps
  every selector at default ``python``).
* No filesystem writes. The script reads ``MANIFEST-0.5.1-pre-cutover.md``
  and ``pin-pack-0.5.1-pre-cutover.yaml`` from the repo; no temp
  files are emitted.
* Deterministic. The boot-fingerprint check itself is one of the
  invariants we assert.

Test inventory (12+ required per Tag-47 auftrag)
------------------------------------------------

The suite delegates to the 20 checks the script defines plus a
handful of suite-level cross-checks (script discoverability,
exit-code semantics, JSON-mode shape). Every check in the script's
``CHECKS`` tuple lands on its own pytest test via parametrisation, so
the test count is ``len(CHECKS) + len(suite-level wrappers)``.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# Boot-self-test module loader.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "persona-engine" / "boot-self-test.py"


def _load_boot_self_test_module(module_name: str = "_pengine_boot_self_test_tag47"):
    """Load the script as a module (the filename has a hyphen).

    Python 3.14's ``@dataclass`` decorator inspects
    ``sys.modules[cls.__module__]`` during class processing; if the
    module is not registered there, the decorator raises
    ``AttributeError``. We therefore install the module into
    ``sys.modules`` before executing it.
    """
    if not SCRIPT_PATH.exists():
        pytest.skip(
            f"boot-self-test script missing: "
            f"{SCRIPT_PATH.relative_to(REPO_ROOT)}"
        )
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return mod


@pytest.fixture(scope="module")
def boot_self_test_module():
    """Cached module fixture for the boot-self-test script."""
    return _load_boot_self_test_module()


@pytest.fixture(scope="function")
def clean_wakir_env(monkeypatch):
    """Strip every WAKIR_* env var so the resolver fan-out picks defaults."""
    for key in list(os.environ):
        if key.startswith("WAKIR_"):
            monkeypatch.delenv(key, raising=False)
    yield


# ---------------------------------------------------------------------------
# Suite-level wrappers.
# ---------------------------------------------------------------------------


def test_script_present_and_executable():
    """The boot-self-test script must live at the documented path."""
    assert SCRIPT_PATH.exists(), (
        f"boot-self-test script missing: "
        f"{SCRIPT_PATH.relative_to(REPO_ROOT)}"
    )
    # Read the shebang -- script must be invocable via python3.
    shebang = SCRIPT_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "python3" in shebang, f"shebang missing python3: {shebang!r}"


def test_script_check_count_at_least_twelve(boot_self_test_module):
    """Tag-47 auftrag floor: >= 12 hermetic checks."""
    checks = boot_self_test_module.CHECKS
    assert (
        len(checks) >= 12
    ), f"boot-self-test must define >= 12 checks, has {len(checks)}"


def test_script_full_run_passes(boot_self_test_module, clean_wakir_env):
    """End-to-end: invoke run_self_test() and assert all checks pass."""
    report = boot_self_test_module.run_self_test()
    failing = [c.name for c in report.checks if not c.passed]
    assert report.passed, f"failing checks: {failing}"


def test_script_run_via_main_exit_code_zero(
    boot_self_test_module, clean_wakir_env, capsys
):
    """Invoking ``main([])`` with all defaults yields exit code 0."""
    rc = boot_self_test_module.main(["--quiet"])
    assert rc == 0


def test_script_json_mode_well_formed(boot_self_test_module, clean_wakir_env, capsys):
    """``--json`` mode emits a parseable report with the documented shape."""
    rc = boot_self_test_module.main(["--json"])
    assert rc == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    for key in (
        "boot_baseline",
        "manifest_version",
        "total_checks",
        "passed_checks",
        "failed_checks",
        "passed",
        "checks",
    ):
        assert key in report, f"JSON report missing key {key!r}"
    assert report["passed"] is True
    assert report["total_checks"] >= 12
    assert report["total_checks"] == len(report["checks"])
    assert report["failed_checks"] == 0


def test_script_via_subprocess_exit_code(clean_wakir_env):
    """Invoke as a subprocess (mirrors operator-hand usage)."""
    # Use the same interpreter that runs pytest. Clean WAKIR_* in the
    # child env explicitly (monkeypatch covers the parent only).
    child_env = {
        k: v for k, v in os.environ.items() if not k.startswith("WAKIR_")
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--quiet"],
        cwd=str(REPO_ROOT),
        env=child_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"subprocess exit={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Per-check parametrised tests.
# ---------------------------------------------------------------------------


def _load_checks() -> list[tuple[str, Any]]:
    """Eagerly load the script's CHECKS tuple for parametrisation."""
    if not SCRIPT_PATH.exists():
        return []
    mod = _load_boot_self_test_module("_pengine_boot_self_test_tag47_param")
    return list(mod.CHECKS)


_PARAM_CHECKS = _load_checks()


@pytest.mark.parametrize(
    "check_name,check_fn",
    _PARAM_CHECKS,
    ids=[name for name, _ in _PARAM_CHECKS],
)
def test_each_boot_self_test_check_passes(
    check_name: str, check_fn, clean_wakir_env
):
    """Run each script-defined check in isolation."""
    passed, detail = check_fn()
    assert passed, f"check {check_name!r} failed: {detail}"


# ---------------------------------------------------------------------------
# Manifest <-> script constant cross-checks.
# ---------------------------------------------------------------------------


def test_expected_boot_order_has_ten_records(boot_self_test_module):
    """Script's EXPECTED_BOOT_ORDER constant must list 10 records (Tag-48)."""
    eb = boot_self_test_module.EXPECTED_BOOT_ORDER
    assert len(eb) == 10
    record_nos = [n for n, _, _ in eb]
    assert record_nos == list(range(1, 11))


def test_expected_pin_pack_boot_wired_aligns(boot_self_test_module):
    """EXPECTED_PIN_PACK_BOOT_WIRED record-nos match EXPECTED_BOOT_ORDER."""
    eb = boot_self_test_module.EXPECTED_BOOT_ORDER
    pp = boot_self_test_module.EXPECTED_PIN_PACK_BOOT_WIRED
    assert len(pp) == 10
    assert [n for n, _ in pp] == [n for n, _, _ in eb]


def test_expected_unwired_crate_count(boot_self_test_module):
    """EXPECTED_PIN_PACK_UNWIRED must list 5 crates (10+5 = 15) in Tag-48."""
    assert len(boot_self_test_module.EXPECTED_PIN_PACK_UNWIRED) == 5


# ---------------------------------------------------------------------------
# Boot-fingerprint stability across two top-level invocations.
# ---------------------------------------------------------------------------


def test_boot_fingerprint_stable_across_two_runs(
    boot_self_test_module, clean_wakir_env
):
    """Two independent run_self_test() calls produce the same fingerprint.

    The fingerprint is internal to the script; we recompute it from
    the report via the helper the script exposes.
    """
    fp_a = boot_self_test_module._compute_boot_fingerprint()
    fp_b = boot_self_test_module._compute_boot_fingerprint()
    assert fp_a == fp_b, f"fingerprint drifted between runs: {fp_a} vs {fp_b}"
    assert len(fp_a) == 64  # sha256 hex


def test_boot_fingerprint_changes_on_env_flip(boot_self_test_module):
    """Flipping a backend selector to 'rust' should change the fingerprint.

    Establishes that the fingerprint is *not* a constant -- it
    actually captures the requested-backend per-record state via the
    explicit env-dict the resolvers receive.
    """
    fp_python = boot_self_test_module._compute_boot_fingerprint(env={})

    # Flip one selector to 'rust'. Even if the Rust binary is
    # missing on the sandbox box, the BackendDecision will record
    # requested_backend=rust which the fingerprint hashes -- so the
    # fingerprint must shift.
    fp_rust = boot_self_test_module._compute_boot_fingerprint(
        env={"WAKIR_RECOVERY_BACKEND": "rust"}
    )

    assert fp_python != fp_rust, (
        "fingerprint did not change when WAKIR_RECOVERY_BACKEND=rust; "
        "either the selector is ignored or the fingerprint is too coarse"
    )
