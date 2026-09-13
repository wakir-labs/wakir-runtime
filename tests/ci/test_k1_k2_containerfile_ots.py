# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for Tag-57 OPEN-K1 + OPEN-K2 closeout.

OPEN-K1: Containerfile base-image SHA digest pin verifier
  (``tooling/ci/verify_containerfile_base_image_digest.py``) plus the
  ``.github/workflows/containerfile-digest-pin-gate.yml`` CI gate.

OPEN-K2: OTS-anchor manifest-hash WAT-spool wiring, audit-only mode
  (``tooling/ots/emit_manifest_hash_ots_marker.py``,
  ``tooling/ots/manifest-hash-ots-anchor-stub.json``,
  ``docs/operations/manifest-hash-ots-anchor-wiring.md``).

Invariants asserted (>=12):

  T01. K1 helper module is stdlib-only.
  T02. K1 helper rejects digest-less FROM in a fixture Containerfile.
  T03. K1 helper accepts full 64-hex SHA digest.
  T04. K1 helper accepts the documented DIGEST_PENDING_* placeholders
       and reports them as info (not violations).
  T05. K1 helper handles multi-stage builds (``AS builder``) and
       ``FROM scratch``.
  T06. K1 helper run against the real repo passes (no violations).
  T07. K1 helper emits JSON report with schema_version=1 + verdict.
  T08. K1 CI workflow is well-formed YAML and pins the verifier
       script.
  T09. K2 helper module is stdlib-only.
  T10. K2 helper emits marker with mode='audit-only' and required
       schema-v1 fields.
  T11. K2 helper computes correct sha256 for a fixture manifest.
  T12. K2 helper '--now' override produces deterministic timestamps.
  T13. K2 anchor-stub JSON registry lists all three pre-cutover
       manifests and points at the runbook doc.
  T14. K2 wiring doc has all five sections and the Operator-Hand
       runbook snippet.

Sandbox boundary: filesystem reads + python stdlib + pytest.
No subprocess for the helpers beyond invoking their ``main()`` via
``importlib``. No network. No ots CLI call. No podman.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

K1_VERIFIER = REPO_ROOT / "tooling" / "ci" / "verify_containerfile_base_image_digest.py"
K1_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "containerfile-digest-pin-gate.yml"

K2_EMIT = REPO_ROOT / "tooling" / "ots" / "emit_manifest_hash_ots_marker.py"
K2_STUB = REPO_ROOT / "tooling" / "ots" / "manifest-hash-ots-anchor-stub.json"
K2_DOC = REPO_ROOT / "docs" / "operations" / "manifest-hash-ots-anchor-wiring.md"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _toplevel_imports(path: Path) -> set[str]:
    """Return the set of distinct top-level module names imported."""
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


@pytest.fixture(scope="module")
def k1_module():
    assert K1_VERIFIER.is_file(), f"missing: {K1_VERIFIER}"
    return _load_module("_k1_verify_containerfile_digest", K1_VERIFIER)


@pytest.fixture(scope="module")
def k2_module():
    assert K2_EMIT.is_file(), f"missing: {K2_EMIT}"
    return _load_module("_k2_emit_manifest_hash_ots_marker", K2_EMIT)


# ----------------------------------------------------------------------
# T01. K1 helper is stdlib-only.
# ----------------------------------------------------------------------


def test_t01_k1_stdlib_only():
    imports = _toplevel_imports(K1_VERIFIER)
    extras = imports - STDLIB_ALLOW
    assert not extras, f"K1 helper has non-stdlib imports: {extras}"


# ----------------------------------------------------------------------
# T02-T05. K1 helper FROM-line semantics.
# ----------------------------------------------------------------------


def _write_containerfile(root: Path, rel_path: str, body: str) -> Path:
    p = root / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_t02_digestless_from_is_violation(tmp_path: Path, k1_module):
    _write_containerfile(
        tmp_path,
        "infra/example/Containerfile",
        "FROM docker.io/library/python:3.13-slim\n",
    )
    report = k1_module.build_report(tmp_path)
    assert report["verdict"] == "FAIL"
    assert len(report["violations"]) == 1
    v = report["violations"][0]
    assert v["reason"] == "missing-digest"
    assert "Containerfile" in v["path"]


def test_t03_full_hex_digest_passes(tmp_path: Path, k1_module):
    real_digest = "a" * 64
    _write_containerfile(
        tmp_path,
        "infra/example/Containerfile",
        f"FROM docker.io/library/python:3.13-slim@sha256:{real_digest}\n",
    )
    report = k1_module.build_report(tmp_path)
    assert report["verdict"] == "PASS"
    assert report["violations"] == []
    assert report["placeholders"] == []
    assert report["from_line_count"] == 1


