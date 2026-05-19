#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-70 Welle-2 State-File Audit-Trail-Anchor-Integration tests.

Mirror of the Tag-69 Welle-1 test-suite, parameterised to Welle-2
(Doppelbetrieb-Sealing). Pins the Tag-70 wiring of the Welle-2
``audit_trail_anchor`` field (schema-pin from Amara Tag-67 PR #429
+ Tag-69 Tomás PR #439):

  Tag-70 Tomás (this PR): tool-side. Adds
  ``--mode welle-2-audit-anchor`` to
  ``tooling/ots/emit_manifest_hash_ots_marker.py`` plus a single-
  purpose CI helper ``tooling/ci/wire_welle_2_audit_trail_anchor.py``
  that emits the producer-facing envelope Selin's Tag-70 engine
  reads.

  Tag-70 Selin (separate PR): engine-side. Triggers on Doppelbetrieb-
  Seal-Marker-Fired, calls the Tomás helper for the hash, writes
  ``audit_trail_anchor`` into ``state/welle-2.json``.

Coverage:

  - Hash-construction determinism + recipe identity with Welle-1
    (same recipe, different namespace);
  - Bundle-shape validation (required keys, dict types) — Welle-2
    error messages call out ``welle-2`` not ``welle-1``;
  - Optional vs. required bundle parts;
  - CLI surface for both helpers;
  - Envelope/marker JSON shape conformance with Welle-2-specific
    kind strings + ``welle_number=2``;
  - Amara verifier-regex round-trip (``^$|^[0-9a-f]{64}$``);
  - Sandbox-boundary invariants (stdlib-only, no network).

Anchor: Tag-70 Welle-2 State-File Audit-Trail-Anchor-Integration.
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
WIRE_HELPER = REPO_ROOT / "tooling" / "ci" / "wire_welle_2_audit_trail_anchor.py"

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
    return _load_module("_emit_helper_tag70", EMIT_HELPER)


@pytest.fixture(scope="module")
def wire_mod():
    return _load_module("_wire_helper_tag70", WIRE_HELPER)


def _canonical_welle_2_rollup() -> dict:
    """Mirror state/welle-2.json (Amara Tag-67 stub, welle=2)."""
    return {
        "welle_number": 2,
        "schema_version": "tag-67-v1",
        "phase": "phase-3-marathon",
        "kw_cutover_anchor": "KW-23",
        "cutover_iso": "",
        "signoff_iso": "",
        "status": "pending",
        "rollup_links": {
            "sign_off": "state/welle-2-sign-off.json",
            "validation_last_verdict": (
                "state/welle-2-validation-last-verdict.json"
            ),
            "hot_spot_trend_dir": "state/welle-2-hot-spot-trend/",
            "pre_auditor_decision": "state/welle-2-pre-auditor-decision.json",
        },
        "audit_trail_anchor": "",
    }


def _canonical_welle_2_sign_off() -> dict:
    """Mirror state/welle-2-sign-off.json (Doppelbetrieb-Sealing)."""
    return {
        "welle_number": 2,
        "status": "signed-off",
        "ac_1_5_green": True,
        "ac_4_consensus_personas": ["tomas", "selin", "amara"],
        "cross_welle_drift_assert": "green",
        "doppelbetrieb_seal_iso": "2026-05-20T08:00:00+00:00",
        "cutover_iso": "2026-05-20T09:00:00+00:00",
        "signoff_iso": "2026-05-20T18:00:00+00:00",
    }


def _canonical_welle_2_validation() -> dict:
    return {
        "welle_number": 2,
        "verdict": "green",
        "verdict_iso": "2026-05-20T17:30:00+00:00",
        "checks": [
            {
                "name": "welle-2-doppelbetrieb-acceptance",
                "verdict": "green",
                "evidence_ref": "",
            }
        ],
        "schema_version": "tag-67-v1",
    }


def _canonical_welle_2_pre_auditor() -> dict:
    return {
        "welle_number": 2,
        "decision": "not-required",
        "pre_auditor_slug": "",
        "designation_iso": "",
        "rationale_doc": "",
        "schema_version": "tag-67-v1",
    }


def _write_bundle(tmp_path: Path, *, include_optional: bool) -> dict:
    rollup = _canonical_welle_2_rollup()
    sign_off = _canonical_welle_2_sign_off()
    paths = {
        "rollup": tmp_path / "welle-2.json",
        "sign_off": tmp_path / "welle-2-sign-off.json",
    }
    paths["rollup"].write_text(json.dumps(rollup), encoding="utf-8")
    paths["sign_off"].write_text(json.dumps(sign_off), encoding="utf-8")
    if include_optional:
        val = _canonical_welle_2_validation()
        pre = _canonical_welle_2_pre_auditor()
        paths["validation"] = tmp_path / "welle-2-validation-last-verdict.json"
        paths["pre_auditor"] = tmp_path / "welle-2-pre-auditor-decision.json"
        paths["validation"].write_text(json.dumps(val), encoding="utf-8")
        paths["pre_auditor"].write_text(json.dumps(pre), encoding="utf-8")
    return paths


# --------------------------------------------------------------------- #
# Hash-construction tests
# --------------------------------------------------------------------- #


def test_t01_hash_minimal_bundle_required_only(emit_mod):
    """Hash with only rollup + sign-off is deterministic + 64-hex."""
    bundle = {
        "rollup": _canonical_welle_2_rollup(),
        "sign_off": _canonical_welle_2_sign_off(),
    }
    h = emit_mod.compute_welle_2_audit_anchor_hash(bundle)
    assert OTS_ANCHOR_RE.match(h), h
    h2 = emit_mod.compute_welle_2_audit_anchor_hash(
        {
            "rollup": _canonical_welle_2_rollup(),
            "sign_off": _canonical_welle_2_sign_off(),
        }
    )
    assert h == h2


def test_t02_hash_full_bundle_differs_from_minimal(emit_mod):
    """Optional parts MUST change the hash when present."""
    minimal = {
        "rollup": _canonical_welle_2_rollup(),
        "sign_off": _canonical_welle_2_sign_off(),
    }
    full = dict(minimal)
    full["validation"] = _canonical_welle_2_validation()
    full["pre_auditor"] = _canonical_welle_2_pre_auditor()
    h_min = emit_mod.compute_welle_2_audit_anchor_hash(minimal)
    h_full = emit_mod.compute_welle_2_audit_anchor_hash(full)
    assert h_min != h_full


def test_t03_hash_construction_matches_explicit_recipe(emit_mod):
    """Spell out the concat-with-separator recipe in the test itself.

    This is the contract Selin's Tag-70 producer relies on.
    """
    bundle = {
        "rollup": _canonical_welle_2_rollup(),
        "sign_off": _canonical_welle_2_sign_off(),
    }
    expected = hashlib.sha256(
        emit_mod._canonical_json_bytes(bundle["rollup"])
        + b"\n"
        + emit_mod._canonical_json_bytes(bundle["sign_off"])
    ).hexdigest()
    assert emit_mod.compute_welle_2_audit_anchor_hash(bundle) == expected


def test_t04_hash_recipe_matches_welle_1_for_same_bytes(emit_mod):
    """Welle-1 and Welle-2 share the recipe — same bundle bytes -> same hash.

    Sanity-pin that the two functions remain wire-compatible until /
    unless someone consciously diverges them. If a divergence is
    introduced, this test must be replaced with a divergence-pin.
    """
    rollup = _canonical_welle_2_rollup()
    sign_off = _canonical_welle_2_sign_off()
    bundle = {"rollup": rollup, "sign_off": sign_off}
    h1 = emit_mod.compute_welle_1_audit_anchor_hash(bundle)
    h2 = emit_mod.compute_welle_2_audit_anchor_hash(bundle)
    assert h1 == h2


def test_t05_hash_missing_required_key_raises_welle_2(emit_mod):
    """Missing ``sign_off`` MUST raise ValueError with welle-2 message."""
    bundle = {"rollup": _canonical_welle_2_rollup()}
    with pytest.raises(ValueError, match="welle-2 bundle missing required keys"):
        emit_mod.compute_welle_2_audit_anchor_hash(bundle)


def test_t06_hash_non_dict_value_raises_welle_2(emit_mod):
    """Non-dict bundle value MUST raise ValueError with welle-2 message."""
    bundle = {
        "rollup": _canonical_welle_2_rollup(),
        "sign_off": "not-a-dict",
    }
    with pytest.raises(ValueError, match="welle-2 bundle key 'sign_off'"):
        emit_mod.compute_welle_2_audit_anchor_hash(bundle)


# --------------------------------------------------------------------- #
# Marker / envelope shape tests
# --------------------------------------------------------------------- #


def test_t07_marker_shape_contains_pinned_keys(emit_mod):
    """Marker dict carries the schema-v1 contract keys + welle_number=2."""
    import datetime as _dt

    bundle = {
        "rollup": _canonical_welle_2_rollup(),
        "sign_off": _canonical_welle_2_sign_off(),
    }
    h = emit_mod.compute_welle_2_audit_anchor_hash(bundle)
    marker = emit_mod.build_welle_2_audit_anchor_marker(
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
    assert marker["kind"] == "welle-2-audit-trail-anchor-marker"
    assert marker["mode"] == "welle-2-audit-anchor"
    assert marker["welle_number"] == 2
    assert marker["audit_trail_anchor"] == h
    assert marker["bundle_keys"] == ["rollup", "sign_off"]
    assert (
        marker["wat_spool_envelope"]["anchor_target"]
        == "opentimestamps-calendar"
    )
    assert (
        marker["wat_spool_envelope"]["kind"]
        == "welle-2-audit-trail-anchor-envelope"
    )
    # Doppelbetrieb-context anchor reference.
    assert marker["anchors"]["welle_2_context"] == "doppelbetrieb-sealing"
    # Cross-coord anchor to Tag-69 PR.
    assert marker["anchors"]["tomas_tag_69_welle_1_audit_anchor_pr"] == 439


def test_t08_envelope_shape_contains_sandbox_boundary_flags(wire_mod):
    """Producer-envelope carries the explicit sandbox-boundary flags."""
    import datetime as _dt

    bundle = {
        "rollup": _canonical_welle_2_rollup(),
        "sign_off": _canonical_welle_2_sign_off(),
    }
    paths = {
        "rollup": "state/welle-2.json",
        "sign_off": "state/welle-2-sign-off.json",
    }
    env = wire_mod.build_envelope(
        bundle=bundle,
        bundle_paths=paths,
        anchor_hash="b" * 64,
        actor="pytest",
        now_utc=_dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.timezone.utc),
    )
    assert env["kind"] == "welle-2-audit-trail-anchor-producer-envelope"
    assert env["schema_version"] == 1
    assert env["welle_number"] == 2
    assert env["sandbox_boundary"] == {
        "no_network_io": True,
        "no_ots_cli_subprocess": True,
        "stdlib_only": True,
    }
    assert env["anchors"]["amara_tag_67_state_file_conventions_pr"] == 429
    assert env["anchors"]["tomas_tag_69_welle_1_audit_anchor_pr"] == 439
    assert env["anchors"]["welle_2_context"] == "doppelbetrieb-sealing"


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
    assert env["welle_number"] == 2


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


def test_t10_emit_cli_welle_2_mode_happy_path(tmp_path: Path):
    """End-to-end: emit_helper --mode welle-2-audit-anchor writes a
    marker file with a 64-hex anchor."""
    paths = _write_bundle(tmp_path, include_optional=False)
    marker_out = tmp_path / "marker.json"

    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "welle-2-audit-anchor",
            "--welle-2-rollup",
            str(paths["rollup"]),
            "--welle-2-sign-off",
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
    assert marker["kind"] == "welle-2-audit-trail-anchor-marker"
    assert marker["welle_number"] == 2
    assert OTS_ANCHOR_RE.match(marker["audit_trail_anchor"])
    assert marker["bundle_keys"] == ["rollup", "sign_off"]


def test_t11_emit_cli_welle_2_missing_required_flag_exit_2(tmp_path: Path):
    """Omitting --welle-2-rollup must exit 2 with stderr help."""
    paths = _write_bundle(tmp_path, include_optional=False)
    marker_out = tmp_path / "marker.json"

    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "welle-2-audit-anchor",
            "--welle-2-sign-off",
            str(paths["sign_off"]),
            "--marker-out",
            str(marker_out),
        ]
    )
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert "welle-2-rollup" in (cp.stdout + cp.stderr)


