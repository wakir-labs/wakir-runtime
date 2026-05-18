# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-50 hermetic suite for the Persona-Engine Boot Self-Test **v2**.

Re-runs every check in ``scripts/persona-engine/boot-self-test-v2.py``
under pytest so CI enforces the same Tag-50 invariants the operator
runs by hand during cutover. The v2 script extends the Tag-48 self-
test (``boot-self-test.py``) with:

  * 15-Crate Cross-Lang-Pin Coverage live in Boot.
  * ENV-Flag-Konsistenz triple-alignment across resolver code,
    manifest §2, and pin-pack ``selector_env`` / ``binary_env`` keys
    (the DRIFT-S4 reconciliation surface).
  * ENV-flip smoke (explicit-python + bogus-value strict-rejection).
  * Cargo.toml <-> pin-pack version alignment.

Hermetic envelope
-----------------

* No network.
* No subprocess for the resolver fan-out (clean env keeps every
  selector at default ``python``); subprocess for the script
  exit-code smoke only.
* No filesystem writes; reads ``MANIFEST-0.5.1-pre-cutover.md`` and
  ``pin-pack-0.5.1-pre-cutover.yaml`` from the repo.
* Deterministic.

Test inventory (>= 15 required per Tag-50 brief)
-------------------------------------------------

The suite delegates to the 22 checks the v2 script defines plus
six suite-level cross-checks (script presence, executable shebang,
end-to-end run, ``main([--quiet])`` exit code, ``--json`` mode shape,
and subprocess exit). Every check in the script's ``CHECKS`` tuple
lands on its own pytest test via parametrisation, so the total test
count is ``len(CHECKS) + len(suite-level wrappers)``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Boot-self-test-v2 module loader.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPO_ROOT / "scripts" / "persona-engine" / "boot-self-test-v2.py"
)


def _load_boot_self_test_v2_module(
    module_name: str = "_pengine_boot_self_test_v2_tag50",
):
    """Load the v2 script as a module (filename has hyphens)."""
    if not SCRIPT_PATH.exists():
        pytest.skip(
            f"boot-self-test-v2 script missing: "
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
def boot_self_test_v2_module():
    return _load_boot_self_test_v2_module()


@pytest.fixture(scope="function")
def clean_wakir_env(monkeypatch):
    """Strip every WAKIR_* env var."""
    for key in list(os.environ):
        if key.startswith("WAKIR_"):
            monkeypatch.delenv(key, raising=False)
    yield


# ---------------------------------------------------------------------------
# Suite-level wrappers.
# ---------------------------------------------------------------------------


def test_v2_script_present_and_executable():
    """The v2 self-test script must live at the documented path."""
    assert SCRIPT_PATH.exists(), (
        f"boot-self-test-v2 script missing: "
        f"{SCRIPT_PATH.relative_to(REPO_ROOT)}"
    )
    shebang = SCRIPT_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "python3" in shebang, f"shebang missing python3: {shebang!r}"


def test_v2_script_check_count_at_least_fifteen(boot_self_test_v2_module):
    """Tag-50 brief floor: >= 15 hermetic checks."""
    checks = boot_self_test_v2_module.CHECKS
    assert (
        len(checks) >= 15
    ), f"boot-self-test-v2 must define >= 15 checks, has {len(checks)}"


def test_v2_script_full_run_passes(
    boot_self_test_v2_module, clean_wakir_env
):
    """End-to-end: invoke run_self_test() and assert all checks pass."""
    report = boot_self_test_v2_module.run_self_test()
    failing = [c.name for c in report.checks if not c.passed]
    assert report.passed, f"failing checks: {failing}"


def test_v2_script_run_via_main_exit_code_zero(
    boot_self_test_v2_module, clean_wakir_env, capsys
):
    """``main(['--quiet'])`` returns 0 on a clean cutover sandbox."""
    rc = boot_self_test_v2_module.main(["--quiet"])
    assert rc == 0


def test_v2_script_json_mode_well_formed(
    boot_self_test_v2_module, clean_wakir_env, capsys
):
    """``--json`` mode emits a parseable report."""
    rc = boot_self_test_v2_module.main(["--json"])
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
    assert report["total_checks"] >= 15
    assert report["total_checks"] == len(report["checks"])
    assert report["failed_checks"] == 0
    # v2-specific baseline string.
    assert "Tag-50" in report["boot_baseline"], (
        f"boot_baseline does not advertise Tag-50: "
        f"{report['boot_baseline']!r}"
    )


def test_v2_script_via_subprocess_exit_code(clean_wakir_env):
    """Invoke as a subprocess (mirrors operator-hand usage)."""
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


def test_v2_script_manifest_version_constant(boot_self_test_v2_module):
    """Pin the manifest-version constant to the Tag-48 anchor."""
    assert (
        boot_self_test_v2_module.EXPECTED_MANIFEST_VERSION
        == "0.5.1-pre-cutover"
    )


def test_v2_script_total_pin_pack_crates_fifteen(boot_self_test_v2_module):
    """Tag-50 brief: 15-crate cardinality is canonical."""
    assert (
        boot_self_test_v2_module.EXPECTED_TOTAL_PIN_PACK_CRATES == 15
    )


def test_v2_script_boot_wired_pinpack_decadent(boot_self_test_v2_module):
    """10 boot-wired pin-pack entries — Tag-48 anchor preserved."""
    assert len(boot_self_test_v2_module.EXPECTED_PIN_PACK_BOOT_WIRED) == 10


def test_v2_script_boot_unwired_pinpack_pentagon(boot_self_test_v2_module):
    """5 boot-unwired pin-pack entries — Phase-3a substrate companions."""
    assert len(boot_self_test_v2_module.EXPECTED_PIN_PACK_UNWIRED) == 5


def test_v2_script_companion_env_set_pinned(boot_self_test_v2_module):
    """DRIFT-S4 surface: 2 companion-crate selector + binary ENVs pinned."""
    selectors = boot_self_test_v2_module.EXPECTED_COMPANION_SELECTOR_ENVS
    bins = boot_self_test_v2_module.EXPECTED_COMPANION_BINARY_ENVS
    assert selectors == (
        "WAKIR_BRIDGE_AUDIT_REPLAY_BACKEND",
        "WAKIR_MIGRATE_VERSION_BACKEND",
    )
    assert bins == (
        "WAKIR_RUST_BRIDGE_AUDIT_REPLAY_BIN",
        "WAKIR_RUST_MIGRATE_VERSION_BIN",
    )


# ---------------------------------------------------------------------------
# Per-check parametrised tests.
# ---------------------------------------------------------------------------


def _load_checks() -> list[tuple[str, Any]]:
    if not SCRIPT_PATH.exists():
        return []
    mod = _load_boot_self_test_v2_module(
        "_pengine_boot_self_test_v2_tag50_param"
    )
    return list(mod.CHECKS)


_PARAM_CHECKS = _load_checks()


@pytest.mark.parametrize(
    "check_name,check_fn",
    _PARAM_CHECKS,
    ids=[name for name, _ in _PARAM_CHECKS],
)
def test_each_v2_boot_self_test_check_passes(
    check_name: str, check_fn, clean_wakir_env
):
    """Run each v2-script-defined check in isolation."""
    passed, detail = check_fn()
    assert passed, f"check {check_name!r} failed: {detail}"
