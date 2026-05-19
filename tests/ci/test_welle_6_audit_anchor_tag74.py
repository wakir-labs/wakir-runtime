#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-74 Welle-6 State-File Audit-Trail-Anchor-Integration tests.

Mirror of the Tag-69 Welle-1 / Tag-70 Welle-2 / Tag-71 Welle-3 /
Tag-72 Welle-4 / Tag-73 Welle-5 test-suites, parameterised to
Welle-6 (``subscribe_loop`` Cutover, KW-27, parallel to Welle-7).
Pins the Tag-74 wiring of the Welle-6 ``audit_trail_anchor`` field
plus the ``subscribe_loop_self_repair_hygiene_tracking`` block.

  Tag-74 Tomás (this PR): tool-side. Adds
  ``--mode welle-6-audit-anchor`` to
  ``tooling/ots/emit_manifest_hash_ots_marker.py`` plus a single-
  purpose CI helper ``tooling/ci/wire_welle_6_audit_trail_anchor.py``
  that emits the producer-facing envelope Selin's Tag-74 engine reads.

  Tag-74 Selin (separate PR): engine-side. Triggers on subscribe_loop
  Cutover-Smoke-Green, calls the Tomás helper for the hash, writes
  ``audit_trail_anchor`` into ``state/welle-6.json``.

Coverage:

  - Hash-construction determinism + recipe identity with
    Welle-1 / 2 / 3 / 4 / 5 (Cross-Substrate-Parity-Markers);
  - Bundle-shape validation (required keys, dict types) — Welle-6
    error messages call out ``welle-6``;
  - Optional vs. required bundle parts;
  - CLI surface for both helpers;
  - Envelope/marker JSON shape conformance with Welle-6-specific
    kind strings + ``welle_number=6`` + ``subscribe_loop_self_repair_
    hygiene_tracking``;
  - Welle-1 / Welle-2 / Welle-3 / Welle-4 / Welle-5 / Welle-6
    kind-disjointness pin (Tag-74 auftrag);
  - Amara verifier-regex round-trip (``^$|^[0-9a-f]{64}$``);
  - Subscribe-Loop-Self-Repair-Hygiene-tracking surfaces correctly
    (active=True vs False, status enum narrowed to canonical set,
    re-subscribe-window-closed flag preserves sign-off precedence);
  - Cross-Substrate-Parity-Markers list surfaces on the marker
    + envelope anchors block;
  - Sandbox-boundary invariants (stdlib-only, no network).

Anchor: Tag-74 Welle-6 State-File Audit-Trail-Anchor-Integration.
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
WIRE_HELPER = REPO_ROOT / "tooling" / "ci" / "wire_welle_6_audit_trail_anchor.py"

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
    return _load_module("_emit_helper_tag74", EMIT_HELPER)


@pytest.fixture(scope="module")
def wire_mod():
    return _load_module("_wire_helper_tag74", WIRE_HELPER)


def _canonical_welle_6_rollup() -> dict:
    """Mirror state/welle-6.json (Amara Tag-67 stub, welle=6).

    Carries the subscribe-loop Self-Repair-Hygiene discipline fields
    plus the last-hygiene-cycle-iso / re-subscribe-window-closed /
    evidence-ref tracking surface fields.
    """
    return {
        "welle_number": 6,
        "schema_version": "tag-67-v1",
        "phase": "phase-3-marathon",
        "kw_cutover_anchor": "KW-27",
        "cutover_iso": "",
        "signoff_iso": "",
        "status": "pending",
        "rollup_links": {
            "sign_off": "state/welle-6-sign-off.json",
            "validation_last_verdict": (
                "state/welle-6-validation-last-verdict.json"
            ),
            "hot_spot_trend_dir": "state/welle-6-hot-spot-trend/",
            "pre_auditor_decision": (
                "state/welle-6-pre-auditor-decision.json"
            ),
        },
        "audit_trail_anchor": "",
        # Tag-74 Welle-6 surface (Tag-73-Lehre, PR #461):
        "subscribe_loop_self_repair_hygiene_active": True,
        "subscribe_loop_self_repair_hygiene_status": "pending",
        "subscribe_loop_last_hygiene_cycle_iso": "",
        "subscribe_loop_re_subscribe_window_closed": False,
        "subscribe_loop_self_repair_hygiene_evidence_ref": "",
    }


