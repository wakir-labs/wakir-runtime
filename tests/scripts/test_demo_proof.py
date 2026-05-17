# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors

"""Tests for scripts/demo-proof.sh + scripts/demo_proof_helpers.py.

Two layers of coverage:

1. **Python helper layer.** Each ``do_*`` function is exercised
   end-to-end against a temporary working directory, with the real
   ``wat`` modules in the loop. This is the substantive coverage —
   if a future refactor breaks the bridge/aggregator contract, these
   tests catch it.

2. **Subprocess driver layer.** The bash driver is invoked when
   ``jq`` is available on PATH; the test skips cleanly otherwise so
   sandbox environments without ``jq`` still pass. The subprocess
   path verifies the JSON report shape and per-step status payloads.

Tests
-----

1.  ``test_helpers_module_loads_and_exports_surface``
2.  ``test_step1_build_event_produces_deterministic_payload_hash``
3.  ``test_step1_rejects_malformed_hour_slot``
4.  ``test_step2_run_bridge_emits_status_ok_and_creates_spool``
5.  ``test_step3_build_manifest_records_payload_hash_from_step1``
6.  ``test_step3_raises_when_spool_missing``
7.  ``test_step4_verify_proof_returns_verified_true``
8.  ``test_step4_raises_when_payload_hash_drifts``
9.  ``test_step5_fixture_verify_matches_manifest_root``
10. ``test_step5_fixture_verify_flags_root_mismatch``
11. ``test_end_to_end_python_pipeline_chains_all_five_steps``
12. ``test_subprocess_demo_proof_emits_well_formed_report`` (skipped
    when ``jq`` is absent)
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# Helper loader
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPERS_PATH = REPO_ROOT / "scripts" / "demo_proof_helpers.py"
SHELL_DRIVER_PATH = REPO_ROOT / "scripts" / "demo-proof.sh"


def _load_helpers():
    """Import the helpers module under a stable dotted name.

    We load via ``importlib.util`` rather than ``import scripts.demo_proof_helpers``
    because the ``scripts`` directory has no ``__init__.py`` and we
    don't want to add one just for the tests.
    """
    spec = importlib.util.spec_from_file_location(
        "demo_proof_helpers", HELPERS_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


helpers = _load_helpers()


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def demo_dir(tmp_path: Path) -> Path:
    """Per-test working directory mirroring DEMO_PROOF_WORKDIR layout."""
    (tmp_path / "spool").mkdir()
    return tmp_path


@pytest.fixture
def event_artifacts(demo_dir: Path) -> Dict[str, Any]:
    """Run step 1 once so step 2/3/4 tests have a fresh event to consume."""
    out = demo_dir / "event.json"
    hash_out = demo_dir / "event.sha256"
    envelope = helpers.do_build_event(
        hour="2026-05-17T12", out=out, hash_out=hash_out
    )
    return {
        "envelope": envelope,
        "out": out,
        "hash_out": hash_out,
        "payload_hash": hash_out.read_text(encoding="utf-8"),
    }


def _run_pipeline(demo_dir: Path) -> Dict[str, Any]:
    """Drive all five steps in-process and return the artefact paths.

    Mirrors the bash driver's sequence but runs purely via the Python
    helper surface so the test stays hermetic and fast.
    """
    out = demo_dir / "event.json"
    hash_out = demo_dir / "event.sha256"
    envelope = helpers.do_build_event(
        hour="2026-05-17T12", out=out, hash_out=hash_out
    )
    bridge_out = demo_dir / "bridge-result.json"
    bridge_result = helpers.do_run_bridge(
        payload=out,
        payload_hash=hash_out.read_text(encoding="utf-8"),
        spool_root=demo_dir / "spool",
        activity_log=demo_dir / "activity-log.md",
        event_time="2026-05-17T12:00:00Z",
        out=bridge_out,
    )
    manifest_out = demo_dir / "2026-05-17T12" / "manifest.json"
    manifest = helpers.do_build_manifest(
        spool_root=demo_dir / "spool",
        hour="2026-05-17T12",
        aggregator_input=demo_dir / "manifest-input.jsonl",
        manifest_out=manifest_out,
    )
    proof_out = demo_dir / "proof.json"
    proof = helpers.do_verify_proof(
        manifest=manifest_out, event=out, out=proof_out
    )
    fixture_out = demo_dir / "verify-result.json"
    fixture = helpers.do_fixture_verify(
        manifest=manifest_out, out=fixture_out
    )
    return {
        "envelope": envelope,
        "bridge_result": bridge_result,
        "manifest": manifest,
        "manifest_path": manifest_out,
        "proof": proof,
        "fixture": fixture,
    }


# ---------------------------------------------------------------------------
# Test 1 — module surface
# ---------------------------------------------------------------------------


def test_helpers_module_loads_and_exports_surface():
    """Catch accidental renames of the public helper functions."""
    expected = {
        "do_build_event",
        "do_run_bridge",
        "do_build_manifest",
        "do_verify_proof",
        "do_fixture_verify",
        "build_parser",
        "main",
    }
    missing = expected - set(helpers.__all__)
    assert not missing, f"helpers.__all__ missing: {missing}"
    for name in expected:
        assert hasattr(helpers, name), f"helpers.{name} is not exported"


# ---------------------------------------------------------------------------
# Test 2 — step 1: build-event
# ---------------------------------------------------------------------------


def test_step1_build_event_produces_deterministic_payload_hash(demo_dir: Path):
    """Two runs against the same hour produce byte-identical events."""
    out_a = demo_dir / "a" / "event.json"
    out_b = demo_dir / "b" / "event.json"
    hash_a = demo_dir / "a" / "event.sha256"
    hash_b = demo_dir / "b" / "event.sha256"

    envelope_a = helpers.do_build_event(
        hour="2026-05-17T12", out=out_a, hash_out=hash_a
    )
    envelope_b = helpers.do_build_event(
        hour="2026-05-17T12", out=out_b, hash_out=hash_b
    )

    assert envelope_a["payload_hash"] == envelope_b["payload_hash"]
    assert out_a.read_bytes() == out_b.read_bytes()
    assert hash_a.read_text() == hash_b.read_text()
    # Envelope sidecar is written next to the payload.
    assert out_a.with_suffix(".envelope.json").exists()


# ---------------------------------------------------------------------------
# Test 3 — step 1 input validation
# ---------------------------------------------------------------------------


def test_step1_rejects_malformed_hour_slot(demo_dir: Path):
    """Malformed hour-slot input must fail loudly, not silently mis-build."""
    with pytest.raises(ValueError, match="YYYY-MM-DDTHH"):
        helpers.do_build_event(
            hour="2026/05/17 12",
            out=demo_dir / "event.json",
            hash_out=demo_dir / "event.sha256",
        )


# ---------------------------------------------------------------------------
# Test 4 — step 2: run-bridge
# ---------------------------------------------------------------------------


def test_step2_run_bridge_emits_status_ok_and_creates_spool(
    demo_dir: Path, event_artifacts: Dict[str, Any]
):
    """The real bridge writer must accept the demo event and produce a spool."""
    bridge_out = demo_dir / "bridge-result.json"
    result = helpers.do_run_bridge(
        payload=event_artifacts["out"],
        payload_hash=event_artifacts["payload_hash"],
        spool_root=demo_dir / "spool",
        activity_log=demo_dir / "activity-log.md",
        event_time="2026-05-17T12:00:00Z",
        out=bridge_out,
    )

    assert result["status"] == "ok"
    assert result["error"] == ""
    # Bridge writes per-persona, per-hour spool file.
    spool_file = demo_dir / "spool" / "demo" / "2026-05-17T12.jsonl"
    assert spool_file.exists()
    # Activity log got at least one append.
    assert (demo_dir / "activity-log.md").exists()
    # JSON dump on disk matches in-memory result.
    on_disk = json.loads(bridge_out.read_text())
    assert on_disk["status"] == "ok"


# ---------------------------------------------------------------------------
# Test 5 — step 3: build-manifest
# ---------------------------------------------------------------------------


def test_step3_build_manifest_records_payload_hash_from_step1(
    demo_dir: Path, event_artifacts: Dict[str, Any]
):
    """The manifest's recorded event row carries the step-1 payload hash."""
    helpers.do_run_bridge(
        payload=event_artifacts["out"],
        payload_hash=event_artifacts["payload_hash"],
        spool_root=demo_dir / "spool",
        activity_log=demo_dir / "activity-log.md",
        event_time="2026-05-17T12:00:00Z",
        out=demo_dir / "bridge-result.json",
    )
    manifest_out = demo_dir / "2026-05-17T12" / "manifest.json"
    manifest = helpers.do_build_manifest(
        spool_root=demo_dir / "spool",
        hour="2026-05-17T12",
        aggregator_input=demo_dir / "manifest-input.jsonl",
        manifest_out=manifest_out,
    )

    assert manifest["event_count"] == 1
    assert isinstance(manifest["merkle_root"], str)
    assert len(manifest["merkle_root"]) == 64  # 32-byte hex
    # The bridge preserves payload_hash verbatim into the manifest row.
    payload_hashes = [ev["payload_hash"] for ev in manifest["events"]]
    assert event_artifacts["payload_hash"] in payload_hashes


