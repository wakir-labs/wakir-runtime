# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic harness-logic tests for the Sprint-9 Tag-5 disposable-VM
Acceptance-Gate.

The real VM run is Operator-Hand (ADR-0051 sandbox-disziplin); these
tests exercise the *logic* of the harness against synthetic artefacts
so the gate's grading is provably correct before it ever sees a live
smoke run.

Specifically, this module verifies that:

  G1. ``acceptance-gate.sh`` returns 0 when given a clean 6/6-PASS
      smoke JSON and a bootstrap log with no Bug-1 signature.
  G2. The gate returns 2 with a bug-vector classification covering every
      one of the seven 2026-05-13 substance bugs, by feeding a synthetic
      failure scenario per bug.
  G3. The gate returns 3 when required artefacts are missing.
  G4. Bug-1 detection (``sudo bash bash`` resume-hint doubling) trips
      the gate even when the smoke JSON is clean.
  G5. The state-file life cycle (vm-up writes, vm-down clears) is
      idempotent: vm-down.sh against a missing state file exits 0.
  G6. ``vm-down.sh`` parses the DESTROY_HANDLE format for both qemu
      and proxmox providers and dispatches to the right cleanup path
      (verified via a fakebin layer for ``qm``).
  G7. The Ignition template substitutes ``__SSH_PUBKEY__`` and
      ``__HOSTNAME__`` correctly (no orphan placeholders post-render).
  G8. The smoke JSON schema the gate parses matches the schema
      emitted by ``bin/proxmox-bringup-smoke --json``.
  G9. The ``run-acceptance-gate.sh`` flag parser accepts the four
      documented flags and rejects unknown ones.
 G10. The new harness scripts carry the required BSL-1.1 SPDX header.

This is the regression net behind the bug-vector classification: if
the gate's mapping drifts (e.g. someone renames a smoke check), this
suite fails before the gate is run against a live VM.

— Amara
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = REPO_ROOT / "infra" / "test-e2e" / "vm-lifecycle-harness"
GATE_SH = HARNESS_DIR / "acceptance-gate.sh"
VM_DOWN_SH = HARNESS_DIR / "vm-down.sh"
RUN_GATE_SH = HARNESS_DIR / "run-acceptance-gate.sh"
IGNITION_TMPL = HARNESS_DIR / "ignition.bu.tmpl"
SMOKE_BIN = REPO_ROOT / "bin" / "proxmox-bringup-smoke"


# ---------------------------------------------------------------------------
# Synthetic smoke JSON / bootstrap log fixtures
# ---------------------------------------------------------------------------

SMOKE_CHECKS = (
    "quadlet-units-active",
    "nats-jetstream-reachable",
    "spire-server-healthy",
    "spire-agent-healthy",
    "spire-workload-api-reachable",
    "marker-stack-bucket-present",
)


def _make_smoke_json(failed: tuple[str, ...] = ()) -> dict[str, Any]:
    """Build a smoke-JSON payload matching the schema emitted by
    ``bin/proxmox-bringup-smoke --json``."""
    results = []
    pass_n = 0
    fail_n = 0
    for c in SMOKE_CHECKS:
        if c in failed:
            results.append({"name": c, "status": "FAIL", "detail": f"synthetic fail for {c}"})
            fail_n += 1
        else:
            results.append({"name": c, "status": "PASS", "detail": "ok"})
            pass_n += 1
    return {
        "summary": {"pass": pass_n, "fail": fail_n, "total": pass_n + fail_n},
        "results": results,
    }


def _write_artefacts(
    tmp_path: Path,
    *,
    smoke: dict[str, Any] | None,
    bootstrap_rc: int = 0,
    smoke_rc: int | None = None,
    bootstrap_log: str = "ok",
) -> dict[str, Path]:
    """Lay down the three artefact files in a per-test state dir."""
    state = tmp_path / "state"
    state.mkdir()
    if smoke_rc is None:
        smoke_rc = 0 if smoke and smoke["summary"]["fail"] == 0 else 2
    paths = {
        "state_dir": state,
        "smoke_json": state / "smoke-run.json",
        "bootstrap_log": state / "bootstrap-run.log",
        "run_env": state / "run.env",
        "gate_verdict": state / "gate-verdict.json",
    }
    if smoke is not None:
        paths["smoke_json"].write_text(json.dumps(smoke), encoding="utf-8")
    paths["bootstrap_log"].write_text(bootstrap_log, encoding="utf-8")
    paths["run_env"].write_text(
        f"WAKIR_E2E_BOOTSTRAP_RC={bootstrap_rc}\n"
        f"WAKIR_E2E_SMOKE_RC={smoke_rc}\n"
        f"WAKIR_E2E_BOOTSTRAP_LOG={paths['bootstrap_log']}\n"
        f"WAKIR_E2E_SMOKE_JSON={paths['smoke_json']}\n"
        f"WAKIR_E2E_SMOKE_LOG={state / 'smoke-run.log'}\n",
        encoding="utf-8",
    )
    return paths