def _canonical_welle_6_sign_off() -> dict:
    """Mirror state/welle-6-sign-off.json (subscribe_loop Cutover)."""
    return {
        "welle_number": 6,
        "status": "signed-off",
        "ac_1_5_green": True,
        "ac_4_consensus_personas": ["tomas", "selin", "amara", "noa"],
        "cross_welle_drift_assert": "green",
        "subscribe_loop_cutover_smoke_iso": (
            "2026-06-29T08:00:00+00:00"
        ),
        "cutover_iso": "2026-06-29T09:00:00+00:00",
        "signoff_iso": "2026-06-29T18:00:00+00:00",
        "subscribe_loop_self_repair_hygiene_status": "drilled",
        "subscribe_loop_last_hygiene_cycle_iso": (
            "2026-06-29T07:30:00+00:00"
        ),
        "subscribe_loop_re_subscribe_window_closed": True,
        "subscribe_loop_self_repair_hygiene_evidence_ref": (
            "docs/operations/welle-6-self-repair-hygiene-drill.md"
        ),
    }


def _canonical_welle_6_validation() -> dict:
    return {
        "welle_number": 6,
        "verdict": "green",
        "verdict_iso": "2026-06-29T17:30:00+00:00",
        "checks": [
            {
                "name": "welle-6-subscribe-loop-cutover-acceptance",
                "verdict": "green",
                "evidence_ref": "",
            }
        ],
        "schema_version": "tag-67-v1",
    }


def _canonical_welle_6_pre_auditor() -> dict:
    return {
        "welle_number": 6,
        "decision": "not-required",
        "pre_auditor_slug": "",
        "designation_iso": "",
        "rationale_doc": (
            "docs/internal-audit/welle-6-pre-auditor-not-required.md"
        ),
        "iia_standard_ref": "IIA-1130",
        "schema_version": "tag-67-v1",
    }


def _write_bundle(tmp_path: Path, *, include_optional: bool) -> dict:
    rollup = _canonical_welle_6_rollup()
    sign_off = _canonical_welle_6_sign_off()
    paths = {
        "rollup": tmp_path / "welle-6.json",
        "sign_off": tmp_path / "welle-6-sign-off.json",
    }
    paths["rollup"].write_text(json.dumps(rollup), encoding="utf-8")
    paths["sign_off"].write_text(json.dumps(sign_off), encoding="utf-8")
    if include_optional:
        val = _canonical_welle_6_validation()
        pre = _canonical_welle_6_pre_auditor()
        paths["validation"] = tmp_path / "welle-6-validation-last-verdict.json"
        paths["pre_auditor"] = tmp_path / "welle-6-pre-auditor-decision.json"
        paths["validation"].write_text(json.dumps(val), encoding="utf-8")
        paths["pre_auditor"].write_text(json.dumps(pre), encoding="utf-8")
    return paths


# --------------------------------------------------------------------- #
# Hash-construction tests
# --------------------------------------------------------------------- #


def test_t01_hash_minimal_bundle_required_only(emit_mod):
    """Hash with only rollup + sign-off is deterministic + 64-hex."""
    bundle = {
        "rollup": _canonical_welle_6_rollup(),
        "sign_off": _canonical_welle_6_sign_off(),
    }
    h = emit_mod.compute_welle_6_audit_anchor_hash(bundle)
    assert OTS_ANCHOR_RE.match(h), h
    h2 = emit_mod.compute_welle_6_audit_anchor_hash(
        {
            "rollup": _canonical_welle_6_rollup(),
            "sign_off": _canonical_welle_6_sign_off(),
        }
    )
    assert h == h2


def test_t02_hash_full_bundle_differs_from_minimal(emit_mod):
    """Optional parts MUST change the hash when present."""
    minimal = {
        "rollup": _canonical_welle_6_rollup(),
        "sign_off": _canonical_welle_6_sign_off(),
    }
    full = dict(minimal)
    full["validation"] = _canonical_welle_6_validation()
    full["pre_auditor"] = _canonical_welle_6_pre_auditor()
    h_min = emit_mod.compute_welle_6_audit_anchor_hash(minimal)
    h_full = emit_mod.compute_welle_6_audit_anchor_hash(full)
    assert h_min != h_full


def test_t03_hash_construction_matches_explicit_recipe(emit_mod):
    """Spell out the concat-with-separator recipe in the test itself.

    This is the contract Selin's Tag-74 producer relies on.
    """
    bundle = {
        "rollup": _canonical_welle_6_rollup(),
        "sign_off": _canonical_welle_6_sign_off(),
    }
    expected = hashlib.sha256(
        emit_mod._canonical_json_bytes(bundle["rollup"])
        + b"\n"
        + emit_mod._canonical_json_bytes(bundle["sign_off"])
    ).hexdigest()
    assert emit_mod.compute_welle_6_audit_anchor_hash(bundle) == expected