# ---------------------------------------------------------------------------
# Test 6 — step 3 error path
# ---------------------------------------------------------------------------


def test_step3_raises_when_spool_missing(demo_dir: Path):
    """A missing spool file is a hard error — silent fallthrough would hide drift."""
    with pytest.raises(FileNotFoundError):
        helpers.do_build_manifest(
            spool_root=demo_dir / "nope",
            hour="2026-05-17T12",
            aggregator_input=demo_dir / "agg.jsonl",
            manifest_out=demo_dir / "manifest.json",
        )


# ---------------------------------------------------------------------------
# Test 7 — step 4: verify-proof happy path
# ---------------------------------------------------------------------------


def test_step4_verify_proof_returns_verified_true(demo_dir: Path):
    """End-to-end pipeline yields a verifiable inclusion proof."""
    results = _run_pipeline(demo_dir)
    proof = results["proof"]
    assert proof["verified"] is True
    assert proof["leaf_index"] == 0
    assert proof["leaf_count"] == 1
    assert proof["proof_depth"] == 0  # single-leaf tree
    # The recomputed leaf hash equals the root for the single-leaf case.
    assert proof["leaf_hash_hex"] == proof["merkle_root"]


# ---------------------------------------------------------------------------
# Test 8 — step 4 drift detection
# ---------------------------------------------------------------------------


