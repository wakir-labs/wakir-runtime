#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic invariants for the Tag-53 Image-Build-Reproducibility-Live-Test.

Tag-53 closes the gap left by Tag-51 (PR #328): Tag-51 covers the
Cargo.lock derivation axis (two in-process derivations of the
build-graph produce byte-equal output). Tag-53 covers the
image-build axis (two ``cargo build --release`` invocations against
the same Cargo.lock produce byte-equal ELF binaries). The default
operation mode in CI is ``--mode=sandbox-stub`` -- a hermetic
simulator over the canonical 15-binary inventory; live verification
is Operator-Hand only per ``feedback_sandbox_host_trennung.md`` +
ADR-0051; this test surface reads files on disk only.

Sibling tests
-------------

  * ``tests/observability/test_verify_15_binary_build_reproducibility.py``
    -- Tag-51 Cargo.lock-derivation invariants (18 tests).
  * ``tests/observability/test_quadlet_15_binary_live_boot_test.py``
    -- Tag-52 quadlet-live-boot invariants.
  * ``tests/observability/test_generate_15_binary_sbom.py``
    -- Tag-48 SBOM-generator invariants.

Test-Vector index
-----------------

  * ``TV-T53-01``  Tag-45 binary inventory mirrored byte-for-byte
                   (15 entries, exact order).
  * ``TV-T53-02``  POLICY_NAME_TO_CRATE mapping is total (every
                   inventory binary has a root-crate).
  * ``TV-T53-03``  Sandbox-stub GREEN by default for all 15 binaries.
  * ``TV-T53-04``  Pass-1 hash deterministic across re-evaluation.
  * ``TV-T53-05``  Pass-2 hash equals pass-1 in undriven case
                   (byte-equality is the GREEN-invariant).
  * ``TV-T53-06``  Pass-1 fingerprints distinct across binaries.
  * ``TV-T53-07``  Pass-1 fingerprint changes when Cargo.lock SHA
                   changes (the audit anchors on lock-file content).
  * ``TV-T53-08``  Induced-drift surfaces RED for the named binary
                   only (other 14 stay GREEN).
  * ``TV-T53-09``  Induced-drift unknown-binary raises KeyError.
  * ``TV-T53-10``  Malformed Cargo.lock raises ValueError.
  * ``TV-T53-11``  Live-mode raises NotImplementedError with the
                   sandbox-host-trennung pointer.
  * ``TV-T53-12``  JSON envelope schema-shape canonical.
  * ``TV-T53-13``  Prometheus textfile carries all required gauges.
  * ``TV-T53-14``  Markdown summary shape canonical.
  * ``TV-T53-15``  Mira-Notify payload empty on GREEN aggregate.
  * ``TV-T53-16``  Mira-Notify payload populated on drift, lists
                   exactly the drifted binaries.
  * ``TV-T53-17``  CLI smoke: --mode=sandbox-stub against the real
                   workspace Cargo.lock exits 0.

Total: 17 hermetic invariants -- comfortably above the >=12 target.

-- Kai
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    REPO_ROOT
    / "scripts"
    / "observability"
    / "verify-15-binary-image-build-reproducibility.py"
)


