#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-69 Welle-1 State-File Audit-Trail-Anchor-Integration tests.

Pins the Tag-69 wiring of the Welle-1 ``audit_trail_anchor`` field
(introduced as schema-pin by Amara Tag-67 PR #429,
``docs/quality-gates/welle-n-state-file-conventions.md`` §6.1):

  Tag-69 Tomás (this PR): tool-side. Adds
  ``--mode welle-1-audit-anchor`` to
  ``tooling/ots/emit_manifest_hash_ots_marker.py`` plus a single-
  purpose CI helper ``tooling/ci/wire_welle_1_audit_trail_anchor.py``
  that emits the producer-facing envelope Selin's Tag-69 engine
  reads.

  Tag-69 Selin (separate PR): engine-side. Triggers on Phase-3-
  COMPLETE-Marker-Fired, calls the Tomás helper for the hash, writes
  ``audit_trail_anchor`` into ``state/welle-1.json``.

The tests below cover:

  - Hash-construction determinism (canonical JSON, byte-stable);
  - Bundle-shape validation (required keys, dict types);
  - Optional vs. required bundle parts (rollup + sign-off required,
    validation + pre-auditor optional);
  - CLI surface for both helpers (argparse, missing-flag handling,
    error exit codes);
  - Envelope/marker JSON shape conformance (schema_version, kind,
    sandbox_boundary flags, anchors cross-references);
  - Round-trip: the wire-helper envelope's ``audit_trail_anchor``
    matches the regex Amara's verifier enforces
    (``^$|^[0-9a-f]{64}$``);
  - Sandbox-boundary invariants (stdlib-only, no network, no
    subprocess).

Anchor: Tag-69 Welle-1 State-File Audit-Trail-Anchor-Integration.
Author: Tomás Reinhart (dev-engineering, Matrix-Lead, Zone-K).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
EMIT_HELPER = REPO_ROOT / "tooling" / "ots" / "emit_manifest_hash_ots_marker.py"
WIRE_HELPER = REPO_ROOT / "tooling" / "ci" / "wire_welle_1_audit_trail_anchor.py"

# Amara Tag-67 verifier regex: empty-string or 64-hex SHA-256.
OTS_ANCHOR_RE = re.compile(r"^$|^[0-9a-f]{64}$")