def test_t04_hash_recipe_matches_welle_1_2_3_4_5_for_same_bytes(emit_mod):
    """Welle-1..6 share the recipe — same bundle bytes -> same hash.

    Cross-Substrate-Parity-Markers (Tag-74 auftrag): sanity-pin that
    the six functions remain wire-compatible until / unless someone
    consciously diverges them. If a divergence is introduced, this
    test must be replaced with a divergence-pin.
    """
    rollup = _canonical_welle_6_rollup()
    sign_off = _canonical_welle_6_sign_off()
    bundle = {"rollup": rollup, "sign_off": sign_off}
    h1 = emit_mod.compute_welle_1_audit_anchor_hash(bundle)
    h2 = emit_mod.compute_welle_2_audit_anchor_hash(bundle)
    h3 = emit_mod.compute_welle_3_audit_anchor_hash(bundle)
    h4 = emit_mod.compute_welle_4_audit_anchor_hash(bundle)
    h5 = emit_mod.compute_welle_5_audit_anchor_hash(bundle)
    h6 = emit_mod.compute_welle_6_audit_anchor_hash(bundle)
    assert h1 == h2 == h3 == h4 == h5 == h6


def test_t05_hash_missing_required_key_raises_welle_6(emit_mod):
    """Missing ``sign_off`` MUST raise ValueError with welle-6 message."""
    bundle = {"rollup": _canonical_welle_6_rollup()}
    with pytest.raises(
        ValueError, match="welle-6 bundle missing required keys"
    ):
        emit_mod.compute_welle_6_audit_anchor_hash(bundle)


def test_t06_hash_non_dict_value_raises_welle_6(emit_mod):
    """Non-dict bundle value MUST raise ValueError with welle-6 message."""
    bundle = {
        "rollup": _canonical_welle_6_rollup(),
        "sign_off": "not-a-dict",
    }
    with pytest.raises(ValueError, match="welle-6 bundle key 'sign_off'"):
        emit_mod.compute_welle_6_audit_anchor_hash(bundle)


# --------------------------------------------------------------------- #
# Subscribe-loop-self-repair-hygiene-tracking derivation tests
# --------------------------------------------------------------------- #


def test_t07_hygiene_tracking_active_with_drilled_status(emit_mod):
    """Bundle with hygiene-active=True yields tracking block where the
    rollup precedence wins for status (rollup pending wins), but the
    sign-off iso + evidence-ref + re-subscribe-window flag fall
    through."""
    bundle = {
        "rollup": _canonical_welle_6_rollup(),
        "sign_off": _canonical_welle_6_sign_off(),
    }
    tracking = emit_mod.derive_subscribe_loop_self_repair_hygiene_tracking(
        bundle
    )
    assert tracking["subscribe_loop_self_repair_hygiene_active"] is True
    # Rollup says "pending" — rollup wins because the derivation prefers
    # rollup over sign-off for the status field.
    assert (
        tracking["subscribe_loop_self_repair_hygiene_status"] == "pending"
    )
    # last-hygiene-cycle-iso & evidence-ref fall back to sign-off when
    # rollup is empty (truthy fallback).
    assert (
        tracking["subscribe_loop_last_hygiene_cycle_iso"]
        == "2026-06-29T07:30:00+00:00"
    )
    assert tracking[
        "subscribe_loop_self_repair_hygiene_evidence_ref"
    ].endswith("self-repair-hygiene-drill.md")
    # Re-subscribe-window-closed: sign-off precedence wins (sign-off=True,
    # rollup=False).
    assert tracking["subscribe_loop_re_subscribe_window_closed"] is True


def test_t08_hygiene_tracking_inactive_defaults_safe(emit_mod):
    """Bundle without the hygiene fields yields safe defaults."""
    rollup_no_flag = {"welle_number": 6, "status": "pending"}
    sign_off_no_flag = {"welle_number": 6, "status": "signed-off"}
    bundle = {"rollup": rollup_no_flag, "sign_off": sign_off_no_flag}
    tracking = emit_mod.derive_subscribe_loop_self_repair_hygiene_tracking(
        bundle
    )
    assert tracking == {
        "subscribe_loop_self_repair_hygiene_active": False,
        "subscribe_loop_self_repair_hygiene_status": "unknown",
        "subscribe_loop_last_hygiene_cycle_iso": "",
        "subscribe_loop_re_subscribe_window_closed": False,
        "subscribe_loop_self_repair_hygiene_evidence_ref": "",
    }


