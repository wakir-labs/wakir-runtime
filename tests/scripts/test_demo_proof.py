# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors

"""Tests for scripts/demo-proof.sh + scripts/demo_proof_helpers.py.

Three layers:

1. **Python helper layer.** Each ``do_*`` function runs end-to-end
   against a temp working directory with the real ``wat`` modules in
   the loop. If a refactor breaks the bridge/aggregator contract,
   these catch it.

2. **Driver layer.** The bash driver is executed as a subprocess. It
   needs only bash + python3, so these tests run everywhere — with or
   without ``jq`` on PATH (one test proves jq is never invoked).
   Fault injection goes through ``DEMO_PROOF_FAIL_STEP`` and the
   ``wakir_verify``-absent simulation through
   ``DEMO_PROOF_SIMULATE_NO_WAKIR_VERIFY``; both are honoured only
   under ``DEMO_PROOF_TEST_MODE=1``.

3. **Proof-format layer.** ``proof.json`` is validated against
   ``wirelang/schemas/wakir-inclusion-proof-v1.json`` and the root is
   recomputed from the sibling path with nothing but ``hashlib``.

The regression tests for the sealed driver bugs (ADR-0072 4a) are
marked ``# regression: F<n>`` after the fix-list numbering.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPERS_PATH = REPO_ROOT / "scripts" / "demo_proof_helpers.py"
SHELL_DRIVER_PATH = REPO_ROOT / "scripts" / "demo-proof.sh"
PROOF_SCHEMA_PATH = REPO_ROOT / "wirelang" / "schemas" / "wakir-inclusion-proof-v1.json"

HOUR = "2026-05-17T12"
STEP_NAMES = [
    "protocol_event",
    "runtime_bridge",
    "merkle_manifest",
    "inclusion_proof",
    "external_verify",
]


def _load_helpers():
    """Import the helpers module under a stable dotted name.

    ``scripts/`` has no ``__init__.py`` on purpose; load by path.
    """
    spec = importlib.util.spec_from_file_location("demo_proof_helpers", HELPERS_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


helpers = _load_helpers()


# ---------------------------------------------------------------------------
# Shared fixtures and driver runner
# ---------------------------------------------------------------------------


@pytest.fixture
def demo_dir(tmp_path: Path) -> Path:
    (tmp_path / "spool").mkdir()
    return tmp_path


@pytest.fixture
def event_artifacts(demo_dir: Path) -> Dict[str, Any]:
    out = demo_dir / "event.json"
    hash_out = demo_dir / "event.sha256"
    envelope = helpers.do_build_event(hour=HOUR, out=out, hash_out=hash_out)
    return {
        "envelope": envelope,
        "out": out,
        "hash_out": hash_out,
        "payload_hash": hash_out.read_text(encoding="utf-8"),
    }


def _run_pipeline(demo_dir: Path, *, simulate_missing_verify: bool = True) -> Dict[str, Any]:
    """Drive all five steps in-process via the helper surface."""
    out = demo_dir / "event.json"
    hash_out = demo_dir / "event.sha256"
    envelope = helpers.do_build_event(hour=HOUR, out=out, hash_out=hash_out)
    bridge_result = helpers.do_run_bridge(
        payload=out,
        payload_hash=hash_out.read_text(encoding="utf-8"),
        spool_root=demo_dir / "spool",
        activity_log=demo_dir / "activity-log.md",
        event_time=f"{HOUR}:00:00Z",
        out=demo_dir / "bridge-result.json",
    )
    manifest_out = demo_dir / HOUR / "manifest.json"
    manifest = helpers.do_build_manifest(
        spool_root=demo_dir / "spool",
        hour=HOUR,
        aggregator_input=demo_dir / "manifest-input.jsonl",
        manifest_out=manifest_out,
    )
    proof_out = demo_dir / "proof.json"
    proof = helpers.do_verify_proof(manifest=manifest_out, event=out, out=proof_out)
    external = helpers.do_external_verify(
        manifest=manifest_out,
        proof=proof_out,
        out=demo_dir / "verify-result.json",
        simulate_missing=simulate_missing_verify,
    )
    return {
        "envelope": envelope,
        "bridge_result": bridge_result,
        "manifest": manifest,
        "manifest_path": manifest_out,
        "proof": proof["proof"],
        "verified": proof["verified"],
        "proof_path": proof_out,
        "external": external,
    }


def _driver_env(
    workdir: Path,
    *,
    path: Optional[str] = None,
    test_mode: bool = True,
    simulate_no_verify: bool = True,
    **extra: str,
) -> Dict[str, str]:
    """Environment for a hermetic driver run.

    ``python3`` must resolve to the interpreter running pytest so the
    driver sees the same site-packages (venv or not).
    """
    env = os.environ.copy()
    interp_dir = str(Path(sys.executable).parent)
    env["PATH"] = f"{interp_dir}:{path if path is not None else env.get('PATH', '')}"
    env["DEMO_PROOF_WORKDIR"] = str(workdir)
    env["DEMO_PROOF_HOUR"] = HOUR
    env["DEMO_PROOF_VERIFY_ONLINE"] = "0"
    env["DEMO_PROOF_TEST_MODE"] = "1" if test_mode else "0"
    env["DEMO_PROOF_SIMULATE_NO_WAKIR_VERIFY"] = "1" if simulate_no_verify else "0"
    env.pop("DEMO_PROOF_FAIL_STEP", None)
    env.pop("DEMO_PROOF_OTS_PROOF", None)
    env.update(extra)
    return env


def _run_driver(env: Dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SHELL_DRIVER_PATH)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _report(completed: subprocess.CompletedProcess) -> Dict[str, Any]:
    assert completed.stdout.strip(), f"driver printed no report\nstderr:\n{completed.stderr}"
    return json.loads(completed.stdout)


def _minimal_path(tmp_path: Path, *, with_jq_poison: bool) -> str:
    """A PATH containing only what the driver legitimately needs."""
    bin_dir = tmp_path / "minbin"
    bin_dir.mkdir()
    for tool in ("bash", "mkdir", "cat", "dirname", "mktemp", "git"):
        real = shutil.which(tool)
        if real:
            os.symlink(real, bin_dir / tool)
    if with_jq_poison:
        shim = bin_dir / "jq"
        shim.write_text("#!/usr/bin/env bash\necho 'jq must not be called' >&2\nexit 99\n")
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return str(bin_dir)


def _recompute_root(leaf_hash_hex: str, siblings: List[Dict[str, str]]) -> str:
    """Independent verifier: stdlib SHA-256 over the sibling path."""
    current = bytes.fromhex(leaf_hash_hex)
    for sibling in siblings:
        sib = bytes.fromhex(sibling["hash"])
        if sibling["side"] == "L":
            current = hashlib.sha256(sib + current).digest()
        elif sibling["side"] == "R":
            current = hashlib.sha256(current + sib).digest()
        else:
            raise AssertionError(f"bad side {sibling['side']!r}")
    return current.hex()


# ---------------------------------------------------------------------------
# Helper layer
# ---------------------------------------------------------------------------


def test_helpers_module_loads_and_exports_surface():
    expected = {
        "do_build_event",
        "do_run_bridge",
        "do_build_manifest",
        "do_verify_proof",
        "do_local_root_check",
        "do_external_verify",
        "do_emit_step",
        "do_assemble_report",
        "do_json_get",
        "aggregate_exit_code",
        "build_parser",
        "main",
    }
    missing = expected - set(helpers.__all__)
    assert not missing, f"helpers.__all__ missing: {missing}"
    for name in expected:
        assert hasattr(helpers, name)
    assert tuple(STEP_NAMES) == helpers.STEP_NAMES


def test_step1_build_event_produces_deterministic_payload_hash(demo_dir: Path):
    a = helpers.do_build_event(hour=HOUR, out=demo_dir / "a" / "event.json", hash_out=demo_dir / "a" / "h")
    b = helpers.do_build_event(hour=HOUR, out=demo_dir / "b" / "event.json", hash_out=demo_dir / "b" / "h")
    assert a["payload_hash"] == b["payload_hash"]
    assert (demo_dir / "a" / "event.json").read_bytes() == (demo_dir / "b" / "event.json").read_bytes()
    assert (demo_dir / "a" / "event.envelope.json").exists()


def test_step1_rejects_malformed_hour_slot(demo_dir: Path):
    with pytest.raises(ValueError, match="YYYY-MM-DDTHH"):
        helpers.do_build_event(hour="2026/05/17 12", out=demo_dir / "e.json", hash_out=demo_dir / "h")


def test_step2_run_bridge_emits_status_ok_and_creates_spool(demo_dir: Path, event_artifacts: Dict[str, Any]):
    result = helpers.do_run_bridge(
        payload=event_artifacts["out"],
        payload_hash=event_artifacts["payload_hash"],
        spool_root=demo_dir / "spool",
        activity_log=demo_dir / "activity-log.md",
        event_time=f"{HOUR}:00:00Z",
        out=demo_dir / "bridge-result.json",
    )
    assert result["status"] == "ok"
    assert result["error"] == ""
    assert (demo_dir / "spool" / "demo" / f"{HOUR}.jsonl").exists()
    assert (demo_dir / "activity-log.md").exists()
    assert json.loads((demo_dir / "bridge-result.json").read_text())["status"] == "ok"


def test_step3_build_manifest_records_payload_hash_from_step1(demo_dir: Path, event_artifacts: Dict[str, Any]):
    helpers.do_run_bridge(
        payload=event_artifacts["out"],
        payload_hash=event_artifacts["payload_hash"],
        spool_root=demo_dir / "spool",
        activity_log=demo_dir / "activity-log.md",
        event_time=f"{HOUR}:00:00Z",
        out=demo_dir / "bridge-result.json",
    )
    manifest = helpers.do_build_manifest(
        spool_root=demo_dir / "spool",
        hour=HOUR,
        aggregator_input=demo_dir / "manifest-input.jsonl",
        manifest_out=demo_dir / HOUR / "manifest.json",
    )
    assert manifest["event_count"] == 1
    assert len(manifest["merkle_root"]) == 64
    assert event_artifacts["payload_hash"] in [ev["payload_hash"] for ev in manifest["events"]]


def test_step3_raises_when_spool_missing(demo_dir: Path):
    with pytest.raises(FileNotFoundError):
        helpers.do_build_manifest(
            spool_root=demo_dir / "nope",
            hour=HOUR,
            aggregator_input=demo_dir / "agg.jsonl",
            manifest_out=demo_dir / "manifest.json",
        )


def test_step4_verify_proof_returns_verified_true(demo_dir: Path):
    results = _run_pipeline(demo_dir)
    assert results["verified"] is True
    proof = results["proof"]
    assert proof["schema"] == "wakir-inclusion-proof/v1"
    assert proof["leaf_index"] == 0
    assert proof["leaf_count"] == 1
    assert proof["siblings"] == []  # single-leaf tree
    assert proof["leaf_hash"] == proof["merkle_root"]
    assert "verified" not in proof  # verdict is not part of the artefact


def test_step4_raises_when_payload_hash_drifts(demo_dir: Path):
    results = _run_pipeline(demo_dir)
    envelope_path = (demo_dir / "event.json").with_suffix(".envelope.json")
    envelope = json.loads(envelope_path.read_text())
    envelope["payload_hash"] = "deadbeef" * 8
    envelope_path.write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match="not found in manifest"):
        helpers.do_verify_proof(manifest=results["manifest_path"], event=demo_dir / "event.json", out=demo_dir / "p2.json")


def test_step5_local_root_check_matches_and_flags_mismatch(demo_dir: Path):
    results = _run_pipeline(demo_dir)
    ok = helpers.do_local_root_check(manifest=results["manifest_path"])
    assert ok["root_ok"] is True
    blob = json.loads(results["manifest_path"].read_text())
    blob["merkle_root"] = "00" * 32
    results["manifest_path"].write_text(json.dumps(blob))
    bad = helpers.do_local_root_check(manifest=results["manifest_path"])
    assert bad["root_ok"] is False


def test_end_to_end_python_pipeline_chains_all_five_steps(demo_dir: Path):
    results = _run_pipeline(demo_dir)
    assert results["bridge_result"]["status"] == "ok"
    assert results["manifest"]["event_count"] == 1
    assert results["verified"] is True
    assert results["external"]["status"] == "skipped"  # simulated-missing library
    assert results["external"]["local_root_rederived"] is True


# ---------------------------------------------------------------------------
# Regression: F1 — details JSON with braces survive emit-step
# ---------------------------------------------------------------------------


def test_details_with_braces_survive(tmp_path: Path):  # regression: F1
    """The old bash default ``"${4:-{}}"`` appended a stray ``}``.

    Nested objects, arrays, and empty details must all round-trip
    through the helper and through the CLI surface the driver uses.
    """
    steps_file = tmp_path / ".steps.jsonl"
    nested = {"a": {"b": 1}, "list": [{"x": "}"}, "{"], "empty": {}}
    helpers.do_emit_step(
        steps_file=steps_file, name="protocol_event", status="ok", code=0,
        details_json=json.dumps(nested),
    )
    completed = subprocess.run(
        [sys.executable, str(HELPERS_PATH), "emit-step", "--steps-file", str(steps_file),
         "--name", "runtime_bridge", "--status", "ok", "--code", "0",
         "--details-json", '{"a":{"b":1}}'],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    helpers.do_emit_step(steps_file=steps_file, name="merkle_manifest", status="ok", code=0)
    records = [json.loads(line) for line in steps_file.read_text().splitlines()]
    assert records[0]["details"] == nested
    assert records[1]["details"] == {"a": {"b": 1}}
    assert records[2]["details"] == {}


def test_emit_step_rejects_inconsistent_status_and_code(tmp_path: Path):
    with pytest.raises(ValueError, match="does not match"):
        helpers.do_emit_step(steps_file=tmp_path / "s", name="protocol_event", status="ok", code=10)
    with pytest.raises(ValueError, match="unknown step name"):
        helpers.do_emit_step(steps_file=tmp_path / "s", name="bogus", status="ok", code=0)
    with pytest.raises(ValueError, match="JSON object"):
        helpers.do_emit_step(steps_file=tmp_path / "s", name="protocol_event", status="ok", code=0, details_json="[1]")


# ---------------------------------------------------------------------------
# Regression: F3 / F11 — no jq
# ---------------------------------------------------------------------------


def test_driver_runs_without_jq(tmp_path: Path):  # regression: F3
    """PATH holds only bash, coreutils, git and python3 — no jq anywhere."""
    workdir = tmp_path / "work"
    env = _driver_env(workdir, path=_minimal_path(tmp_path, with_jq_poison=False))
    assert shutil.which("jq", path=env["PATH"]) is None
    completed = _run_driver(env)
    assert completed.returncode == 0, f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    report = _report(completed)
    assert report["schema"] == "wakir-demo-proof/v1"
    assert [s["name"] for s in report["steps"]] == STEP_NAMES


def test_driver_never_invokes_jq_when_present(tmp_path: Path):  # regression: F3, F11
    """A poison ``jq`` on PATH exits 99; a single call would fail a step."""
    workdir = tmp_path / "work"
    env = _driver_env(workdir, path=_minimal_path(tmp_path, with_jq_poison=True))
    assert shutil.which("jq", path=env["PATH"]) is not None
    completed = _run_driver(env)
    assert completed.returncode == 0, f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    assert "jq must not be called" not in completed.stderr
    report = _report(completed)
    assert all(s["status"] in ("ok", "skipped") for s in report["steps"])


# ---------------------------------------------------------------------------
# Regression: F2 / F4 / F9 — rc propagation, short-circuit, five steps always
# ---------------------------------------------------------------------------


def test_hard_failure_propagates_exit_code(tmp_path: Path):  # regression: F2, F4, F9
    """``if ! step`` used to zero the return code; exit was always 0."""
    completed = _run_driver(_driver_env(tmp_path / "w", DEMO_PROOF_FAIL_STEP="step3_merkle_manifest"))
    assert completed.returncode == 10, f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    report = _report(completed)
    by_name = {s["name"]: s for s in report["steps"]}
    assert by_name["protocol_event"]["status"] == "ok"
    assert by_name["runtime_bridge"]["status"] == "ok"
    assert by_name["merkle_manifest"]["status"] == "failed"
    assert by_name["merkle_manifest"]["exit_code"] == 10
    assert by_name["merkle_manifest"]["details"]["fault_injected"] == "true"
    for name in ("inclusion_proof", "external_verify"):
        assert by_name[name]["status"] == "not_run"
        assert by_name[name]["exit_code"] == 30
        assert "step3_merkle_manifest" in by_name[name]["details"]["reason"]
    assert report["exit_code"] == 10
    assert not (tmp_path / "w" / HOUR / "manifest.json").exists()  # step 3 really did not run


def test_report_always_has_five_named_steps_in_order(tmp_path: Path):  # regression: F4
    for fail_step in (None, "step1_protocol_event", "step5_external_verify"):
        extra = {"DEMO_PROOF_FAIL_STEP": fail_step} if fail_step else {}
        completed = _run_driver(_driver_env(tmp_path / f"w-{fail_step}", **extra))
        report = _report(completed)
        names = [s["name"] for s in report["steps"]]
        assert names == STEP_NAMES, f"fail_step={fail_step}: {names}"
        for step in report["steps"]:
            assert set(step) == {"name", "status", "exit_code", "details"}
            assert step["status"] in {"ok", "failed", "skipped", "not_run"}
            assert isinstance(step["details"], dict)
        assert completed.returncode == (10 if fail_step else 0)


def test_fault_injection_ignored_without_test_mode(tmp_path: Path):
    """Production runs must not react to the test hooks."""
    env = _driver_env(tmp_path / "w", test_mode=False, DEMO_PROOF_FAIL_STEP="step3_merkle_manifest")
    completed = _run_driver(env)
    assert completed.returncode == 0, completed.stderr
    report = _report(completed)
    assert report["steps"][2]["status"] == "ok"
    assert "fault_injected" not in report["steps"][2]["details"]


# ---------------------------------------------------------------------------
# Regression: F5 / F6 / F8 — external_verify semantics
# ---------------------------------------------------------------------------


def test_external_verify_skipped_with_reason_when_verify_absent(tmp_path: Path):  # regression: F5, F8
    completed = _run_driver(_driver_env(tmp_path / "w", simulate_no_verify=True))
    assert completed.returncode == 0, completed.stderr  # skipped never fails the demo
    step5 = _report(completed)["steps"][-1]
    assert step5["name"] == "external_verify"
    assert step5["status"] == "skipped"
    assert step5["exit_code"] == 20
    assert "wakir_verify not importable" in step5["details"]["reason"]
    assert step5["details"]["mode"] == "library"
    assert step5["details"]["local_root_rederived"] is True


def test_external_verify_ok_with_library(tmp_path: Path):  # regression: F5, F7
    """With wakir-verify installed the cross-repo leg is a real ``ok``."""
    pytest.importorskip("wakir_verify.manifest")
    pytest.importorskip("wakir_verify.merkle_proof")
    completed = _run_driver(_driver_env(tmp_path / "w", simulate_no_verify=False))
    assert completed.returncode == 0, completed.stderr
    step5 = _report(completed)["steps"][-1]
    assert step5["status"] == "ok"
    d = step5["details"]
    assert d["mode"] == "library"
    assert d["manifest_consistent"] is True
    assert d["root_match"] is True
    assert d["leaf_present"] is True
    assert d["proof_verified"] is True
    verify_result = json.loads((tmp_path / "w" / "verify-result.json").read_text())
    assert verify_result["status"] == "ok"


def test_external_verify_library_flags_tampered_proof(tmp_path: Path):
    """Library path must say ``failed`` when the proof does not resolve."""
    pytest.importorskip("wakir_verify.merkle_proof")
    results = _run_pipeline(tmp_path, simulate_missing_verify=False)
    assert results["external"]["status"] == "ok"
    proof = dict(results["proof"])
    proof["leaf_hash"] = "11" * 32
    tampered = tmp_path / "tampered-proof.json"
    tampered.write_text(json.dumps(proof))
    result = helpers.do_external_verify(
        manifest=results["manifest_path"], proof=tampered, out=tmp_path / "vr2.json"
    )
    assert result["status"] == "failed"
    assert result["exit_code"] == 10
    assert result["proof_verified"] is False


def test_online_without_ots_is_explicit_skip(tmp_path: Path):  # regression: F6
    env = _driver_env(tmp_path / "w", DEMO_PROOF_VERIFY_ONLINE="1")
    completed = _run_driver(env)
    assert completed.returncode == 0, completed.stderr
    step5 = _report(completed)["steps"][-1]
    assert step5["status"] == "skipped"
    assert step5["details"]["reason"] == "DEMO_PROOF_VERIFY_ONLINE=1 but DEMO_PROOF_OTS_PROOF unset"


def test_aggregate_exit_code_semantics():  # regression: F8
    ok = {"status": "ok"}
    skipped = {"status": "skipped"}
    failed = {"status": "failed"}
    not_run = {"status": "not_run"}
    assert helpers.aggregate_exit_code([ok, ok, ok, ok, ok]) == 0
    assert helpers.aggregate_exit_code([ok, ok, ok, ok, skipped]) == 0
    assert helpers.aggregate_exit_code([ok, ok, failed, not_run, not_run]) == 10


# ---------------------------------------------------------------------------
# Regression: F7 — proof format
# ---------------------------------------------------------------------------


def _validator():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(PROOF_SCHEMA_PATH.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_proof_json_matches_inclusion_proof_schema(tmp_path: Path):  # regression: F7
    completed = _run_driver(_driver_env(tmp_path / "w"))
    assert completed.returncode == 0, completed.stderr
    proof = json.loads((tmp_path / "w" / "proof.json").read_text())
    _validator().validate(proof)
    assert proof["schema"] == "wakir-inclusion-proof/v1"
    assert proof["manifest_version"] == "wakir-wat-manifest/v1"
    assert "siblings" in proof
    # Step-4 details in the report carry the same fields.
    step4 = _report(completed)["steps"][3]["details"]
    assert step4["leaf_hash"] == proof["leaf_hash"]
    assert step4["siblings"] == proof["siblings"]
    assert step4["verified"] is True


def test_proof_siblings_recompute_root_with_stdlib_only(tmp_path: Path):  # regression: F7
    """Three leaves (odd → duplicate-last rule): the sibling path must
    let an outsider recompute the root with ``hashlib`` alone."""
    from wat.merkle.aggregator import compute_leaf_hash

    events = []
    for i in range(3):
        events.append({
            "event_id": f"evt-{i}",
            "time": f"{HOUR}:0{i}:00Z",
            "payload_hash": hashlib.sha256(f"payload-{i}".encode()).hexdigest(),
            "capability_token_hash": "0" * 64,
        })
    from wat.merkle.aggregator import build_merkle_tree

    leaves = [compute_leaf_hash(**ev) for ev in events]
    root, _ = build_merkle_tree(leaves)
    manifest = {
        "version": "wakir-wat-manifest/v1",
        "hour_slot": HOUR,
        "merkle_root": root.hex(),
        "event_count": 3,
        "events": [dict(ev, leaf_hash=leaf.hex()) for ev, leaf in zip(events, leaves)],
        "leaves": [dict(ev, leaf_hash=leaf.hex()) for ev, leaf in zip(events, leaves)],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    validator = _validator()

    for target in range(3):
        event_path = tmp_path / f"event-{target}.json"
        event_path.write_text("{}")
        event_path.with_suffix(".envelope.json").write_text(
            json.dumps({"payload_hash": events[target]["payload_hash"]})
        )
        result = helpers.do_verify_proof(
            manifest=manifest_path, event=event_path, out=tmp_path / f"proof-{target}.json"
        )
        assert result["verified"] is True
        proof = result["proof"]
        validator.validate(proof)
        assert proof["leaf_index"] == target
        assert proof["leaf_count"] == 3
        assert len(proof["siblings"]) == 2  # ceil(log2(3))
        assert _recompute_root(proof["leaf_hash"], proof["siblings"]) == root.hex()
        # Tamper one sibling: the outsider's recomputation must diverge.
        bad = json.loads(json.dumps(proof))
        bad["siblings"][0]["hash"] = "ff" * 32
        assert _recompute_root(bad["leaf_hash"], bad["siblings"]) != root.hex()


# ---------------------------------------------------------------------------
# Report validity with stdlib json
# ---------------------------------------------------------------------------


def test_report_validates_with_stdlib_json(tmp_path: Path):  # regression: F3, F12
    """stdout is one JSON object identical to demo-report.json; the
    workdir was created by the portable mktemp form (default path)."""
    completed = _run_driver(_driver_env(tmp_path / "w"))
    assert completed.returncode == 0, completed.stderr
    report = _report(completed)
    on_disk = json.loads((tmp_path / "w" / "demo-report.json").read_text())
    assert report == on_disk
    assert report["hour"] == HOUR
    assert report["workdir"] == str(tmp_path / "w")
    assert {"wakir_runtime", "wakir_protocol", "wakir_verify"} <= set(report["commits"])
    assert report["exit_code"] == 0

    # Default workdir: no DEMO_PROOF_WORKDIR, TMPDIR pointed at tmp_path.
    env = _driver_env(tmp_path / "unused")
    del env["DEMO_PROOF_WORKDIR"]
    env["TMPDIR"] = str(tmp_path)
    completed = _run_driver(env)
    assert completed.returncode == 0, completed.stderr
    workdir = Path(_report(completed)["workdir"])
    assert workdir.parent == tmp_path
    assert workdir.name.startswith("wakir-demo-proof.")
    assert (workdir / "demo-report.json").exists()
