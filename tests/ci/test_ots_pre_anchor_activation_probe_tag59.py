# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for Tag-59 OTS Pre-Anchor Activation Probe.

The Tag-57 audit-only emit (PR #366) plus the Tag-58 spec-seal
probe (Reza, PR #371) leave one gap before the KW-24 Phase-3c
cutover (2026-06-09 start): no CI-side dry-run that asserts the
Repo-Side OTS-call pipeline is shape-ready for the real
``ots stamp`` invocation. Tag-59 closes that gap with a hermetic
``--mode pre-activation-probe`` extension of the existing helper.

Invariants asserted (>=12):

  P01. Helper still stdlib-only after the Tag-59 extension.
  P02. Helper exposes ``MODE_PRE_ACTIVATION_PROBE`` and the
       four probe-stage keys.
  P03. ``--mode pre-activation-probe`` on a valid fixture
       returns verdict PROBE-READY and the documented v1 shape.
  P04. Verdict envelope key-set matches the documented v1 shape.
  P05. Missing manifest yields verdict PROBE-DEFECT with
       input_validation FAIL reason.
  P06. Non-file manifest (directory) yields PROBE-DEFECT.
  P07. SHA-256 in the verdict envelope matches a manual
       hashlib computation on the fixture bytes.
  P08. Verdict ``ar_authorisation_required`` is always True.
  P09. Verdict ``probed_at_utc`` honours ``--now`` and is
       byte-stable across two invocations.
  P10. Audit-only mode still works after Tag-59 extension
       (backwards compat with Tag-57 helper API).
  P11. ``--probe-verdict-out`` is required for probe mode
       (exit code 2 when missing).
  P12. ``--marker-out`` is required for audit-only mode
       (exit code 2 when missing).
  P13. Tag-59 workflow YAML is well-formed and pins the helper.
  P14. Runbook doc contains §6 Pre-Activation-Probe-Mode and
       §7 AR-Authorisierungs-Pfad sections.
  P15. Probing every real pre-cutover manifest from the
       in-tree registry succeeds with PROBE-READY.
  P16. Probe never imports network-capable modules.

Sandbox boundary: filesystem reads, python stdlib, pytest, yaml.
No subprocess for the helper beyond invoking ``main()`` via
``importlib``. No network. No ots CLI call. No podman.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

K2_EMIT = REPO_ROOT / "tooling" / "ots" / "emit_manifest_hash_ots_marker.py"
K2_STUB = REPO_ROOT / "tooling" / "ots" / "manifest-hash-ots-anchor-stub.json"
K2_DOC = REPO_ROOT / "docs" / "operations" / "manifest-hash-ots-anchor-wiring.md"
TAG59_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "ots-pre-anchor-activation-probe.yml"
)


STDLIB_ALLOW: frozenset[str] = frozenset(
    {
        "__future__",
        "argparse",
        "ast",
        "datetime",
        "hashlib",
        "io",
        "json",
        "os",
        "pathlib",
        "re",
        "sys",
        "typing",
    }
)


# Modules that would imply network or subprocess capability. The
# Tag-59 probe must NOT import any of them — that is the runtime
# guarantee for the ``sandbox_boundary: OK`` stage flag.
NETWORK_FORBIDDEN: frozenset[str] = frozenset(
    {
        "socket",
        "ssl",
        "urllib",
        "http",
        "ftplib",
        "smtplib",
        "telnetlib",
        "requests",
        "httpx",
        "subprocess",
        "asyncio",
    }
)


VERDICT_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "kind",
        "mode",
        "verdict",
        "stages",
        "manifest_sha256",
        "manifest_size_bytes",
        "probed_at_utc",
        "ar_authorisation_required",
        "anchors",
    }
)