def test_t09_hygiene_tracking_unknown_status_for_garbage(emit_mod):
    """Out-of-vocabulary status string MUST collapse to 'unknown'."""
    rollup = dict(_canonical_welle_6_rollup())
    rollup["subscribe_loop_self_repair_hygiene_status"] = "not-a-real-status"
    bundle = {
        "rollup": rollup,
        "sign_off": _canonical_welle_6_sign_off(),
    }
    tracking = emit_mod.derive_subscribe_loop_self_repair_hygiene_tracking(
        bundle
    )
    assert (
        tracking["subscribe_loop_self_repair_hygiene_status"] == "unknown"
    )
    # Hygiene-active from rollup remains True.
    assert tracking["subscribe_loop_self_repair_hygiene_active"] is True


def test_t10_hygiene_tracking_re_subscribe_window_sign_off_precedence(
    emit_mod,
):
    """Re-subscribe-window-closed: sign-off declaration overrides rollup.

    Discipline (mirrors Welle-5 replay-window precedence): the rollup
    may track pre-cutover state (window=False) while the sign-off
    declares the window closed at cutover-time (window=True). The
    tracking block MUST surface the sign-off value when present.
    """
    rollup = dict(_canonical_welle_6_rollup())
    rollup["subscribe_loop_re_subscribe_window_closed"] = False
    sign_off = dict(_canonical_welle_6_sign_off())
    sign_off["subscribe_loop_re_subscribe_window_closed"] = True
    bundle = {"rollup": rollup, "sign_off": sign_off}
    tracking = emit_mod.derive_subscribe_loop_self_repair_hygiene_tracking(
        bundle
    )
    assert tracking["subscribe_loop_re_subscribe_window_closed"] is True

    # And the inverse: when sign-off is missing the field but rollup
    # carries it, rollup wins as the fallback.
    sign_off_no_field = {"welle_number": 6, "status": "signed-off"}
    rollup_yes = dict(_canonical_welle_6_rollup())
    rollup_yes["subscribe_loop_re_subscribe_window_closed"] = True
    bundle2 = {"rollup": rollup_yes, "sign_off": sign_off_no_field}
    tracking2 = emit_mod.derive_subscribe_loop_self_repair_hygiene_tracking(
        bundle2
    )
    assert tracking2["subscribe_loop_re_subscribe_window_closed"] is True


# --------------------------------------------------------------------- #
# Marker / envelope shape tests
# --------------------------------------------------------------------- #


def test_t11_marker_shape_contains_pinned_keys_and_parity_markers(emit_mod):
    """Marker dict carries the schema-v1 contract keys + welle_number=6
    + subscribe_loop_self_repair_hygiene_tracking + Cross-Substrate-
    Parity-Markers list."""
    import datetime as _dt

    bundle = {
        "rollup": _canonical_welle_6_rollup(),
        "sign_off": _canonical_welle_6_sign_off(),
        "pre_auditor": _canonical_welle_6_pre_auditor(),
    }
    h = emit_mod.compute_welle_6_audit_anchor_hash(bundle)
    marker = emit_mod.build_welle_6_audit_anchor_marker(
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
        "subscribe_loop_self_repair_hygiene_tracking",
        "wat_spool_envelope",
        "emitted_at_utc",
        "anchors",
        "operator_hand_next_step",
    }
    assert set(marker.keys()) == required, set(marker.keys()) ^ required
    assert marker["schema_version"] == 1
    assert marker["kind"] == "welle-6-audit-trail-anchor-marker"
    assert marker["mode"] == "welle-6-audit-anchor"
    assert marker["welle_number"] == 6
    assert marker["audit_trail_anchor"] == h
    # Tracking block surfaced correctly.
    tracking = marker["subscribe_loop_self_repair_hygiene_tracking"]
    assert tracking["subscribe_loop_self_repair_hygiene_active"] is True
    assert tracking["subscribe_loop_re_subscribe_window_closed"] is True
    assert (
        marker["wat_spool_envelope"]["anchor_target"]
        == "opentimestamps-calendar"
    )
    assert (
        marker["wat_spool_envelope"]["kind"]
        == "welle-6-audit-trail-anchor-envelope"
    )
    # Subscribe-loop-context anchor reference.
    assert (
        marker["anchors"]["welle_6_context"]
        == "subscribe-loop-cutover-kw27"
    )
    # Cross-coord anchors to Tag-69..Tag-73.
    assert marker["anchors"]["tomas_tag_69_welle_1_audit_anchor_pr"] == 439
    assert marker["anchors"]["tomas_tag_70_welle_2_audit_anchor_pr"] == 445
    assert marker["anchors"]["tomas_tag_71_welle_3_audit_anchor_pr"] == 450
    assert marker["anchors"]["tomas_tag_72_welle_4_audit_anchor_pr"] == 457
    assert marker["anchors"]["tomas_tag_73_welle_5_audit_anchor_pr"] == 464
    # Tag-73-Lehre carry-through anchor.
    assert (
        marker["anchors"]["subscribe_loop_self_repair_hygiene_discipline"]
        == "tag-73-lehre-pr-461-cross-persona-self-repair-hygiene-fix"
    )
    # Cross-Substrate-Parity-Markers list — Tag-74 auftrag.
    assert marker["anchors"]["cross_substrate_parity_markers"] == [
        "welle-1",
        "welle-2",
        "welle-3",
        "welle-4",
        "welle-5",
        "welle-6",
    ]