def test_t12_emit_cli_welle_2_missing_marker_out_exit_2(tmp_path: Path):
    """Omitting --marker-out in welle-2-audit-anchor mode must exit 2."""
    paths = _write_bundle(tmp_path, include_optional=False)

    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "welle-2-audit-anchor",
            "--welle-2-rollup",
            str(paths["rollup"]),
            "--welle-2-sign-off",
            str(paths["sign_off"]),
        ]
    )
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert "--marker-out" in (cp.stdout + cp.stderr)


def test_t13_wire_helper_cli_full_bundle(tmp_path: Path):
    """End-to-end: wire_helper with all four bundle parts produces
    envelope with bundle_keys including validation + pre_auditor."""
    paths = _write_bundle(tmp_path, include_optional=True)
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-2-rollup",
            str(paths["rollup"]),
            "--welle-2-sign-off",
            str(paths["sign_off"]),
            "--welle-2-validation",
            str(paths["validation"]),
            "--welle-2-pre-auditor",
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
    assert env["kind"] == "welle-2-audit-trail-anchor-producer-envelope"
    assert env["welle_number"] == 2
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
            "--welle-2-rollup",
            str(paths["rollup"]),
            "--welle-2-sign-off",
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
    """Pointing --welle-2-rollup at a non-existent path exits 1."""
    paths = _write_bundle(tmp_path, include_optional=False)
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-2-rollup",
            str(tmp_path / "does-not-exist.json"),
            "--welle-2-sign-off",
            str(paths["sign_off"]),
            "--envelope-out",
            str(env_out),
        ]
    )
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "welle-2-rollup" in (cp.stdout + cp.stderr)