PROBE_STAGE_KEYS: frozenset[str] = frozenset(
    {
        "input_validation",
        "hash_computation",
        "payload_shape",
        "sandbox_boundary",
    }
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _toplevel_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


@pytest.fixture(scope="module")
def k2_module():
    assert K2_EMIT.is_file(), f"missing: {K2_EMIT}"
    return _load_module("_k2_emit_manifest_hash_ots_marker_tag59", K2_EMIT)


# ----------------------------------------------------------------------
# P01. Helper still stdlib-only after Tag-59 extension.
# ----------------------------------------------------------------------


def test_p01_helper_still_stdlib_only():
    imports = _toplevel_imports(K2_EMIT)
    extras = imports - STDLIB_ALLOW
    assert not extras, f"Tag-59 helper has non-stdlib imports: {extras}"


# ----------------------------------------------------------------------
# P02. Module constants exposed.
# ----------------------------------------------------------------------


def test_p02_module_exposes_probe_constants(k2_module):
    assert k2_module.MODE_PRE_ACTIVATION_PROBE == "pre-activation-probe"
    assert k2_module.PROBE_VERDICT_READY == "PROBE-READY"
    assert k2_module.PROBE_VERDICT_DEFECT == "PROBE-DEFECT"
    assert set(k2_module.PROBE_STAGE_KEYS) == PROBE_STAGE_KEYS
    assert (
        set(k2_module.PROBE_VERDICT_REQUIRED_KEYS) == VERDICT_REQUIRED_KEYS
    )


# ----------------------------------------------------------------------
# P03. Happy-path: probe on fixture manifest -> PROBE-READY, v1 shape.
# ----------------------------------------------------------------------


def test_p03_probe_happy_path_emits_ready(tmp_path: Path, k2_module):
    manifest = tmp_path / "MANIFEST-fixture.md"
    manifest.write_text("fixture body line one\nfixture body line two\n", encoding="utf-8")
    verdict_out = tmp_path / "out" / "verdict.json"
    rc = k2_module.main(
        [
            "--mode", "pre-activation-probe",
            "--manifest", str(manifest),
            "--probe-verdict-out", str(verdict_out),
            "--actor", "tomas",
            "--repo-root", str(tmp_path),
            "--now", "2026-05-19T12:00:00+00:00",
        ]
    )
    assert rc == 0
    payload = json.loads(verdict_out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["kind"] == "ots-pre-activation-probe-verdict"
    assert payload["mode"] == "pre-activation-probe"
    assert payload["verdict"] == "PROBE-READY"
    for stage_key in PROBE_STAGE_KEYS:
        assert payload["stages"][stage_key].startswith("OK"), (
            f"stage {stage_key} not OK: {payload['stages'][stage_key]}"
        )


# ----------------------------------------------------------------------
# P04. Verdict envelope key-set matches the documented v1 shape.
# ----------------------------------------------------------------------


def test_p04_verdict_envelope_key_set(tmp_path: Path, k2_module):
    manifest = tmp_path / "MANIFEST-shape.md"
    manifest.write_text("a\n", encoding="utf-8")
    verdict_out = tmp_path / "verdict.json"
    rc = k2_module.main(
        [
            "--mode", "pre-activation-probe",
            "--manifest", str(manifest),
            "--probe-verdict-out", str(verdict_out),
            "--repo-root", str(tmp_path),
            "--now", "2026-05-19T12:00:00+00:00",
        ]
    )
    assert rc == 0
    payload = json.loads(verdict_out.read_text(encoding="utf-8"))
    assert set(payload.keys()) == VERDICT_REQUIRED_KEYS
    assert set(payload["stages"].keys()) == PROBE_STAGE_KEYS
    # ``anchors`` cross-links Tag-58 PR #371 and the runbook.
    anchors = payload["anchors"]
    assert anchors["reza_tag_58_spec_seal_pr"] == 371
    assert anchors["operator_hand_runbook"] == (
        "docs/operations/manifest-hash-ots-anchor-wiring.md"
    )


# ----------------------------------------------------------------------
# P05. Missing manifest -> PROBE-DEFECT with input_validation FAIL.
# ----------------------------------------------------------------------


def test_p05_missing_manifest_yields_defect(tmp_path: Path, k2_module):
    manifest = tmp_path / "does-not-exist.md"
    verdict_out = tmp_path / "verdict.json"
    rc = k2_module.main(
        [
            "--mode", "pre-activation-probe",
            "--manifest", str(manifest),
            "--probe-verdict-out", str(verdict_out),
            "--repo-root", str(tmp_path),
            "--now", "2026-05-19T12:00:00+00:00",
        ]
    )
    assert rc == 0  # probe records defect, does not exit non-zero
    payload = json.loads(verdict_out.read_text(encoding="utf-8"))
    assert payload["verdict"] == "PROBE-DEFECT"
    assert payload["stages"]["input_validation"].startswith("FAIL: ")
    assert "not found" in payload["stages"]["input_validation"]
    assert payload["manifest_sha256"] == ""
    assert payload["manifest_size_bytes"] == 0


# ----------------------------------------------------------------------
# P06. Non-file manifest (directory) -> PROBE-DEFECT.
# ----------------------------------------------------------------------


def test_p06_directory_manifest_yields_defect(tmp_path: Path, k2_module):
    # Pass a directory as the manifest path.
    not_a_file = tmp_path / "subdir"
    not_a_file.mkdir()
    verdict_out = tmp_path / "verdict.json"
    rc = k2_module.main(
        [
            "--mode", "pre-activation-probe",
            "--manifest", str(not_a_file),
            "--probe-verdict-out", str(verdict_out),
            "--repo-root", str(tmp_path),
            "--now", "2026-05-19T12:00:00+00:00",
        ]
    )
    assert rc == 0
    payload = json.loads(verdict_out.read_text(encoding="utf-8"))
    assert payload["verdict"] == "PROBE-DEFECT"
    assert payload["stages"]["input_validation"].startswith("FAIL: ")
    assert "not a regular file" in payload["stages"]["input_validation"]


# ----------------------------------------------------------------------
# P07. SHA-256 in verdict matches manual hashlib computation.
# ----------------------------------------------------------------------


def test_p07_verdict_sha256_matches_manual(tmp_path: Path, k2_module):
    body = b"deterministic content for tag-59 probe\n"
    manifest = tmp_path / "MANIFEST-sha.md"
    manifest.write_bytes(body)
    expected = hashlib.sha256(body).hexdigest()
    verdict_out = tmp_path / "verdict.json"
    rc = k2_module.main(
        [
            "--mode", "pre-activation-probe",
            "--manifest", str(manifest),
            "--probe-verdict-out", str(verdict_out),
            "--repo-root", str(tmp_path),
            "--now", "2026-05-19T12:00:00+00:00",
        ]
    )
    assert rc == 0
    payload = json.loads(verdict_out.read_text(encoding="utf-8"))
    assert payload["manifest_sha256"] == expected
    assert payload["manifest_size_bytes"] == len(body)
    assert payload["stages"]["hash_computation"] == f"OK: {expected}"


# ----------------------------------------------------------------------
# P08. ``ar_authorisation_required`` is always True.
# ----------------------------------------------------------------------


def test_p08_ar_authorisation_required_always_true(tmp_path: Path, k2_module):
    # Both READY and DEFECT verdicts must carry the flag.
    manifest_ok = tmp_path / "MANIFEST-ok.md"
    manifest_ok.write_text("ok\n", encoding="utf-8")
    manifest_missing = tmp_path / "absent.md"
    for manifest in (manifest_ok, manifest_missing):
        out = tmp_path / f"{manifest.name}.verdict.json"
        rc = k2_module.main(
            [
                "--mode", "pre-activation-probe",
                "--manifest", str(manifest),
                "--probe-verdict-out", str(out),
                "--repo-root", str(tmp_path),
                "--now", "2026-05-19T12:00:00+00:00",
            ]
        )
        assert rc == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["ar_authorisation_required"] is True


# ----------------------------------------------------------------------
# P09. ``--now`` byte-stable across two invocations.
# ----------------------------------------------------------------------


def test_p09_now_override_byte_stable(tmp_path: Path, k2_module):
    manifest = tmp_path / "MANIFEST-stable.md"
    manifest.write_text("stable\n", encoding="utf-8")
    iso = "2026-05-19T12:34:56+00:00"
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    for out in (out_a, out_b):
        rc = k2_module.main(
            [
                "--mode", "pre-activation-probe",
                "--manifest", str(manifest),
                "--probe-verdict-out", str(out),
                "--actor", "tomas",
                "--repo-root", str(tmp_path),
                "--now", iso,
            ]
        )
        assert rc == 0
    pa = json.loads(out_a.read_text(encoding="utf-8"))
    pb = json.loads(out_b.read_text(encoding="utf-8"))
    assert pa["probed_at_utc"] == iso
    assert pa == pb


# ----------------------------------------------------------------------
# P10. Audit-only mode still works (backwards compat).
# ----------------------------------------------------------------------


def test_p10_audit_only_mode_backwards_compat(tmp_path: Path, k2_module):
    manifest = tmp_path / "MANIFEST-bc.md"
    manifest.write_text("bc\n", encoding="utf-8")
    marker = tmp_path / "marker.json"
    # Note: --mode defaults to audit-only; we also test the explicit
    # form to lock the default behaviour.
    rc = k2_module.main(
        [
            "--manifest", str(manifest),
            "--marker-out", str(marker),
            "--actor", "tomas",
            "--repo-root", str(tmp_path),
            "--now", "2026-05-19T12:00:00+00:00",
        ]
    )
    assert rc == 0
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["mode"] == "audit-only"
    assert payload["kind"] == "manifest-hash-ots-anchor-marker"
    # Same call with explicit --mode audit-only must produce same bytes.
    marker2 = tmp_path / "marker2.json"
    rc2 = k2_module.main(
        [
            "--mode", "audit-only",
            "--manifest", str(manifest),
            "--marker-out", str(marker2),
            "--actor", "tomas",
            "--repo-root", str(tmp_path),
            "--now", "2026-05-19T12:00:00+00:00",
        ]
    )
    assert rc2 == 0
    assert marker.read_text(encoding="utf-8") == marker2.read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# P11. ``--probe-verdict-out`` required for probe mode.
# ----------------------------------------------------------------------


def test_p11_probe_mode_requires_verdict_out(tmp_path: Path, k2_module, capsys):
    manifest = tmp_path / "m.md"
    manifest.write_text("x\n", encoding="utf-8")
    rc = k2_module.main(
        [
            "--mode", "pre-activation-probe",
            "--manifest", str(manifest),
            # missing --probe-verdict-out
            "--repo-root", str(tmp_path),
            "--now", "2026-05-19T12:00:00+00:00",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "--probe-verdict-out is required" in err


# ----------------------------------------------------------------------
# P12. ``--marker-out`` required for audit-only mode.
# ----------------------------------------------------------------------


def test_p12_audit_mode_requires_marker_out(tmp_path: Path, k2_module, capsys):
    manifest = tmp_path / "m.md"
    manifest.write_text("x\n", encoding="utf-8")
    rc = k2_module.main(
        [
            "--mode", "audit-only",
            "--manifest", str(manifest),
            # missing --marker-out
            "--repo-root", str(tmp_path),
            "--now", "2026-05-19T12:00:00+00:00",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "--marker-out is required" in err


# ----------------------------------------------------------------------
# P13. Tag-59 workflow YAML well-formed and pins helper.
# ----------------------------------------------------------------------


def test_p13_tag59_workflow_yaml_shape():
    assert TAG59_WORKFLOW.is_file(), f"missing workflow: {TAG59_WORKFLOW}"
    data = yaml.safe_load(TAG59_WORKFLOW.read_text(encoding="utf-8"))
    assert data["name"] == "ots-pre-anchor-activation-probe"
    on = data.get("on", data.get(True))
    assert "pull_request" in on
    assert "push" in on
    assert "workflow_dispatch" in on
    jobs = data["jobs"]
    assert "ots-pre-anchor-activation-probe" in jobs
    steps = jobs["ots-pre-anchor-activation-probe"]["steps"]
    step_text = "\n".join(
        s.get("run", "") for s in steps if isinstance(s, dict)
    )
    assert "tooling/ots/emit_manifest_hash_ots_marker.py" in step_text
    assert "--mode pre-activation-probe" in step_text
    assert "tests/ci/test_ots_pre_anchor_activation_probe_tag59.py" in step_text
    # Stage 3 verdict literal.
    assert "PROBE-READY" in step_text
    assert "PROBE-DEFECT" in step_text


# ----------------------------------------------------------------------
# P14. Runbook doc has §6 + §7 sections.
# ----------------------------------------------------------------------


def test_p14_runbook_has_section_6_and_7():
    assert K2_DOC.is_file(), f"missing: {K2_DOC}"
    text = K2_DOC.read_text(encoding="utf-8")
    assert "## 6. Pre-Activation-Probe-Mode" in text
    assert "## 7. AR-Authorisierungs-Pfad" in text
    # §6 must reference the new CLI surface.
    assert "--mode pre-activation-probe" in text
    assert "--probe-verdict-out" in text
    # §7 must reference KW-24 cutover gate and Reza PR #371 anchor.
    assert "KW-24" in text
    assert "PR #371" in text or "Tag-58 PR #371" in text
    # Old §5 invariants section is preserved (Tag-57 backwards anchor).
    assert "## 5. CI-Side Invariants" in text


# ----------------------------------------------------------------------
# P15. Real pre-cutover manifests from the in-tree registry probe READY.
# ----------------------------------------------------------------------


def test_p15_real_registry_manifests_probe_ready(tmp_path: Path, k2_module):
    registry = json.loads(K2_STUB.read_text(encoding="utf-8"))
    paths = [Path(m["path"]) for m in registry["wired_manifests"]]
    assert len(paths) == 3, "expected exactly 3 pre-cutover manifests"
    for rel in paths:
        manifest = REPO_ROOT / rel
        assert manifest.is_file(), f"registry points at missing manifest: {rel}"
        out = tmp_path / f"{manifest.name}.verdict.json"
        rc = k2_module.main(
            [
                "--mode", "pre-activation-probe",
                "--manifest", str(manifest),
                "--probe-verdict-out", str(out),
                "--actor", "tomas",
                "--repo-root", str(REPO_ROOT),
                "--now", "2026-05-19T12:00:00+00:00",
            ]
        )
        assert rc == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["verdict"] == "PROBE-READY", (
            f"{rel} probe-defective: {payload['stages']}"
        )
        assert len(payload["manifest_sha256"]) == 64


# ----------------------------------------------------------------------
# P16. Probe never imports network-capable modules.
# ----------------------------------------------------------------------


def test_p16_probe_never_imports_network_modules():
    imports = _toplevel_imports(K2_EMIT)
    forbidden = imports & NETWORK_FORBIDDEN
    assert not forbidden, (
        f"Tag-59 helper imports network/subprocess modules: {forbidden}"
    )