def _load_module():
    """Load the hyphenated-name script as a Python module."""
    spec = importlib.util.spec_from_file_location(
        "verify_15_binary_image_build_reproducibility",
        str(SCRIPT_PATH),
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[
        "verify_15_binary_image_build_reproducibility"
    ] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


vbr = _load_module()


# ---------------------------------------------------------------------------
# Synthetic Cargo.lock fixture -- the smallest TOML that satisfies
# the parser's [[package]]-must-be-non-empty invariant. The
# image-build axis does not need the parsed tree; it only anchors
# on the lock-file SHA-256.
# ---------------------------------------------------------------------------


SYNTHETIC_LOCK = b"""\
version = 4

[[package]]
name = "anchor-crate"
version = "0.0.0"
"""


# ---------------------------------------------------------------------------
# TV-T53-01: Inventory mirrored byte-for-byte.
# ---------------------------------------------------------------------------


def test_tv_t53_01_inventory_mirrored_byte_for_byte():
    assert vbr.TAG45_BINARY_INVENTORY == (
        "recovery",
        "state-backing",
        "fsm",
        "v907-verify",
        "bridge-diff",
        "subscribe-loop",
        "anchor-emitter",
        "svid-workload-identity",
        "bridge-audit-writer",
        "state-backing-welle4",
        "fsm-welle5",
        "subscribe-loop-welle6",
        "recovery-welle7",
        "bridge-audit-replay",
        "migrate-version",
    )
    assert len(vbr.TAG45_BINARY_INVENTORY) == 15


# ---------------------------------------------------------------------------
# TV-T53-02: POLICY_NAME_TO_CRATE total.
# ---------------------------------------------------------------------------


def test_tv_t53_02_policy_name_to_crate_total():
    missing = [
        name for name in vbr.TAG45_BINARY_INVENTORY
        if name not in vbr.POLICY_NAME_TO_CRATE
    ]
    assert missing == [], (
        f"POLICY_NAME_TO_CRATE missing entries: {missing}"
    )
    # And every root-crate must be a non-empty string.
    for name in vbr.TAG45_BINARY_INVENTORY:
        root = vbr.POLICY_NAME_TO_CRATE[name]
        assert isinstance(root, str)
        assert root.startswith("persona-engine-"), root


# ---------------------------------------------------------------------------
# TV-T53-03: Sandbox-stub GREEN by default for all 15.
# ---------------------------------------------------------------------------


def test_tv_t53_03_sandbox_stub_green_by_default():
    verdict = vbr.run_sandbox_stub(SYNTHETIC_LOCK)
    assert verdict.overall_green is True
    assert verdict.drift_count == 0
    assert verdict.deterministic_count == 15
    assert len(verdict.per_binary) == 15
    assert verdict.mode == vbr.MODE_SANDBOX_STUB
    for bp in verdict.per_binary:
        assert bp.byte_equal is True
        assert bp.pass1_sha256 == bp.pass2_sha256


# ---------------------------------------------------------------------------
# TV-T53-04: Pass-1 hash deterministic across re-evaluation.
# ---------------------------------------------------------------------------


def test_tv_t53_04_pass1_deterministic_across_runs():
    v1 = vbr.run_sandbox_stub(SYNTHETIC_LOCK)
    v2 = vbr.run_sandbox_stub(SYNTHETIC_LOCK)
    for a, b in zip(v1.per_binary, v2.per_binary):
        assert a.binary_name == b.binary_name
        assert a.pass1_sha256 == b.pass1_sha256
        assert a.pass2_sha256 == b.pass2_sha256


# ---------------------------------------------------------------------------
# TV-T53-05: Pass-2 equals pass-1 in undriven case.
# ---------------------------------------------------------------------------


def test_tv_t53_05_pass2_equals_pass1_in_undriven_case():
    verdict = vbr.run_sandbox_stub(SYNTHETIC_LOCK)
    for bp in verdict.per_binary:
        assert bp.pass1_sha256 == bp.pass2_sha256, (
            f"undriven case must be byte-equal: {bp.binary_name}"
        )


# ---------------------------------------------------------------------------
# TV-T53-06: Pass-1 fingerprints distinct across binaries.
# ---------------------------------------------------------------------------


def test_tv_t53_06_pass1_fingerprints_distinct_across_binaries():
    verdict = vbr.run_sandbox_stub(SYNTHETIC_LOCK)
    hashes = [bp.pass1_sha256 for bp in verdict.per_binary]
    assert len(set(hashes)) == len(hashes), (
        "pass-1 fingerprints must be distinct across binaries"
    )


# ---------------------------------------------------------------------------
# TV-T53-07: Pass-1 fingerprint changes when Cargo.lock SHA changes.
# ---------------------------------------------------------------------------


def test_tv_t53_07_pass1_fingerprint_anchored_on_cargo_lock():
    other_lock = SYNTHETIC_LOCK + b"\n# trailing comment\n"
    v1 = vbr.run_sandbox_stub(SYNTHETIC_LOCK)
    v2 = vbr.run_sandbox_stub(other_lock)
    assert v1.cargo_lock_sha256 != v2.cargo_lock_sha256
    for a, b in zip(v1.per_binary, v2.per_binary):
        assert a.binary_name == b.binary_name
        assert a.pass1_sha256 != b.pass1_sha256, (
            f"pass-1 must change with lock-file: {a.binary_name}"
        )


# ---------------------------------------------------------------------------
# TV-T53-08: Induced-drift surfaces RED for the named binary only.
# ---------------------------------------------------------------------------


def test_tv_t53_08_induced_drift_surfaces_red_for_named_binary():
    target = "subscribe-loop"
    verdict = vbr.run_sandbox_stub(
        SYNTHETIC_LOCK, induced_drift_binaries=(target,)
    )
    assert verdict.overall_green is False
    assert verdict.drift_count == 1
    assert verdict.deterministic_count == 14
    red = [
        bp.binary_name for bp in verdict.per_binary
        if not bp.byte_equal
    ]
    assert red == [target]
    # The drifted binary's pass-2 hash is the canonical marker.
    drifted = next(
        bp for bp in verdict.per_binary if bp.binary_name == target
    )
    expected_drift = hashlib.sha256(
        vbr.INDUCED_DRIFT_MARKER
    ).hexdigest()
    assert drifted.pass2_sha256 == expected_drift
    assert drifted.pass1_sha256 != drifted.pass2_sha256


# ---------------------------------------------------------------------------
# TV-T53-09: Induced-drift unknown-binary raises KeyError.
# ---------------------------------------------------------------------------


def test_tv_t53_09_induced_drift_unknown_binary_raises():
    with pytest.raises(KeyError, match="not-a-real-binary"):
        vbr.run_sandbox_stub(
            SYNTHETIC_LOCK,
            induced_drift_binaries=("not-a-real-binary",),
        )


# ---------------------------------------------------------------------------
# TV-T53-10: Malformed Cargo.lock raises ValueError.
# ---------------------------------------------------------------------------


def test_tv_t53_10_malformed_cargo_lock_raises_value_error():
    # Valid TOML, no [[package]] -- should fail the parse-sanity.
    bad = b'version = 4\n'
    with pytest.raises(ValueError, match="package"):
        vbr.run_sandbox_stub(bad)


# ---------------------------------------------------------------------------
# TV-T53-11: Live-mode raises NotImplementedError.
# ---------------------------------------------------------------------------


def test_tv_t53_11_live_mode_raises_not_implemented_error():
    with pytest.raises(NotImplementedError) as excinfo:
        vbr.run_live_mode(SYNTHETIC_LOCK)
    msg = str(excinfo.value)
    assert "Operator-Hand" in msg
    assert "sandbox-stub" in msg


# ---------------------------------------------------------------------------
# TV-T53-12: JSON envelope schema-shape canonical.
# ---------------------------------------------------------------------------


def test_tv_t53_12_json_envelope_schema_shape_canonical():
    verdict = vbr.run_sandbox_stub(SYNTHETIC_LOCK)
    body = vbr.render_envelope_json(verdict, audit_ts=0.0)
    obj = json.loads(body)
    assert obj["$schema"] == vbr.ENVELOPE_SCHEMA
    assert obj["tool"]["name"] == vbr.TOOL_NAME
    assert obj["tool"]["version"] == vbr.TOOL_VERSION
    assert obj["mode"] == vbr.MODE_SANDBOX_STUB
    assert obj["overall_green"] is True
    assert obj["deterministic_count"] == 15
    assert obj["drift_count"] == 0
    assert obj["binary_count"] == 15
    assert len(obj["per_binary"]) == 15
    for entry in obj["per_binary"]:
        assert set(entry.keys()) == {
            "binary_name",
            "root_crate",
            "pass1_sha256",
            "pass2_sha256",
            "byte_equal",
        }
        assert len(entry["pass1_sha256"]) == 64
        assert len(entry["pass2_sha256"]) == 64
    # JSON is deterministic (sort_keys + indent fixed).
    assert body == vbr.render_envelope_json(verdict, audit_ts=0.0)


# ---------------------------------------------------------------------------
# TV-T53-13: Prometheus textfile carries all required gauges.
# ---------------------------------------------------------------------------


def test_tv_t53_13_prom_textfile_carries_required_gauges():
    verdict = vbr.run_sandbox_stub(SYNTHETIC_LOCK)
    txt = vbr.render_prom_textfile(verdict)
    # Three gauge declarations.
    assert (
        "# TYPE wakir_image_build_reproducibility_byte_equal gauge"
        in txt
    )
    assert (
        "# TYPE wakir_image_build_reproducibility_drift_count "
        "gauge" in txt
    )
    assert (
        "# TYPE wakir_image_build_reproducibility_"
        "deterministic_count gauge" in txt
    )
    # One byte_equal sample per binary.
    for name in vbr.TAG45_BINARY_INVENTORY:
        assert (
            f'wakir_image_build_reproducibility_byte_equal'
            f'{{binary="{name}",mode="sandbox-stub"}} 1'
        ) in txt
    # Aggregates.
    assert (
        'wakir_image_build_reproducibility_drift_count'
        '{mode="sandbox-stub"} 0'
    ) in txt
    assert (
        'wakir_image_build_reproducibility_deterministic_count'
        '{mode="sandbox-stub"} 15'
    ) in txt


# ---------------------------------------------------------------------------
# TV-T53-14: Markdown summary shape canonical.
# ---------------------------------------------------------------------------


def test_tv_t53_14_markdown_summary_shape_canonical():
    verdict = vbr.run_sandbox_stub(SYNTHETIC_LOCK)
    md = vbr.render_markdown(verdict)
    assert md.startswith(
        "## 15-Binary Image-Build-Reproducibility (Tag-53)"
    )
    assert "**Mode**: `sandbox-stub`" in md
    assert "**Overall**: `GREEN`" in md
    assert "**Drift**: 0" in md
    # One table row per binary.
    for name in vbr.TAG45_BINARY_INVENTORY:
        assert f"| `{name}` |" in md


# ---------------------------------------------------------------------------
# TV-T53-15: Mira-Notify payload empty on GREEN aggregate.
# ---------------------------------------------------------------------------


def test_tv_t53_15_mira_notify_empty_on_green():
    verdict = vbr.run_sandbox_stub(SYNTHETIC_LOCK)
    body = vbr.render_mira_notify(verdict, audit_ts=0.0)
    assert body == ""


# ---------------------------------------------------------------------------
# TV-T53-16: Mira-Notify populated on drift; lists drifted binaries.
# ---------------------------------------------------------------------------


def test_tv_t53_16_mira_notify_populated_on_drift():
    target_a = "fsm"
    target_b = "anchor-emitter"
    verdict = vbr.run_sandbox_stub(
        SYNTHETIC_LOCK,
        induced_drift_binaries=(target_a, target_b),
    )
    body = vbr.render_mira_notify(verdict, audit_ts=0.0)
    assert body != ""
    obj = json.loads(body)
    assert (
        obj["$schema"] == "wakir-runtime/mira-notify-event@1"
    )
    assert obj["event_type"] == "image-build-reproducibility-drift"
    assert obj["severity"] == "RED"
    assert obj["mode"] == vbr.MODE_SANDBOX_STUB
    assert obj["drift_count"] == 2
    assert obj["drift_binaries"] == [target_a, target_b]
    assert "byte-unequal" in obj["summary"]
    assert "cargo build --release" in obj["summary"]


# ---------------------------------------------------------------------------
# TV-T53-17: CLI smoke against the real workspace Cargo.lock.
# ---------------------------------------------------------------------------


def test_tv_t53_17_cli_smoke_against_real_cargo_lock(tmp_path):
    real_lock = REPO_ROOT / "wirelang-rust" / "Cargo.lock"
    if not real_lock.is_file():
        pytest.skip("workspace Cargo.lock not present")
    out_json = tmp_path / "verdict.json"
    out_prom = tmp_path / "metrics.prom"
    out_md = tmp_path / "summary.md"
    out_notify = tmp_path / "mira-notify.json"
    rc = vbr.main(
        [
            "--cargo-lock",
            str(real_lock),
            "--mode",
            "sandbox-stub",
            "--out-json",
            str(out_json),
            "--out-textfile",
            str(out_prom),
            "--out-markdown",
            str(out_md),
            "--out-mira-notify",
            str(out_notify),
        ]
    )
    assert rc == 0, "CLI smoke must exit 0 on real Cargo.lock"
    assert out_json.is_file()
    assert out_prom.is_file()
    assert out_md.is_file()
    assert out_notify.is_file()
    # GREEN -> notify is empty.
    assert out_notify.read_text("utf-8") == ""
    obj = json.loads(out_json.read_text("utf-8"))
    assert obj["overall_green"] is True
    assert obj["binary_count"] == 15