def test_step4_raises_when_payload_hash_drifts(demo_dir: Path):
    """Tampering with the envelope payload hash must trip the verifier."""
    results = _run_pipeline(demo_dir)
    envelope_path = (demo_dir / "event.json").with_suffix(".envelope.json")
    envelope = json.loads(envelope_path.read_text())
    envelope["payload_hash"] = "deadbeef" * 8  # 64-hex but absent from manifest
    envelope_path.write_text(json.dumps(envelope))

    with pytest.raises(ValueError, match="not found in manifest"):
        helpers.do_verify_proof(
            manifest=results["manifest_path"],
            event=demo_dir / "event.json",
            out=demo_dir / "proof-2.json",
        )


# ---------------------------------------------------------------------------
# Test 9 — step 5 fixture happy path
# ---------------------------------------------------------------------------


def test_step5_fixture_verify_matches_manifest_root(demo_dir: Path):
    """Fixture verifier confirms the writer-side root re-derives cleanly."""
    results = _run_pipeline(demo_dir)
    fixture = results["fixture"]
    assert fixture["fixture_ok"] is True
    assert fixture["rederived_root"] == fixture["manifest_root"]


# ---------------------------------------------------------------------------
# Test 10 — step 5 fixture failure path
# ---------------------------------------------------------------------------


def test_step5_fixture_verify_flags_root_mismatch(demo_dir: Path):
    """Tamper the manifest's stored root; fixture verifier must say fixture_ok=false."""
    results = _run_pipeline(demo_dir)
    manifest_path = results["manifest_path"]
    blob = json.loads(manifest_path.read_text())
    blob["merkle_root"] = "00" * 32  # plausible 64-hex but wrong
    manifest_path.write_text(json.dumps(blob))

    out = demo_dir / "fixture-2.json"
    fixture = helpers.do_fixture_verify(manifest=manifest_path, out=out)
    assert fixture["fixture_ok"] is False
    assert fixture["rederived_root"] != fixture["manifest_root"]


# ---------------------------------------------------------------------------
# Test 11 — full Python pipeline
# ---------------------------------------------------------------------------


def test_end_to_end_python_pipeline_chains_all_five_steps(demo_dir: Path):
    """All five helpers chain in order and produce a verified result."""
    results = _run_pipeline(demo_dir)
    assert results["bridge_result"]["status"] == "ok"
    assert results["manifest"]["event_count"] == 1
    assert results["proof"]["verified"] is True
    assert results["fixture"]["fixture_ok"] is True
    # The manifest's root must match the rederived root from the fixture verifier.
    assert (
        results["manifest"]["merkle_root"]
        == results["fixture"]["rederived_root"]
    )


# ---------------------------------------------------------------------------
# Test 12 — subprocess shell driver
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    shutil.which("jq") is None,
    reason="jq is not installed on the test host",
)
def test_subprocess_demo_proof_emits_well_formed_report(tmp_path: Path):
    """Run the actual bash driver and assert on the JSON report shape."""
    env = os.environ.copy()
    env["DEMO_PROOF_WORKDIR"] = str(tmp_path)
    env["DEMO_PROOF_HOUR"] = "2026-05-17T12"
    # Force the hermetic external-verify path so we never reach the network.
    env["DEMO_PROOF_VERIFY_ONLINE"] = "0"
    env["DEMO_PROOF_VERIFY_CMD"] = "wakir-verify-not-installed-on-purpose"

    completed = subprocess.run(
        ["bash", str(SHELL_DRIVER_PATH)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    # Exit code 20 is "all steps OK but external-verify fell back to fixture".
    # 0 would only happen if wakir-verify is installed; we forced a non-existent
    # binary name so the fixture fallback is guaranteed.
    assert completed.returncode in (0, 20), (
        f"unexpected exit: {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    report = json.loads(completed.stdout)
    assert report["schema"] == "wakir-demo-proof/v1"
    assert report["hour"] == "2026-05-17T12"
    assert {"wakir_runtime", "wakir_protocol", "wakir_verify"} <= set(
        report["commits"]
    )
    step_names = [step["name"] for step in report["steps"]]
    assert step_names == [
        "protocol_event",
        "runtime_bridge",
        "merkle_manifest",
        "inclusion_proof",
        "external_verify",
    ]
    # Step 5 must have fallen back to the fixture path.
    step5 = report["steps"][-1]
    assert step5["name"] == "external_verify"
    assert step5["status"] == "skipped"
    assert step5["details"].get("fallback") == "fixture"
    assert step5["details"].get("fixture_ok") is True