def test_t16_wire_helper_malformed_json_exit_1(tmp_path: Path):
    """Malformed JSON in the rollup file surfaces an exit-1 error."""
    rollup = tmp_path / "welle-2.json"
    rollup.write_text("{not valid json", encoding="utf-8")
    sign_off = tmp_path / "welle-2-sign-off.json"
    sign_off.write_text(
        json.dumps(_canonical_welle_2_sign_off()), encoding="utf-8"
    )
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-2-rollup",
            str(rollup),
            "--welle-2-sign-off",
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
    """No third-party / network imports in the wire-helper."""
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


def test_t18_emit_helper_welle_2_mode_no_network(monkeypatch, tmp_path: Path):
    """Confirm welle-2 mode does NOT touch the network. We monkeypatch
    ``socket.socket`` to raise; the mode must still succeed."""
    import socket as _socket

    real_socket = _socket.socket

    def _fail(*a, **kw):
        raise AssertionError(
            "sandbox-boundary violation: socket.socket called from "
            "welle-2-audit-anchor mode"
        )

    monkeypatch.setattr(_socket, "socket", _fail)

    paths = _write_bundle(tmp_path, include_optional=True)
    marker_out = tmp_path / "marker.json"

    emit_mod = _load_module("_emit_helper_tag70_no_net", EMIT_HELPER)
    rc = emit_mod.main(
        [
            "--mode",
            "welle-2-audit-anchor",
            "--welle-2-rollup",
            str(paths["rollup"]),
            "--welle-2-sign-off",
            str(paths["sign_off"]),
            "--welle-2-validation",
            str(paths["validation"]),
            "--welle-2-pre-auditor",
            str(paths["pre_auditor"]),
            "--marker-out",
            str(marker_out),
            "--actor",
            "pytest",
            "--now",
            "2026-05-19T12:00:00+00:00",
        ]
    )
    monkeypatch.setattr(_socket, "socket", real_socket)
    assert rc == 0
    assert marker_out.is_file()


def test_t19_welle_1_and_welle_2_kinds_disjoint(emit_mod):
    """Welle-1 and Welle-2 marker/envelope kinds must be distinct strings
    so a downstream consumer can dispatch on ``kind`` unambiguously."""
    assert emit_mod.WELLE_1_KIND_MARKER != emit_mod.WELLE_2_KIND_MARKER
    assert emit_mod.WELLE_1_KIND_ENVELOPE != emit_mod.WELLE_2_KIND_ENVELOPE
    assert "welle-1" in emit_mod.WELLE_1_KIND_MARKER
    assert "welle-2" in emit_mod.WELLE_2_KIND_MARKER


def test_t20_welle_2_mode_constant_present(emit_mod):
    """The Tag-70 mode constant is exposed at module level."""
    assert emit_mod.MODE_WELLE_2_AUDIT_ANCHOR == "welle-2-audit-anchor"