def _run_gate(paths: dict[str, Path]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["WAKIR_E2E_STATE_DIR"] = str(paths["state_dir"])
    env["WAKIR_E2E_OVERRIDE_SMOKE_JSON"] = str(paths["smoke_json"])
    env["WAKIR_E2E_OVERRIDE_BOOTSTRAP_LOG"] = str(paths["bootstrap_log"])
    env["WAKIR_E2E_OVERRIDE_RUN_ENV"] = str(paths["run_env"])
    env["WAKIR_E2E_OVERRIDE_VERDICT_JSON"] = str(paths["gate_verdict"])
    return subprocess.run(
        ["bash", str(GATE_SH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# G1: clean 6/6 PASS → exit 0
# ---------------------------------------------------------------------------


def test_gate_passes_on_clean_six_of_six(tmp_path: Path) -> None:
    paths = _write_artefacts(
        tmp_path,
        smoke=_make_smoke_json(failed=()),
        bootstrap_rc=0,
        smoke_rc=0,
        bootstrap_log="phase 1..8 ok",
    )
    proc = _run_gate(paths)
    assert proc.returncode == 0, (
        f"gate returned {proc.returncode} on clean inputs; expected 0.\n"
        f"--- stderr ---\n{proc.stderr}"
    )
    verdict = json.loads(paths["gate_verdict"].read_text())
    assert verdict["verdict"] == "PASS"
    assert verdict["pass_count"] == 6
    assert verdict["fail_count"] == 0
    assert verdict["failed_checks"] == []
    assert verdict["bug_vectors"] == []


# ---------------------------------------------------------------------------
# G2: each smoke check failure maps to the right bug vector(s)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("failed_check", "expected_bug_substrings"),
    [
        ("quadlet-units-active",         ["Bug 2", "Bug 5"]),
        ("nats-jetstream-reachable",     ["Bug 6"]),
        ("spire-server-healthy",         ["Bug 7"]),
        ("spire-agent-healthy",          ["Bug 3", "Bug 4"]),
        ("spire-workload-api-reachable", ["Bug 3", "Bug 4", "Bug 7"]),
        ("marker-stack-bucket-present",  ["Bug 6"]),
    ],
)
def test_gate_classifies_failed_check_to_bug_vector(
    tmp_path: Path, failed_check: str, expected_bug_substrings: list[str]
) -> None:
    paths = _write_artefacts(
        tmp_path,
        smoke=_make_smoke_json(failed=(failed_check,)),
        bootstrap_rc=0,
        smoke_rc=2,
    )
    proc = _run_gate(paths)
    assert proc.returncode == 2, (
        f"gate must fail (exit 2) on a smoke failure; got {proc.returncode}.\n"
        f"stderr:\n{proc.stderr}"
    )
    verdict = json.loads(paths["gate_verdict"].read_text())
    assert verdict["verdict"] == "FAIL"
    assert verdict["failed_checks"] == [failed_check]
    bug_text = " ".join(verdict["bug_vectors"])
    for needle in expected_bug_substrings:
        assert needle in bug_text, (
            f"failed check {failed_check!r} did not produce bug vector "
            f"mention of {needle!r}; bug_vectors={verdict['bug_vectors']}"
        )


# ---------------------------------------------------------------------------
# G3: missing artefacts → exit 3
# ---------------------------------------------------------------------------


def test_gate_returns_3_on_missing_smoke_json(tmp_path: Path) -> None:
    paths = _write_artefacts(tmp_path, smoke=_make_smoke_json(), bootstrap_rc=0)
    paths["smoke_json"].unlink()
    proc = _run_gate(paths)
    assert proc.returncode == 3, proc.stderr


def test_gate_returns_3_on_missing_run_env(tmp_path: Path) -> None:
    paths = _write_artefacts(tmp_path, smoke=_make_smoke_json(), bootstrap_rc=0)
    paths["run_env"].unlink()
    proc = _run_gate(paths)
    assert proc.returncode == 3, proc.stderr


def test_gate_returns_3_on_missing_bootstrap_log(tmp_path: Path) -> None:
    paths = _write_artefacts(tmp_path, smoke=_make_smoke_json(), bootstrap_rc=0)
    paths["bootstrap_log"].unlink()
    proc = _run_gate(paths)
    assert proc.returncode == 3, proc.stderr


# ---------------------------------------------------------------------------
# G4: Bug-1 resume-hint detection trips the gate
# ---------------------------------------------------------------------------


def test_gate_fails_when_bootstrap_log_contains_bug1_resume_hint(
    tmp_path: Path,
) -> None:
    """Even with 6/6 PASS, if the bootstrap log shows the Bug-1
    ``sudo bash bash --resume-from`` doubling, the gate must fail —
    because the script is shipping the wrong resume hint to operators.
    """
    paths = _write_artefacts(
        tmp_path,
        smoke=_make_smoke_json(failed=()),
        bootstrap_rc=0,
        smoke_rc=0,
        bootstrap_log=textwrap.dedent(
            """\
            phase 1 ok
            phase 2 ok
            (a failure occurred)
            Resume after fixing the issue:
              sudo bash bash --resume-from 6
            """
        ),
    )
    proc = _run_gate(paths)
    assert proc.returncode == 2, (
        f"gate should fail on Bug-1 resume-hint doubling; got {proc.returncode}\n"
        f"stderr:\n{proc.stderr}"
    )
    assert "Bug 1" in proc.stderr, (
        "gate failure message should mention Bug 1 explicitly; got:\n"
        + proc.stderr
    )


def test_gate_does_not_trip_bug1_on_correct_resume_hint(tmp_path: Path) -> None:
    """The correct resume hint references the installed script path
    (``sudo bash /opt/wakir-runtime/.../wakir-pilot-bootstrap.sh --resume-from N``)
    and must not trip the Bug-1 detector."""
    paths = _write_artefacts(
        tmp_path,
        smoke=_make_smoke_json(failed=()),
        bootstrap_rc=0,
        smoke_rc=0,
        bootstrap_log=textwrap.dedent(
            """\
            phase 1 ok
            Resume after fixing the issue:
              sudo bash /opt/wakir-runtime/infra/spire/federation/wakir-pilot-bootstrap.sh --resume-from 6
            """
        ),
    )
    proc = _run_gate(paths)
    assert proc.returncode == 0, (
        f"gate should pass when resume-hint is correct; got {proc.returncode}\n"
        f"stderr:\n{proc.stderr}"
    )


# ---------------------------------------------------------------------------
# G5: vm-down.sh is idempotent against a missing state file
# ---------------------------------------------------------------------------


def test_vm_down_no_state_is_noop_success(tmp_path: Path) -> None:
    state = tmp_path / "empty-state"
    state.mkdir()
    env = os.environ.copy()
    env["WAKIR_E2E_STATE_DIR"] = str(state)
    proc = subprocess.run(
        ["bash", str(VM_DOWN_SH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    assert "nothing to tear down" in proc.stderr.lower() or "complete" in proc.stderr.lower()


# ---------------------------------------------------------------------------
# G6: vm-down.sh dispatches on DESTROY_HANDLE provider
# ---------------------------------------------------------------------------


def test_vm_down_dispatches_proxmox_via_fake_qm(tmp_path: Path) -> None:
    """If DESTROY_HANDLE = ``proxmox:<vmid>`` and ``qm`` is on PATH,
    vm-down.sh must invoke ``qm stop <vmid>`` and ``qm destroy <vmid>``.
    We feed it a fake ``qm`` that logs every call.
    """
    state = tmp_path / "state"
    state.mkdir()
    state_file = state / "vm.env"
    state_file.write_text(
        textwrap.dedent(
            """\
            WAKIR_E2E_VM_NAME=wakir-pilot-e2e-fake
            WAKIR_E2E_VM_PROVIDER=proxmox
            WAKIR_E2E_VM_IP=10.0.0.42
            WAKIR_E2E_SSH_KEY=/dev/null
            WAKIR_E2E_DESTROY_HANDLE=proxmox:999
            WAKIR_E2E_STATE_DIR=%s
            """
            % state
        ),
        encoding="utf-8",
    )
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    call_log = tmp_path / "qm-calls.log"
    qm = fakebin / "qm"
    qm.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            echo "$@" >> "{call_log}"
            exit 0
            """
        )
    )
    qm.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fakebin}:{env.get('PATH','')}"
    env["WAKIR_E2E_STATE_DIR"] = str(state)
    proc = subprocess.run(
        ["bash", str(VM_DOWN_SH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    calls = call_log.read_text(encoding="utf-8").strip().splitlines()
    joined = "\n".join(calls)
    assert any("stop 999" in c for c in calls), f"no qm stop call:\n{joined}"
    assert any("destroy 999" in c for c in calls), f"no qm destroy call:\n{joined}"
    # State file should be removed on success.
    assert not state_file.exists(), "vm-down.sh did not clean up state file"


def test_vm_down_dispatches_qemu_with_pidfile_cleanup(tmp_path: Path) -> None:
    """If DESTROY_HANDLE = ``qemu:<pidfile>:<disk>:<ign>`` then the disk
    + ignition files must be removed even when the pidfile points at a
    non-running pid (graceful handling of a stale state)."""
    state = tmp_path / "state"
    state.mkdir()
    disk = state / "fake.qcow2"
    ign = state / "fake.ign"
    pidfile = state / "fake.pid"
    disk.write_text("dummy-disk")
    ign.write_text("dummy-ign")
    # pid that's almost certainly not a running process. We pick a
    # very-high number that's invalid on most kernels.
    pidfile.write_text("4000000\n")
    state_file = state / "vm.env"
    state_file.write_text(
        textwrap.dedent(
            f"""\
            WAKIR_E2E_VM_NAME=wakir-pilot-e2e-fake
            WAKIR_E2E_VM_PROVIDER=qemu
            WAKIR_E2E_VM_IP=127.0.0.1
            WAKIR_E2E_SSH_KEY=/dev/null
            WAKIR_E2E_DESTROY_HANDLE=qemu:{pidfile}:{disk}:{ign}
            WAKIR_E2E_STATE_DIR={state}
            """
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["WAKIR_E2E_STATE_DIR"] = str(state)
    proc = subprocess.run(
        ["bash", str(VM_DOWN_SH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    assert not disk.exists(), "vm-down.sh did not remove the qemu disk"
    assert not ign.exists(), "vm-down.sh did not remove the ignition file"
    assert not pidfile.exists(), "vm-down.sh did not remove the pidfile"


# ---------------------------------------------------------------------------
# G7: Ignition template substitutes both placeholders
# ---------------------------------------------------------------------------


def test_ignition_template_substitution_leaves_no_placeholders() -> None:
    txt = IGNITION_TMPL.read_text(encoding="utf-8")
    # Simulate the same sed vm-up.sh does.
    substituted = (
        txt.replace("__SSH_PUBKEY__", "ssh-ed25519 AAAA... wakir-test")
           .replace("__HOSTNAME__", "wakir-pilot-e2e-2026-05-13T20-00-00Z")
    )
    assert "__SSH_PUBKEY__" not in substituted, (
        "post-render still has __SSH_PUBKEY__ placeholder"
    )
    assert "__HOSTNAME__" not in substituted, (
        "post-render still has __HOSTNAME__ placeholder"
    )
    assert "ssh-ed25519 AAAA... wakir-test" in substituted
    assert "wakir-pilot-e2e-2026-05-13T20-00-00Z" in substituted


def test_ignition_template_is_a_butane_fcos_1_5_doc() -> None:
    """The template must declare ``variant: fcos`` and a valid Butane
    version line. If someone tweaks it to a flavour butane cannot
    render, the harness silently degrades."""
    txt = IGNITION_TMPL.read_text(encoding="utf-8")
    assert "variant: fcos" in txt
    assert "version: 1.5.0" in txt


# ---------------------------------------------------------------------------
# G8: gate parses the exact schema that proxmox-bringup-smoke emits
# ---------------------------------------------------------------------------


def test_smoke_bin_json_schema_matches_gate_expectations() -> None:
    """The schema the smoke script emits is the contract the gate
    parses. If the smoke binary's JSON-emission block drifts, the gate
    silently regresses to "always FAIL" or worse "always PASS"."""
    src = SMOKE_BIN.read_text(encoding="utf-8")
    # All the keys the gate's python parser reads:
    for key in (
        '"summary"',
        '"pass"',
        '"fail"',
        '"total"',
        '"results"',
        '"name"',
        '"status"',
        '"detail"',
    ):
        assert key in src, (
            f"proxmox-bringup-smoke no longer emits {key!r} in its --json "
            "output; acceptance-gate.sh will silently misclassify. Re-align "
            "the gate's parser or restore the schema."
        )


def test_gate_check_to_bug_mapping_covers_all_six_smoke_checks() -> None:
    """Every check that proxmox-bringup-smoke emits MUST appear in the
    gate's CHECK_TO_BUGS map; otherwise a failure of a check would be
    classified as ``unknown check``.
    """
    gate_src = GATE_SH.read_text(encoding="utf-8")
    smoke_src = SMOKE_BIN.read_text(encoding="utf-8")
    # Smoke check names appear in lines like:  RESULTS_NAME+=("quadlet-units-active")
    expected = SMOKE_CHECKS
    for c in expected:
        # The mapping in the gate uses single-quoted Python dict keys
        # which become "<name>" inside the python heredoc. Substring
        # match is sufficient.
        assert f'"{c}"' in gate_src, (
            f"smoke check {c!r} is not present in acceptance-gate.sh's "
            "CHECK_TO_BUGS map. Add the bug-vector for it."
        )
        assert c in smoke_src, (
            f"smoke check {c!r} not found in proxmox-bringup-smoke source; "
            "either the check was renamed (update the gate map) or this "
            "test's SMOKE_CHECKS list is stale."
        )


# ---------------------------------------------------------------------------
# G9: run-acceptance-gate.sh flag parser
# ---------------------------------------------------------------------------


def test_run_gate_help_flag_documents_all_flags() -> None:
    proc = subprocess.run(
        ["bash", str(RUN_GATE_SH), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    for flag in ("--org", "--branch", "--provider", "--no-teardown"):
        assert flag in proc.stdout, f"--help missing {flag}"


def test_run_gate_unknown_flag_rejected() -> None:
    proc = subprocess.run(
        ["bash", str(RUN_GATE_SH), "--definitely-not-a-flag"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode != 0, "unknown flag must not be silently accepted"
    assert "unknown flag" in proc.stderr.lower()


# ---------------------------------------------------------------------------
# G10: BSL-1.1 header coverage on new harness scripts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        "infra/test-e2e/vm-lifecycle-harness/vm-up.sh",
        "infra/test-e2e/vm-lifecycle-harness/vm-down.sh",
        "infra/test-e2e/vm-lifecycle-harness/vm-bringup-run.sh",
        "infra/test-e2e/vm-lifecycle-harness/acceptance-gate.sh",
        "infra/test-e2e/vm-lifecycle-harness/run-acceptance-gate.sh",
        "infra/test-e2e/vm-lifecycle-harness/ignition.bu.tmpl",
        "infra/test-e2e/vm-lifecycle-harness/README.md",
        ".github/workflows/e2e-vm-acceptance-gate.yml",
    ],
)
def test_harness_scripts_carry_busl_header(rel: str) -> None:
    path = REPO_ROOT / rel
    assert path.exists(), f"missing harness file: {rel}"
    head = path.read_text(encoding="utf-8", errors="replace").splitlines()[:15]
    head_text = "\n".join(head)
    # REUSE-IgnoreStart
    assert "SPDX-License-Identifier: BUSL-1.1" in head_text, (
        f"{rel} must carry BUSL-1.1 per ADR-0059 + sprint-9-tag-5 brief"
    )
    # REUSE-IgnoreEnd


# ---------------------------------------------------------------------------
# G11: acceptance-gate.sh + run-acceptance-gate.sh are executable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        "infra/test-e2e/vm-lifecycle-harness/vm-up.sh",
        "infra/test-e2e/vm-lifecycle-harness/vm-down.sh",
        "infra/test-e2e/vm-lifecycle-harness/vm-bringup-run.sh",
        "infra/test-e2e/vm-lifecycle-harness/acceptance-gate.sh",
        "infra/test-e2e/vm-lifecycle-harness/run-acceptance-gate.sh",
    ],
)
def test_harness_shell_scripts_are_executable(rel: str) -> None:
    path = REPO_ROOT / rel
    assert path.exists(), f"missing: {rel}"
    mode = path.stat().st_mode
    assert mode & 0o111, f"{rel} is not executable (mode={oct(mode)})"