def test_t12_envelope_shape_contains_sandbox_boundary_flags(wire_mod):
    """Producer-envelope carries the explicit sandbox-boundary flags
    and the subscribe_loop_self_repair_hygiene_tracking surface."""
    import datetime as _dt

    bundle = {
        "rollup": _canonical_welle_6_rollup(),
        "sign_off": _canonical_welle_6_sign_off(),
        "pre_auditor": _canonical_welle_6_pre_auditor(),
    }
    paths = {
        "rollup": "state/welle-6.json",
        "sign_off": "state/welle-6-sign-off.json",
        "pre_auditor": "state/welle-6-pre-auditor-decision.json",
    }
    tracking_stub = {
        "subscribe_loop_self_repair_hygiene_active": True,
        "subscribe_loop_self_repair_hygiene_status": "drilled",
        "subscribe_loop_last_hygiene_cycle_iso": "2026-06-29T07:30:00+00:00",
        "subscribe_loop_re_subscribe_window_closed": True,
        "subscribe_loop_self_repair_hygiene_evidence_ref": "docs/y.md",
    }
    env = wire_mod.build_envelope(
        bundle=bundle,
        bundle_paths=paths,
        anchor_hash="f" * 64,
        actor="pytest",
        now_utc=_dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.timezone.utc),
        subscribe_loop_self_repair_hygiene_tracking=tracking_stub,
    )
    assert env["kind"] == "welle-6-audit-trail-anchor-producer-envelope"
    assert env["schema_version"] == 1
    assert env["welle_number"] == 6
    assert env["sandbox_boundary"] == {
        "no_network_io": True,
        "no_ots_cli_subprocess": True,
        "stdlib_only": True,
    }
    # Tracking block round-trips.
    assert (
        env["subscribe_loop_self_repair_hygiene_tracking"] == tracking_stub
    )
    # Cross-coord anchors.
    assert env["anchors"]["amara_tag_67_state_file_conventions_pr"] == 429
    assert env["anchors"]["tomas_tag_69_welle_1_audit_anchor_pr"] == 439
    assert env["anchors"]["tomas_tag_70_welle_2_audit_anchor_pr"] == 445
    assert env["anchors"]["tomas_tag_71_welle_3_audit_anchor_pr"] == 450
    assert env["anchors"]["tomas_tag_72_welle_4_audit_anchor_pr"] == 457
    assert env["anchors"]["tomas_tag_73_welle_5_audit_anchor_pr"] == 464
    assert (
        env["anchors"]["welle_6_context"] == "subscribe-loop-cutover-kw27"
    )
    # Cross-Substrate-Parity-Markers list also on the envelope.
    assert env["anchors"]["cross_substrate_parity_markers"] == [
        "welle-1",
        "welle-2",
        "welle-3",
        "welle-4",
        "welle-5",
        "welle-6",
    ]