def test_t04_allowed_placeholder_is_info_not_violation(
    tmp_path: Path, k1_module
):
    _write_containerfile(
        tmp_path,
        "infra/example/Containerfile",
        (
            "FROM docker.io/library/python:3.13-slim"
            "@sha256:DIGEST_PENDING_TOMAS_REVIEW\n"
        ),
    )
    report = k1_module.build_report(tmp_path)
    assert report["verdict"] == "PASS"
    assert report["violations"] == []
    assert len(report["placeholders"]) == 1
    assert report["placeholders"][0]["token"] == "DIGEST_PENDING_TOMAS_REVIEW"


def test_t04b_unknown_placeholder_is_violation(tmp_path: Path, k1_module):
    _write_containerfile(
        tmp_path,
        "infra/example/Containerfile",
        (
            "FROM docker.io/library/python:3.13-slim"
            "@sha256:DIGEST_PENDING_RANDO_REVIEW\n"
        ),
    )
    report = k1_module.build_report(tmp_path)
    assert report["verdict"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["reason"].startswith("unknown-digest-token:")


def test_t05_multistage_and_scratch(tmp_path: Path, k1_module):
    real_digest = "b" * 64
    body = (
        f"FROM docker.io/library/rust:1.85-slim@sha256:{real_digest} AS builder\n"
        "RUN cargo build\n"
        "FROM scratch\n"
        "COPY --from=builder /out /out\n"
    )
    _write_containerfile(tmp_path, "infra/multi/Containerfile", body)
    report = k1_module.build_report(tmp_path)
    assert report["verdict"] == "PASS"
    assert report["from_line_count"] == 2
    assert report["violations"] == []


def test_t05b_comment_lines_with_from_are_ignored(tmp_path: Path, k1_module):
    real_digest = "c" * 64
    body = (
        "# This Containerfile FROM the foo image (docs only).\n"
        f"FROM docker.io/library/python:3.13@sha256:{real_digest}\n"
    )
    _write_containerfile(tmp_path, "infra/cmt/Containerfile", body)
    report = k1_module.build_report(tmp_path)
    assert report["from_line_count"] == 1
    assert report["verdict"] == "PASS"


# ----------------------------------------------------------------------
# T06. K1 helper run against the real repo passes.
# ----------------------------------------------------------------------


def test_t06_real_repo_passes(k1_module):
    report = k1_module.build_report(REPO_ROOT)
    # Every Containerfile in infra/ must either have a real hex
    # digest or one of the allowed placeholder tokens.
    assert report["verdict"] == "PASS", (
        f"real-repo digest scan has violations: {report['violations']}"
    )
    assert report["containerfile_count"] >= 10
    assert report["from_line_count"] >= 10


# ----------------------------------------------------------------------
# T07. JSON report shape.
# ----------------------------------------------------------------------


def test_t07_report_schema_shape(tmp_path: Path, k1_module):
    report_path = tmp_path / "report.json"
    rc = k1_module.main(
        [
            "--repo-root",
            str(REPO_ROOT),
            "--report",
            str(report_path),
            "--quiet",
        ]
    )
    assert rc == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["kind"] == "containerfile-base-image-digest-pin-report"
    assert payload["verdict"] in {"PASS", "FAIL"}
    assert "violations" in payload
    assert "placeholders" in payload
    assert "scanned_at_utc" in payload


# ----------------------------------------------------------------------
# T08. K1 workflow shape.
# ----------------------------------------------------------------------


def test_t08_k1_workflow_yaml():
    assert K1_WORKFLOW.is_file(), f"missing workflow: {K1_WORKFLOW}"
    data = yaml.safe_load(K1_WORKFLOW.read_text(encoding="utf-8"))
    assert data["name"] == "containerfile-digest-pin-gate"
    on = data.get("on", data.get(True))
    assert "pull_request" in on
    assert "push" in on
    jobs = data["jobs"]
    assert "verify-digest-pins" in jobs
    steps = jobs["verify-digest-pins"]["steps"]
    step_text = "\n".join(
        s.get("run", "") for s in steps if isinstance(s, dict)
    )
    assert "tooling/ci/verify_containerfile_base_image_digest.py" in step_text


# ----------------------------------------------------------------------
# T09-T12. K2 helper.
# ----------------------------------------------------------------------


def test_t09_k2_stdlib_only():
    imports = _toplevel_imports(K2_EMIT)
    extras = imports - STDLIB_ALLOW
    assert not extras, f"K2 helper has non-stdlib imports: {extras}"


def test_t10_k2_marker_schema(tmp_path: Path, k2_module):
    manifest = tmp_path / "MANIFEST-fixture.md"
    manifest.write_text("fixture body\n", encoding="utf-8")
    marker = tmp_path / "out" / "fixture.json"
    rc = k2_module.main(
        [
            "--manifest",
            str(manifest),
            "--marker-out",
            str(marker),
            "--actor",
            "tomas",
            "--repo-root",
            str(tmp_path),
            "--now",
            "2026-05-19T12:00:00+00:00",
        ]
    )
    assert rc == 0
    payload = json.loads(marker.read_text(encoding="utf-8"))
    expected_keys = {
        "schema_version",
        "kind",
        "mode",
        "manifest_path",
        "manifest_sha256",
        "manifest_size_bytes",
        "wat_spool_envelope",
        "emitted_at_utc",
        "anchors",
        "operator_hand_next_step",
    }
    assert set(payload.keys()) == expected_keys, (
        f"unexpected top-level keys: {set(payload.keys()) ^ expected_keys}"
    )
    assert payload["schema_version"] == 1
    assert payload["kind"] == "manifest-hash-ots-anchor-marker"
    assert payload["mode"] == "audit-only"
    env = payload["wat_spool_envelope"]
    assert env["kind"] == "ots-anchor-request"
    assert env["anchor_target"] == "opentimestamps-calendar"
    assert env["actor"] == "tomas"


def test_t11_k2_sha256_correct(tmp_path: Path, k2_module):
    manifest = tmp_path / "MANIFEST-deterministic.md"
    body = b"hash this exactly\n"
    manifest.write_bytes(body)
    expected = hashlib.sha256(body).hexdigest()
    marker = tmp_path / "out" / "det.json"
    rc = k2_module.main(
        [
            "--manifest",
            str(manifest),
            "--marker-out",
            str(marker),
            "--now",
            "2026-05-19T12:00:00+00:00",
        ]
    )
    assert rc == 0
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["manifest_sha256"] == expected
    assert payload["manifest_size_bytes"] == len(body)
    assert payload["wat_spool_envelope"]["manifest_sha256"] == expected


def test_t12_k2_now_override_deterministic(tmp_path: Path, k2_module):
    manifest = tmp_path / "MANIFEST-x.md"
    manifest.write_text("x\n", encoding="utf-8")
    marker_a = tmp_path / "a.json"
    marker_b = tmp_path / "b.json"
    iso = "2026-05-19T12:34:56+00:00"
    for out in (marker_a, marker_b):
        rc = k2_module.main(
            [
                "--manifest",
                str(manifest),
                "--marker-out",
                str(out),
                "--actor",
                "tomas",
                "--now",
                iso,
            ]
        )
        assert rc == 0
    pa = json.loads(marker_a.read_text(encoding="utf-8"))
    pb = json.loads(marker_b.read_text(encoding="utf-8"))
    assert pa["emitted_at_utc"] == iso
    assert pa["wat_spool_envelope"]["requested_at_utc"] == iso
    assert pa == pb  # full byte-stability under fixed --now


# ----------------------------------------------------------------------
# T13. K2 stub JSON registry.
# ----------------------------------------------------------------------


def test_t13_k2_stub_registry_shape():
    assert K2_STUB.is_file(), f"missing: {K2_STUB}"
    payload = json.loads(K2_STUB.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["kind"] == "manifest-hash-ots-anchor-stub"
    assert payload["mode"] == "audit-only"
    manifests = payload["wired_manifests"]
    assert isinstance(manifests, list) and len(manifests) == 3
    names = {m["name"] for m in manifests}
    assert names == {
        "MANIFEST-0.5.2-final-pre-cutover",
        "MANIFEST-0.5.1-pre-cutover",
        "MANIFEST-0.5.0-pre-cutover",
    }
    spool = payload["wat_spool"]
    assert spool["emit_helper"] == "tooling/ots/emit_manifest_hash_ots_marker.py"
    assert (
        spool["operator_hand_runbook"]
        == "docs/operations/manifest-hash-ots-anchor-wiring.md"
    )
    sb = payload["sandbox_boundary"]
    assert sb["no_network_io"] is True
    assert sb["no_ots_cli_subprocess"] is True
    assert sb["no_calendar_call"] is True


# ----------------------------------------------------------------------
# T14. K2 wiring doc sections + runbook snippet.
# ----------------------------------------------------------------------


def test_t14_k2_wiring_doc_sections():
    assert K2_DOC.is_file(), f"missing: {K2_DOC}"
    text = K2_DOC.read_text(encoding="utf-8")
    required_sections = (
        "## 1. Scope and Sandbox Boundary",
        "## 2. Wiring Topology",
        "## 3. Marker Schema",
        "## 4. Operator-Hand Runbook",
        "## 5. CI-Side Invariants",
    )
    for section in required_sections:
        assert section in text, f"missing section: {section}"
    # Operator-Hand runbook must mention the three OTS CLI steps.
    assert "ots stamp" in text
    assert "ots upgrade" in text
    assert "ots verify" in text
    # Sandbox boundary must be explicit about no network / no OTS CLI.
    assert "No host-podman-socket access" in text
    assert "No outbound network" in text