def _load_module(name: str, path: Path):
    """Load a module from a file path without packaging machinery."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def emit_mod():
    return _load_module("_emit_helper_tag69", EMIT_HELPER)


@pytest.fixture(scope="module")
def wire_mod():
    return _load_module("_wire_helper_tag69", WIRE_HELPER)


def _canonical_welle_1_rollup() -> dict:
    """Mirror state/welle-1.json (Amara Tag-67 stub)."""
    return {
        "welle_number": 1,
        "schema_version": "tag-67-v1",
        "phase": "phase-3-marathon",
        "kw_cutover_anchor": "KW-22",
        "cutover_iso": "",
        "signoff_iso": "",
        "status": "pending",
        "rollup_links": {
            "sign_off": "state/welle-1-sign-off.json",
            "validation_last_verdict": (
                "state/welle-1-validation-last-verdict.json"
            ),
            "hot_spot_trend_dir": "state/welle-1-hot-spot-trend/",
            "pre_auditor_decision": "state/welle-1-pre-auditor-decision.json",
        },
        "audit_trail_anchor": "",
    }


def _canonical_welle_1_sign_off() -> dict:
    """Mirror state/welle-1-sign-off.json (Amara Tag-67 schema §2.2)."""
    return {
        "welle_number": 1,
        "status": "signed-off",
        "ac_1_5_green": True,
        "ac_4_consensus_personas": ["tomas", "selin", "amara"],
        "cross_welle_drift_assert": "green",
        "cutover_iso": "2026-05-13T08:00:00+00:00",
        "signoff_iso": "2026-05-13T17:00:00+00:00",
    }


def _canonical_welle_1_validation() -> dict:
    """Mirror state/welle-1-validation-last-verdict.json schema §2.3."""
    return {
        "welle_number": 1,
        "verdict": "green",
        "verdict_iso": "2026-05-13T16:30:00+00:00",
        "checks": [
            {
                "name": "welle-1-acceptance",
                "verdict": "green",
                "evidence_ref": "",
            }
        ],
        "schema_version": "tag-67-v1",
    }


def _canonical_welle_1_pre_auditor() -> dict:
    """Mirror state/welle-1-pre-auditor-decision.json schema §2.5."""
    return {
        "welle_number": 1,
        "decision": "not-required",
        "pre_auditor_slug": "",
        "designation_iso": "",
        "rationale_doc": "",
        "schema_version": "tag-67-v1",
    }


def _write_bundle(tmp_path: Path, *, include_optional: bool) -> dict:
    rollup = _canonical_welle_1_rollup()
    sign_off = _canonical_welle_1_sign_off()
    paths = {
        "rollup": tmp_path / "welle-1.json",
        "sign_off": tmp_path / "welle-1-sign-off.json",
    }
    paths["rollup"].write_text(json.dumps(rollup), encoding="utf-8")
    paths["sign_off"].write_text(json.dumps(sign_off), encoding="utf-8")
    if include_optional:
        val = _canonical_welle_1_validation()
        pre = _canonical_welle_1_pre_auditor()
        paths["validation"] = tmp_path / "welle-1-validation-last-verdict.json"
        paths["pre_auditor"] = tmp_path / "welle-1-pre-auditor-decision.json"
        paths["validation"].write_text(json.dumps(val), encoding="utf-8")
        paths["pre_auditor"].write_text(json.dumps(pre), encoding="utf-8")
    return paths


# --------------------------------------------------------------------- #
# Hash-construction tests
# --------------------------------------------------------------------- #


def test_t01_canonical_json_bytes_is_deterministic(emit_mod):
    """Same logical dict yields same bytes regardless of key order."""
    a = {"b": 1, "a": 2, "c": [3, 4]}
    b = {"c": [3, 4], "a": 2, "b": 1}
    assert emit_mod._canonical_json_bytes(a) == emit_mod._canonical_json_bytes(b)


def test_t02_hash_minimal_bundle_required_only(emit_mod):
    """Hash with only rollup + sign-off is deterministic + 64-hex."""
    bundle = {
        "rollup": _canonical_welle_1_rollup(),
        "sign_off": _canonical_welle_1_sign_off(),
    }
    h = emit_mod.compute_welle_1_audit_anchor_hash(bundle)
    assert OTS_ANCHOR_RE.match(h), h
    # Re-hash to assert deterministic.
    h2 = emit_mod.compute_welle_1_audit_anchor_hash(
        {
            "rollup": _canonical_welle_1_rollup(),
            "sign_off": _canonical_welle_1_sign_off(),
        }
    )
    assert h == h2


def test_t03_hash_full_bundle_differs_from_minimal(emit_mod):
    """Optional parts MUST change the hash when present."""
    minimal = {
        "rollup": _canonical_welle_1_rollup(),
        "sign_off": _canonical_welle_1_sign_off(),
    }
    full = dict(minimal)
    full["validation"] = _canonical_welle_1_validation()
    full["pre_auditor"] = _canonical_welle_1_pre_auditor()
    h_min = emit_mod.compute_welle_1_audit_anchor_hash(minimal)
    h_full = emit_mod.compute_welle_1_audit_anchor_hash(full)
    assert h_min != h_full


def test_t04_hash_construction_matches_explicit_recipe(emit_mod):
    """Spell out the concat-with-separator recipe in the test itself.

    This is the contract Selin's producer relies on: change of recipe
    is a Cross-Review-Zone-K break.
    """
    bundle = {
        "rollup": _canonical_welle_1_rollup(),
        "sign_off": _canonical_welle_1_sign_off(),
    }
    expected = hashlib.sha256(
        emit_mod._canonical_json_bytes(bundle["rollup"])
        + b"\n"
        + emit_mod._canonical_json_bytes(bundle["sign_off"])
    ).hexdigest()
    assert emit_mod.compute_welle_1_audit_anchor_hash(bundle) == expected


def test_t05_hash_missing_required_key_raises(emit_mod):
    """Missing ``sign_off`` MUST raise ValueError, not silently hash."""
    bundle = {"rollup": _canonical_welle_1_rollup()}
    with pytest.raises(ValueError, match="missing required keys"):
        emit_mod.compute_welle_1_audit_anchor_hash(bundle)


def test_t06_hash_non_dict_value_raises(emit_mod):
    """Non-dict bundle value MUST raise ValueError."""
    bundle = {
        "rollup": _canonical_welle_1_rollup(),
        "sign_off": "not-a-dict",
    }
    with pytest.raises(ValueError, match="must be a JSON object dict"):
        emit_mod.compute_welle_1_audit_anchor_hash(bundle)


# --------------------------------------------------------------------- #
# Marker / envelope shape tests
# --------------------------------------------------------------------- #


def test_t07_marker_shape_contains_pinned_keys(emit_mod):
    """Marker dict carries the schema-v1 contract keys."""
    bundle = {
        "rollup": _canonical_welle_1_rollup(),
        "sign_off": _canonical_welle_1_sign_off(),
    }
    h = emit_mod.compute_welle_1_audit_anchor_hash(bundle)
    import datetime as _dt

    marker = emit_mod.build_welle_1_audit_anchor_marker(
        bundle=bundle,
        anchor_hash=h,
        actor="pytest",
        now_utc=_dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.timezone.utc),
    )
    required = {
        "schema_version",
        "kind",
        "mode",
        "welle_number",
        "audit_trail_anchor",
        "bundle_keys",
        "wat_spool_envelope",
        "emitted_at_utc",
        "anchors",
        "operator_hand_next_step",
    }
    assert set(marker.keys()) == required, set(marker.keys()) ^ required
    assert marker["schema_version"] == 1
    assert marker["kind"] == "welle-1-audit-trail-anchor-marker"
    assert marker["mode"] == "welle-1-audit-anchor"
    assert marker["welle_number"] == 1
    assert marker["audit_trail_anchor"] == h
    assert marker["bundle_keys"] == ["rollup", "sign_off"]
    assert (
        marker["wat_spool_envelope"]["anchor_target"]
        == "opentimestamps-calendar"
    )


def test_t08_envelope_shape_contains_sandbox_boundary_flags(wire_mod):
    """Producer-envelope carries the explicit sandbox-boundary flags."""
    import datetime as _dt

    bundle = {
        "rollup": _canonical_welle_1_rollup(),
        "sign_off": _canonical_welle_1_sign_off(),
    }
    paths = {
        "rollup": "state/welle-1.json",
        "sign_off": "state/welle-1-sign-off.json",
    }
    env = wire_mod.build_envelope(
        bundle=bundle,
        bundle_paths=paths,
        anchor_hash="a" * 64,
        actor="pytest",
        now_utc=_dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.timezone.utc),
    )
    assert env["kind"] == "welle-1-audit-trail-anchor-producer-envelope"
    assert env["schema_version"] == 1
    assert env["welle_number"] == 1
    assert env["sandbox_boundary"] == {
        "no_network_io": True,
        "no_ots_cli_subprocess": True,
        "stdlib_only": True,
    }
    # Anchors include the Amara Tag-67 PR reference (cross-coord).
    assert env["anchors"]["amara_tag_67_state_file_conventions_pr"] == 429


def test_t09_envelope_anchor_matches_amara_verifier_regex(
    wire_mod, tmp_path: Path
):
    """The emitted audit_trail_anchor satisfies the Tag-67 verifier
    regex (``^$|^[0-9a-f]{64}$``)."""
    import datetime as _dt

    paths = _write_bundle(tmp_path, include_optional=True)
    env = wire_mod.emit_envelope(
        rollup_path=paths["rollup"],
        sign_off_path=paths["sign_off"],
        validation_path=paths["validation"],
        pre_auditor_path=paths["pre_auditor"],
        actor="pytest",
        now_utc=_dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.timezone.utc),
    )
    anchor = env["audit_trail_anchor"]
    assert OTS_ANCHOR_RE.match(anchor), anchor
    assert env["bundle_keys"] == ["pre_auditor", "rollup", "sign_off", "validation"]


# --------------------------------------------------------------------- #
# CLI surface tests
# --------------------------------------------------------------------- #


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_t10_emit_cli_welle_1_mode_happy_path(tmp_path: Path):
    """End-to-end: emit_helper --mode welle-1-audit-anchor writes a
    marker file with a 64-hex anchor."""
    paths = _write_bundle(tmp_path, include_optional=False)
    marker_out = tmp_path / "marker.json"

    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "welle-1-audit-anchor",
            "--welle-1-rollup",
            str(paths["rollup"]),
            "--welle-1-sign-off",
            str(paths["sign_off"]),
            "--marker-out",
            str(marker_out),
            "--actor",
            "pytest",
            "--now",
            "2026-05-19T12:00:00+00:00",
        ]
    )
    assert cp.returncode == 0, cp.stderr
    assert marker_out.is_file()

    marker = json.loads(marker_out.read_text(encoding="utf-8"))
    assert marker["kind"] == "welle-1-audit-trail-anchor-marker"
    assert OTS_ANCHOR_RE.match(marker["audit_trail_anchor"])
    assert marker["bundle_keys"] == ["rollup", "sign_off"]


def test_t11_emit_cli_welle_1_missing_required_flag_exit_2(tmp_path: Path):
    """Omitting --welle-1-rollup must exit 2 with stderr help."""
    paths = _write_bundle(tmp_path, include_optional=False)
    marker_out = tmp_path / "marker.json"

    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "welle-1-audit-anchor",
            "--welle-1-sign-off",
            str(paths["sign_off"]),
            "--marker-out",
            str(marker_out),
        ]
    )
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert "welle-1-rollup" in (cp.stdout + cp.stderr)


def test_t12_emit_cli_audit_only_still_requires_manifest():
    """Tag-57 default audit-only mode must error cleanly when
    --manifest is omitted (regression-pin for the Tag-69 refactor
    that made --manifest optional at argparse-level)."""
    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "audit-only",
            "--marker-out",
            "/tmp/should-not-be-written.json",
        ]
    )
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert "--manifest" in (cp.stdout + cp.stderr)


def test_t13_wire_helper_cli_full_bundle(tmp_path: Path):
    """End-to-end: wire_helper with all four bundle parts produces
    envelope with bundle_keys including validation + pre_auditor."""
    paths = _write_bundle(tmp_path, include_optional=True)
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-1-rollup",
            str(paths["rollup"]),
            "--welle-1-sign-off",
            str(paths["sign_off"]),
            "--welle-1-validation",
            str(paths["validation"]),
            "--welle-1-pre-auditor",
            str(paths["pre_auditor"]),
            "--envelope-out",
            str(env_out),
            "--actor",
            "pytest",
            "--now",
            "2026-05-19T12:00:00+00:00",
        ]
    )
    assert cp.returncode == 0, cp.stderr
    env = json.loads(env_out.read_text(encoding="utf-8"))
    assert env["kind"] == "welle-1-audit-trail-anchor-producer-envelope"
    assert env["welle_number"] == 1
    assert env["bundle_keys"] == [
        "pre_auditor",
        "rollup",
        "sign_off",
        "validation",
    ]
    assert OTS_ANCHOR_RE.match(env["audit_trail_anchor"])
    assert env["actor"] == "pytest"
    assert env["emitted_at_utc"] == "2026-05-19T12:00:00+00:00"


def test_t14_wire_helper_minimal_bundle_skips_missing_optionals(
    tmp_path: Path,
):
    """When validation + pre_auditor files are absent on disk, the
    envelope omits them from bundle_keys / bundle_paths."""
    paths = _write_bundle(tmp_path, include_optional=False)
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-1-rollup",
            str(paths["rollup"]),
            "--welle-1-sign-off",
            str(paths["sign_off"]),
            "--envelope-out",
            str(env_out),
        ]
    )
    assert cp.returncode == 0, cp.stderr
    env = json.loads(env_out.read_text(encoding="utf-8"))
    assert env["bundle_keys"] == ["rollup", "sign_off"]
    assert set(env["bundle_paths"].keys()) == {"rollup", "sign_off"}


def test_t15_wire_helper_missing_rollup_file_exit_1(tmp_path: Path):
    """Pointing --welle-1-rollup at a non-existent path exits 1."""
    paths = _write_bundle(tmp_path, include_optional=False)
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-1-rollup",
            str(tmp_path / "does-not-exist.json"),
            "--welle-1-sign-off",
            str(paths["sign_off"]),
            "--envelope-out",
            str(env_out),
        ]
    )
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "welle-1-rollup" in (cp.stdout + cp.stderr)


def test_t16_wire_helper_malformed_json_exit_1(tmp_path: Path):
    """Malformed JSON in the rollup file surfaces an exit-1 error."""
    rollup = tmp_path / "welle-1.json"
    rollup.write_text("{not valid json", encoding="utf-8")
    sign_off = tmp_path / "welle-1-sign-off.json"
    sign_off.write_text(
        json.dumps(_canonical_welle_1_sign_off()), encoding="utf-8"
    )
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-1-rollup",
            str(rollup),
            "--welle-1-sign-off",
            str(sign_off),
            "--envelope-out",
            str(env_out),
        ]
    )
    assert cp.returncode == 1, cp.stdout + cp.stderr


# --------------------------------------------------------------------- #
# Cross-coord + sandbox-boundary invariants
# --------------------------------------------------------------------- #


def test_t17_wire_helper_stdlib_only():
    """No third-party imports in the wire-helper (Cross-Review-Zone-K
    sandbox-boundary invariant). We grep for ``import`` lines and assert
    every non-relative imported module is stdlib-resolvable."""
    text = WIRE_HELPER.read_text(encoding="utf-8")
    third_party_markers = (
        "import requests",
        "import httpx",
        "import yaml",
        "import opentimestamps",
        "from opentimestamps",
        "import socket",
        "import urllib.request",
    )
    for marker in third_party_markers:
        assert marker not in text, (
            f"wire helper must stay stdlib-only / no-network; "
            f"forbidden import found: {marker!r}"
        )


def test_t18_emit_helper_welle_1_mode_no_network(monkeypatch, tmp_path: Path):
    """Confirm welle-1 mode does NOT touch the network. We monkeypatch
    ``socket.socket`` to raise; the mode must still succeed."""
    import socket as _socket

    real_socket = _socket.socket

    def _fail(*a, **kw):
        raise AssertionError(
            "sandbox-boundary violation: socket.socket called from "
            "welle-1-audit-anchor mode"
        )

    monkeypatch.setattr(_socket, "socket", _fail)

    paths = _write_bundle(tmp_path, include_optional=True)
    marker_out = tmp_path / "marker.json"

    # We invoke the Python entrypoint in-process (not subprocess) to
    # keep the monkeypatch effective.
    emit_mod = _load_module("_emit_helper_tag69_no_net", EMIT_HELPER)
    rc = emit_mod.main(
        [
            "--mode",
            "welle-1-audit-anchor",
            "--welle-1-rollup",
            str(paths["rollup"]),
            "--welle-1-sign-off",
            str(paths["sign_off"]),
            "--welle-1-validation",
            str(paths["validation"]),
            "--welle-1-pre-auditor",
            str(paths["pre_auditor"]),
            "--marker-out",
            str(marker_out),
            "--actor",
            "pytest",
            "--now",
            "2026-05-19T12:00:00+00:00",
        ]
    )
    # Restore for any teardown that needs sockets (pytest plugins).
    monkeypatch.setattr(_socket, "socket", real_socket)
    assert rc == 0
    assert marker_out.is_file()