def test_t13_envelope_anchor_matches_amara_verifier_regex(
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
    assert env["bundle_keys"] == [
        "pre_auditor",
        "rollup",
        "sign_off",
        "validation",
    ]
    assert env["welle_number"] == 6
    assert (
        env["subscribe_loop_self_repair_hygiene_tracking"][
            "subscribe_loop_self_repair_hygiene_active"
        ]
        is True
    )
    # Re-subscribe-window-closed surfaces from the sign-off precedence.
    assert (
        env["subscribe_loop_self_repair_hygiene_tracking"][
            "subscribe_loop_re_subscribe_window_closed"
        ]
        is True
    )


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


def test_t14_emit_cli_welle_6_mode_happy_path(tmp_path: Path):
    """End-to-end: emit_helper --mode welle-6-audit-anchor writes a
    marker file with a 64-hex anchor and the subscribe_loop_self_repair_
    hygiene_tracking block surfaced."""
    paths = _write_bundle(tmp_path, include_optional=True)
    marker_out = tmp_path / "marker.json"

    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "welle-6-audit-anchor",
            "--welle-6-rollup",
            str(paths["rollup"]),
            "--welle-6-sign-off",
            str(paths["sign_off"]),
            "--welle-6-validation",
            str(paths["validation"]),
            "--welle-6-pre-auditor",
            str(paths["pre_auditor"]),
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
    assert marker["kind"] == "welle-6-audit-trail-anchor-marker"
    assert marker["welle_number"] == 6
    assert OTS_ANCHOR_RE.match(marker["audit_trail_anchor"])
    assert marker["bundle_keys"] == [
        "pre_auditor",
        "rollup",
        "sign_off",
        "validation",
    ]
    tracking = marker["subscribe_loop_self_repair_hygiene_tracking"]
    assert tracking["subscribe_loop_self_repair_hygiene_active"] is True
    assert tracking["subscribe_loop_self_repair_hygiene_status"] in {
        "pending",
        "drilled",
        "exempt",
        "unknown",
    }
    assert tracking["subscribe_loop_re_subscribe_window_closed"] is True


def test_t15_emit_cli_welle_6_missing_required_flag_exit_2(tmp_path: Path):
    """Omitting --welle-6-rollup must exit 2 with stderr help."""
    paths = _write_bundle(tmp_path, include_optional=False)
    marker_out = tmp_path / "marker.json"

    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "welle-6-audit-anchor",
            "--welle-6-sign-off",
            str(paths["sign_off"]),
            "--marker-out",
            str(marker_out),
        ]
    )
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert "welle-6-rollup" in (cp.stdout + cp.stderr)


def test_t16_wire_helper_cli_full_bundle(tmp_path: Path):
    """End-to-end: wire_helper with all four bundle parts produces
    envelope with bundle_keys including validation + pre_auditor
    and tracking block surfaced."""
    paths = _write_bundle(tmp_path, include_optional=True)
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-6-rollup",
            str(paths["rollup"]),
            "--welle-6-sign-off",
            str(paths["sign_off"]),
            "--welle-6-validation",
            str(paths["validation"]),
            "--welle-6-pre-auditor",
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
    assert env["kind"] == "welle-6-audit-trail-anchor-producer-envelope"
    assert env["welle_number"] == 6
    assert env["bundle_keys"] == [
        "pre_auditor",
        "rollup",
        "sign_off",
        "validation",
    ]
    assert OTS_ANCHOR_RE.match(env["audit_trail_anchor"])
    assert env["actor"] == "pytest"
    assert env["emitted_at_utc"] == "2026-05-19T12:00:00+00:00"
    tracking = env["subscribe_loop_self_repair_hygiene_tracking"]
    assert tracking["subscribe_loop_self_repair_hygiene_active"] is True
    assert tracking["subscribe_loop_re_subscribe_window_closed"] is True


def test_t17_wire_helper_minimal_bundle_skips_missing_optionals(
    tmp_path: Path,
):
    """When validation + pre_auditor files are absent on disk, the
    envelope omits them from bundle_keys / bundle_paths AND
    the hygiene tracking still surfaces from the rollup + sign-off."""
    paths = _write_bundle(tmp_path, include_optional=False)
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-6-rollup",
            str(paths["rollup"]),
            "--welle-6-sign-off",
            str(paths["sign_off"]),
            "--envelope-out",
            str(env_out),
        ]
    )
    assert cp.returncode == 0, cp.stderr
    env = json.loads(env_out.read_text(encoding="utf-8"))
    assert env["bundle_keys"] == ["rollup", "sign_off"]
    assert set(env["bundle_paths"].keys()) == {"rollup", "sign_off"}
    tracking = env["subscribe_loop_self_repair_hygiene_tracking"]
    assert tracking["subscribe_loop_self_repair_hygiene_active"] is True
    # Rollup status wins (rollup says pending).
    assert (
        tracking["subscribe_loop_self_repair_hygiene_status"] == "pending"
    )
    # Sign-off precedence for the re-subscribe-window flag.
    assert tracking["subscribe_loop_re_subscribe_window_closed"] is True


def test_t18_wire_helper_missing_rollup_file_exit_1(tmp_path: Path):
    """Pointing --welle-6-rollup at a non-existent path exits 1."""
    paths = _write_bundle(tmp_path, include_optional=False)
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-6-rollup",
            str(tmp_path / "does-not-exist.json"),
            "--welle-6-sign-off",
            str(paths["sign_off"]),
            "--envelope-out",
            str(env_out),
        ]
    )
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "welle-6-rollup" in (cp.stdout + cp.stderr)


def test_t19_wire_helper_malformed_json_exit_1(tmp_path: Path):
    """Malformed JSON in the rollup file surfaces an exit-1 error."""
    rollup = tmp_path / "welle-6.json"
    rollup.write_text("{not valid json", encoding="utf-8")
    sign_off = tmp_path / "welle-6-sign-off.json"
    sign_off.write_text(
        json.dumps(_canonical_welle_6_sign_off()), encoding="utf-8"
    )
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-6-rollup",
            str(rollup),
            "--welle-6-sign-off",
            str(sign_off),
            "--envelope-out",
            str(env_out),
        ]
    )
    assert cp.returncode == 1, cp.stdout + cp.stderr


# --------------------------------------------------------------------- #
# Cross-coord + sandbox-boundary invariants
# --------------------------------------------------------------------- #


def test_t20_wire_helper_stdlib_only():
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


def test_t21_emit_helper_welle_6_mode_no_network(monkeypatch, tmp_path: Path):
    """Confirm welle-6 mode does NOT touch the network. We monkeypatch
    ``socket.socket`` to raise; the mode must still succeed."""
    import socket as _socket

    real_socket = _socket.socket

    def _fail(*a, **kw):
        raise AssertionError(
            "sandbox-boundary violation: socket.socket called from "
            "welle-6-audit-anchor mode"
        )

    monkeypatch.setattr(_socket, "socket", _fail)

    paths = _write_bundle(tmp_path, include_optional=True)
    marker_out = tmp_path / "marker.json"

    emit_mod = _load_module("_emit_helper_tag74_no_net", EMIT_HELPER)
    rc = emit_mod.main(
        [
            "--mode",
            "welle-6-audit-anchor",
            "--welle-6-rollup",
            str(paths["rollup"]),
            "--welle-6-sign-off",
            str(paths["sign_off"]),
            "--welle-6-validation",
            str(paths["validation"]),
            "--welle-6-pre-auditor",
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


def test_t22_welle_1_2_3_4_5_6_kinds_disjoint(emit_mod):
    """Welle-1..6 marker/envelope kinds MUST be distinct strings so a
    downstream consumer can dispatch on ``kind`` unambiguously. This
    is the Tag-74 disjointness-pin (per auftrag)."""
    marker_kinds = {
        emit_mod.WELLE_1_KIND_MARKER,
        emit_mod.WELLE_2_KIND_MARKER,
        emit_mod.WELLE_3_KIND_MARKER,
        emit_mod.WELLE_4_KIND_MARKER,
        emit_mod.WELLE_5_KIND_MARKER,
        emit_mod.WELLE_6_KIND_MARKER,
    }
    envelope_kinds = {
        emit_mod.WELLE_1_KIND_ENVELOPE,
        emit_mod.WELLE_2_KIND_ENVELOPE,
        emit_mod.WELLE_3_KIND_ENVELOPE,
        emit_mod.WELLE_4_KIND_ENVELOPE,
        emit_mod.WELLE_5_KIND_ENVELOPE,
        emit_mod.WELLE_6_KIND_ENVELOPE,
    }
    assert len(marker_kinds) == 6, marker_kinds
    assert len(envelope_kinds) == 6, envelope_kinds
    assert "welle-1" in emit_mod.WELLE_1_KIND_MARKER
    assert "welle-2" in emit_mod.WELLE_2_KIND_MARKER
    assert "welle-3" in emit_mod.WELLE_3_KIND_MARKER
    assert "welle-4" in emit_mod.WELLE_4_KIND_MARKER
    assert "welle-5" in emit_mod.WELLE_5_KIND_MARKER
    assert "welle-6" in emit_mod.WELLE_6_KIND_MARKER
    assert "welle-1" in emit_mod.WELLE_1_KIND_ENVELOPE
    assert "welle-2" in emit_mod.WELLE_2_KIND_ENVELOPE
    assert "welle-3" in emit_mod.WELLE_3_KIND_ENVELOPE
    assert "welle-4" in emit_mod.WELLE_4_KIND_ENVELOPE
    assert "welle-5" in emit_mod.WELLE_5_KIND_ENVELOPE
    assert "welle-6" in emit_mod.WELLE_6_KIND_ENVELOPE


def test_t23_welle_6_mode_constant_present(emit_mod):
    """The Tag-74 mode constant is exposed at module level."""
    assert emit_mod.MODE_WELLE_6_AUDIT_ANCHOR == "welle-6-audit-anchor"
    # The Welle-6 ordering / required-key constants are also exposed
    # (Selin's producer imports them).
    assert emit_mod.WELLE_6_BUNDLE_ORDER == (
        "rollup",
        "sign_off",
        "validation",
        "pre_auditor",
    )
    assert emit_mod.WELLE_6_BUNDLE_REQUIRED == frozenset(
        {"rollup", "sign_off"}
    )
    # Status-enum surface is also exposed for downstream consumers
    # who want to validate before persisting.
    assert (
        emit_mod.SUBSCRIBE_LOOP_SELF_REPAIR_HYGIENE_STATUS_VALUES
        == frozenset({"pending", "drilled", "exempt", "unknown"})
    )


def test_t24_emit_cli_welle_6_missing_marker_out_exit_2(tmp_path: Path):
    """Omitting --marker-out in welle-6-audit-anchor mode must exit 2."""
    paths = _write_bundle(tmp_path, include_optional=False)

    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "welle-6-audit-anchor",
            "--welle-6-rollup",
            str(paths["rollup"]),
            "--welle-6-sign-off",
            str(paths["sign_off"]),
        ]
    )
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert "--marker-out" in (cp.stdout + cp.stderr)


def test_t25_emit_cli_welle_6_hygiene_inactive_when_absent(tmp_path: Path):
    """Bundle without the Self-Repair-Hygiene fields surfaces
    hygiene_active=False + status=unknown via the CLI happy path."""
    rollup = {"welle_number": 6, "status": "pending"}
    sign_off = {"welle_number": 6, "status": "signed-off"}
    rollup_path = tmp_path / "welle-6.json"
    sign_off_path = tmp_path / "welle-6-sign-off.json"
    rollup_path.write_text(json.dumps(rollup), encoding="utf-8")
    sign_off_path.write_text(json.dumps(sign_off), encoding="utf-8")
    marker_out = tmp_path / "marker.json"

    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "welle-6-audit-anchor",
            "--welle-6-rollup",
            str(rollup_path),
            "--welle-6-sign-off",
            str(sign_off_path),
            "--marker-out",
            str(marker_out),
            "--now",
            "2026-05-19T12:00:00+00:00",
        ]
    )
    assert cp.returncode == 0, cp.stderr
    marker = json.loads(marker_out.read_text(encoding="utf-8"))
    tracking = marker["subscribe_loop_self_repair_hygiene_tracking"]
    assert tracking["subscribe_loop_self_repair_hygiene_active"] is False
    assert (
        tracking["subscribe_loop_self_repair_hygiene_status"] == "unknown"
    )
    assert tracking["subscribe_loop_last_hygiene_cycle_iso"] == ""
    assert tracking["subscribe_loop_re_subscribe_window_closed"] is False
    assert tracking["subscribe_loop_self_repair_hygiene_evidence_ref"] == ""


def test_t26_marker_cross_substrate_parity_markers_list_pin(emit_mod):
    """The Tag-74 Cross-Substrate-Parity-Markers list MUST be the full
    Welle-1..6 sequence on the marker (auftrag-pin).
    """
    import datetime as _dt

    bundle = {
        "rollup": _canonical_welle_6_rollup(),
        "sign_off": _canonical_welle_6_sign_off(),
    }
    h = emit_mod.compute_welle_6_audit_anchor_hash(bundle)
    marker = emit_mod.build_welle_6_audit_anchor_marker(
        bundle=bundle,
        anchor_hash=h,
        actor="pytest",
        now_utc=_dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.timezone.utc),
    )
    parity = marker["anchors"]["cross_substrate_parity_markers"]
    # Order matters (audit-trail-lineage left-to-right).
    assert parity == ["welle-1", "welle-2", "welle-3", "welle-4", "welle-5", "welle-6"]
    # Length-pin: future welle additions must consciously extend this.
    assert len(parity) == 6
