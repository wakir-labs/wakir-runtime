#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-75 Welle-7 State-File Audit-Trail-Anchor-Integration tests.

FINAL Welle of the Phase-3c-Welle-Marathon. Mirror of the Tag-69..
Tag-74 test-suites, parameterised to Welle-7 (KW-27 Doppel-Welle-
6+7 entry, Cutover-Mittwoch 2026-07-01, Sign-off-Freitag 2026-07-03
= Global Acceptance-Verdict per
``docs/quality-gates/pre-cutover-acceptance-run-order.md`` §3.2).

  Tag-75 Tomás (this PR): tool-side. Adds
  ``--mode welle-7-audit-anchor`` to
  ``tooling/ots/emit_manifest_hash_ots_marker.py`` plus a single-
  purpose CI helper ``tooling/ci/wire_welle_7_audit_trail_anchor.py``
  that emits the producer-facing envelope Selin's Tag-75 engine reads.

  Tag-75 Selin (separate PR): engine-side. Triggers on Final-Sealing-
  Smoke-Green, calls the Tomás helper for the hash, writes
  ``audit_trail_anchor`` into ``state/welle-7.json``.

Coverage (>= 12 tests per Tag-75 auftrag):

  - Hash-construction determinism + recipe identity with Welle-1..6
    (Cross-Substrate-Parity-Markers, Welle-1..7-Kind-Disjointness-Pin);
  - Bundle-shape validation (required keys, dict types) — Welle-7
    error messages call out ``welle-7``;
  - Optional vs. required bundle parts;
  - CLI surface for both helpers;
  - Envelope/marker JSON shape conformance with Welle-7-specific
    kind strings + ``welle_number=7`` + ``phase_3_final_sealing_
    tracking`` + Pre-Auditor-Final-Sealing-Signaling-Markers;
  - Welle-1..7-Kind-Disjointness-Pin (Tag-75 auftrag, mandatory);
  - Amara verifier-regex round-trip (``^$|^[0-9a-f]{64}$``);
  - Phase-3-Final-Sealing-Tracking surfaces correctly (active=True
    vs False, status enum narrowed to canonical set, global-
    acceptance-verdict-recorded + Phase-3-COMPLETE-marker-ready
    sign-off precedence);
  - Pre-Auditor-Final-Sealing-Signaling-Markers behaviour (two
    flags, the second requires both pre-auditor present AND global-
    acceptance-verdict-recorded);
  - Cross-Substrate-Parity-Markers list surfaces full Welle-1..7;
  - Sandbox-boundary invariants (stdlib-only, no network).

Anchor: Tag-75 Welle-7 State-File Audit-Trail-Anchor-Integration.
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
WIRE_HELPER = REPO_ROOT / "tooling" / "ci" / "wire_welle_7_audit_trail_anchor.py"

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
    return _load_module("_emit_helper_tag75", EMIT_HELPER)


@pytest.fixture(scope="module")
def wire_mod():
    return _load_module("_wire_helper_tag75", WIRE_HELPER)


def _canonical_welle_7_rollup() -> dict:
    """Mirror state/welle-7.json (Amara Tag-67 stub, welle=7, FINAL).

    Carries the Phase-3-Final-Sealing discipline fields plus the
    sealing-iso / global-acceptance-verdict-recorded / Phase-3-
    COMPLETE-marker-ready / evidence-ref tracking surface fields.
    """
    return {
        "welle_number": 7,
        "schema_version": "tag-67-v1",
        "phase": "phase-3-marathon",
        "kw_cutover_anchor": "KW-27",
        "cutover_iso": "",
        "signoff_iso": "",
        "status": "pending",
        "rollup_links": {
            "sign_off": "state/welle-7-sign-off.json",
            "validation_last_verdict": (
                "state/welle-7-validation-last-verdict.json"
            ),
            "hot_spot_trend_dir": "state/welle-7-hot-spot-trend/",
            "pre_auditor_decision": (
                "state/welle-7-pre-auditor-decision.json"
            ),
        },
        "audit_trail_anchor": "",
        # Tag-75 Welle-7 surface (Phase-3-Final-Sealing):
        "phase_3_final_sealing_active": True,
        "phase_3_final_sealing_status": "pending",
        "phase_3_final_sealing_iso": "",
        "global_acceptance_verdict_recorded": False,
        "phase_3_complete_marker_ready": False,
        "phase_3_final_sealing_evidence_ref": "",
    }


def _canonical_welle_7_sign_off() -> dict:
    """Mirror state/welle-7-sign-off.json (Final-Sealing Cutover).

    Sign-off carries the canonical Final-Sealing-iso, the global-
    acceptance-verdict-recorded flag (verdict-aggregator output),
    and the Phase-3-COMPLETE-marker-ready flag.
    """
    return {
        "welle_number": 7,
        "status": "signed-off",
        "ac_1_5_green": True,
        "ac_4_consensus_personas": [
            "tomas",
            "selin",
            "amara",
            "noa",
            "kai",
            "reza",
        ],
        "cross_welle_drift_assert": "green",
        "final_sealing_cutover_smoke_iso": "2026-07-01T08:00:00+00:00",
        "cutover_iso": "2026-07-01T09:00:00+00:00",
        "signoff_iso": "2026-07-03T15:00:00+00:00",
        "phase_3_final_sealing_status": "sealed",
        "phase_3_final_sealing_iso": "2026-07-03T15:00:00+00:00",
        "global_acceptance_verdict_recorded": True,
        "phase_3_complete_marker_ready": True,
        "phase_3_final_sealing_evidence_ref": (
            "docs/operations/phase-3-final-sealing-runbook.md"
        ),
    }


def _canonical_welle_7_validation() -> dict:
    return {
        "welle_number": 7,
        "verdict": "green",
        "verdict_iso": "2026-07-03T14:30:00+00:00",
        "checks": [
            {
                "name": "welle-7-final-sealing-acceptance",
                "verdict": "green",
                "evidence_ref": "",
            },
            {
                "name": "global-acceptance-verdict",
                "verdict": "green",
                "evidence_ref": "",
            },
        ],
        "schema_version": "tag-67-v1",
    }


def _canonical_welle_7_pre_auditor() -> dict:
    return {
        "welle_number": 7,
        "decision": "required",
        "pre_auditor_slug": "henrik-voss",
        "designation_iso": "2026-06-30T08:00:00+00:00",
        "rationale_doc": (
            "docs/internal-audit/welle-7-pre-auditor-final-sealing.md"
        ),
        "iia_standard_ref": "IIA-1130",
        "schema_version": "tag-67-v1",
    }


def _write_bundle(tmp_path: Path, *, include_optional: bool) -> dict:
    rollup = _canonical_welle_7_rollup()
    sign_off = _canonical_welle_7_sign_off()
    paths = {
        "rollup": tmp_path / "welle-7.json",
        "sign_off": tmp_path / "welle-7-sign-off.json",
    }
    paths["rollup"].write_text(json.dumps(rollup), encoding="utf-8")
    paths["sign_off"].write_text(json.dumps(sign_off), encoding="utf-8")
    if include_optional:
        val = _canonical_welle_7_validation()
        pre = _canonical_welle_7_pre_auditor()
        paths["validation"] = tmp_path / "welle-7-validation-last-verdict.json"
        paths["pre_auditor"] = tmp_path / "welle-7-pre-auditor-decision.json"
        paths["validation"].write_text(json.dumps(val), encoding="utf-8")
        paths["pre_auditor"].write_text(json.dumps(pre), encoding="utf-8")
    return paths


# --------------------------------------------------------------------- #
# Hash-construction tests
# --------------------------------------------------------------------- #


def test_t01_hash_minimal_bundle_required_only(emit_mod):
    """Hash with only rollup + sign-off is deterministic + 64-hex."""
    bundle = {
        "rollup": _canonical_welle_7_rollup(),
        "sign_off": _canonical_welle_7_sign_off(),
    }
    h = emit_mod.compute_welle_7_audit_anchor_hash(bundle)
    assert OTS_ANCHOR_RE.match(h), h
    h2 = emit_mod.compute_welle_7_audit_anchor_hash(
        {
            "rollup": _canonical_welle_7_rollup(),
            "sign_off": _canonical_welle_7_sign_off(),
        }
    )
    assert h == h2


def test_t02_hash_full_bundle_differs_from_minimal(emit_mod):
    """Optional parts MUST change the hash when present."""
    minimal = {
        "rollup": _canonical_welle_7_rollup(),
        "sign_off": _canonical_welle_7_sign_off(),
    }
    full = dict(minimal)
    full["validation"] = _canonical_welle_7_validation()
    full["pre_auditor"] = _canonical_welle_7_pre_auditor()
    h_min = emit_mod.compute_welle_7_audit_anchor_hash(minimal)
    h_full = emit_mod.compute_welle_7_audit_anchor_hash(full)
    assert h_min != h_full


def test_t03_hash_construction_matches_explicit_recipe(emit_mod):
    """Spell out the concat-with-separator recipe in the test itself."""
    bundle = {
        "rollup": _canonical_welle_7_rollup(),
        "sign_off": _canonical_welle_7_sign_off(),
    }
    expected = hashlib.sha256(
        emit_mod._canonical_json_bytes(bundle["rollup"])
        + b"\n"
        + emit_mod._canonical_json_bytes(bundle["sign_off"])
    ).hexdigest()
    assert emit_mod.compute_welle_7_audit_anchor_hash(bundle) == expected


def test_t04_hash_recipe_matches_welle_1_2_3_4_5_6_for_same_bytes(emit_mod):
    """Welle-1..7 share the recipe — same bundle bytes -> same hash.

    Cross-Substrate-Parity-Markers (Tag-75 auftrag, Welle-1..7-Kind-
    Disjointness-Pin): the SEVEN hash functions remain wire-compatible.
    If a divergence is introduced consciously, this test must be
    replaced with a divergence-pin.
    """
    rollup = _canonical_welle_7_rollup()
    sign_off = _canonical_welle_7_sign_off()
    bundle = {"rollup": rollup, "sign_off": sign_off}
    h1 = emit_mod.compute_welle_1_audit_anchor_hash(bundle)
    h2 = emit_mod.compute_welle_2_audit_anchor_hash(bundle)
    h3 = emit_mod.compute_welle_3_audit_anchor_hash(bundle)
    h4 = emit_mod.compute_welle_4_audit_anchor_hash(bundle)
    h5 = emit_mod.compute_welle_5_audit_anchor_hash(bundle)
    h6 = emit_mod.compute_welle_6_audit_anchor_hash(bundle)
    h7 = emit_mod.compute_welle_7_audit_anchor_hash(bundle)
    assert h1 == h2 == h3 == h4 == h5 == h6 == h7


def test_t05_hash_missing_required_key_raises_welle_7(emit_mod):
    """Missing ``sign_off`` MUST raise ValueError with welle-7 message."""
    bundle = {"rollup": _canonical_welle_7_rollup()}
    with pytest.raises(
        ValueError, match="welle-7 bundle missing required keys"
    ):
        emit_mod.compute_welle_7_audit_anchor_hash(bundle)


def test_t06_hash_non_dict_value_raises_welle_7(emit_mod):
    """Non-dict bundle value MUST raise ValueError with welle-7 message."""
    bundle = {
        "rollup": _canonical_welle_7_rollup(),
        "sign_off": "not-a-dict",
    }
    with pytest.raises(ValueError, match="welle-7 bundle key 'sign_off'"):
        emit_mod.compute_welle_7_audit_anchor_hash(bundle)


# --------------------------------------------------------------------- #
# Phase-3-Final-Sealing-Tracking derivation tests
# --------------------------------------------------------------------- #


def test_t07_final_sealing_tracking_active_with_sealed_status(emit_mod):
    """Bundle with sealing-active=True yields tracking block where
    rollup precedence wins for status (rollup says pending wins) but
    the sign-off iso + evidence-ref + global-verdict-recorded +
    Phase-3-COMPLETE-marker-ready fall through with sign-off
    precedence."""
    bundle = {
        "rollup": _canonical_welle_7_rollup(),
        "sign_off": _canonical_welle_7_sign_off(),
    }
    tracking = emit_mod.derive_phase_3_final_sealing_tracking(bundle)
    assert tracking["phase_3_final_sealing_active"] is True
    # Rollup says "pending" — rollup wins because the derivation prefers
    # rollup over sign-off for the status field.
    assert tracking["phase_3_final_sealing_status"] == "pending"
    # sealing-iso & evidence-ref fall back to sign-off when rollup is
    # empty (truthy fallback).
    assert (
        tracking["phase_3_final_sealing_iso"]
        == "2026-07-03T15:00:00+00:00"
    )
    assert tracking["phase_3_final_sealing_evidence_ref"].endswith(
        "phase-3-final-sealing-runbook.md"
    )
    # Sign-off precedence for the two sign-off-canonical fields.
    assert tracking["global_acceptance_verdict_recorded"] is True
    assert tracking["phase_3_complete_marker_ready"] is True


def test_t08_final_sealing_tracking_inactive_defaults_safe(emit_mod):
    """Bundle without the sealing fields yields safe defaults."""
    rollup_no_flag = {"welle_number": 7, "status": "pending"}
    sign_off_no_flag = {"welle_number": 7, "status": "signed-off"}
    bundle = {"rollup": rollup_no_flag, "sign_off": sign_off_no_flag}
    tracking = emit_mod.derive_phase_3_final_sealing_tracking(bundle)
    assert tracking == {
        "phase_3_final_sealing_active": False,
        "phase_3_final_sealing_status": "unknown",
        "phase_3_final_sealing_iso": "",
        "global_acceptance_verdict_recorded": False,
        "phase_3_complete_marker_ready": False,
        "phase_3_final_sealing_evidence_ref": "",
    }


def test_t09_final_sealing_tracking_unknown_status_for_garbage(emit_mod):
    """Out-of-vocabulary status string MUST collapse to 'unknown'."""
    rollup = dict(_canonical_welle_7_rollup())
    rollup["phase_3_final_sealing_status"] = "not-a-real-status"
    bundle = {
        "rollup": rollup,
        "sign_off": _canonical_welle_7_sign_off(),
    }
    tracking = emit_mod.derive_phase_3_final_sealing_tracking(bundle)
    assert tracking["phase_3_final_sealing_status"] == "unknown"
    # Sealing-active from rollup remains True.
    assert tracking["phase_3_final_sealing_active"] is True


def test_t10_final_sealing_tracking_sign_off_precedence_for_verdict_flag(
    emit_mod,
):
    """Global-acceptance-verdict-recorded: sign-off declaration
    overrides rollup. Mirrors Welle-5/6 sign-off-canonical precedence.

    The rollup may track pre-cutover state (recorded=False) while the
    sign-off declares the verdict recorded at sign-off-Freitag time
    (recorded=True). The tracking block MUST surface the sign-off
    value when present.
    """
    rollup = dict(_canonical_welle_7_rollup())
    rollup["global_acceptance_verdict_recorded"] = False
    rollup["phase_3_complete_marker_ready"] = False
    sign_off = dict(_canonical_welle_7_sign_off())
    sign_off["global_acceptance_verdict_recorded"] = True
    sign_off["phase_3_complete_marker_ready"] = True
    bundle = {"rollup": rollup, "sign_off": sign_off}
    tracking = emit_mod.derive_phase_3_final_sealing_tracking(bundle)
    assert tracking["global_acceptance_verdict_recorded"] is True
    assert tracking["phase_3_complete_marker_ready"] is True

    # And the inverse: when sign-off is missing the fields but rollup
    # carries them, rollup wins as the fallback.
    sign_off_no_fields = {"welle_number": 7, "status": "signed-off"}
    rollup_yes = dict(_canonical_welle_7_rollup())
    rollup_yes["global_acceptance_verdict_recorded"] = True
    rollup_yes["phase_3_complete_marker_ready"] = True
    bundle2 = {"rollup": rollup_yes, "sign_off": sign_off_no_fields}
    tracking2 = emit_mod.derive_phase_3_final_sealing_tracking(bundle2)
    assert tracking2["global_acceptance_verdict_recorded"] is True
    assert tracking2["phase_3_complete_marker_ready"] is True


# --------------------------------------------------------------------- #
# Pre-Auditor-Final-Sealing-Signaling-Markers tests
# --------------------------------------------------------------------- #


def test_t11_pre_auditor_signaling_two_flag_semantics(emit_mod):
    """The marker carries TWO pre-auditor signaling flags.

    Tag-75 Final-Welle discipline:

      * ``pre_auditor_signaling_ready`` is True iff pre-auditor-
        decision is present in the bundle.
      * ``pre_auditor_final_sealing_signaling_ready`` is True iff
        ABOVE AND ``global_acceptance_verdict_recorded == True``.

    This test covers the four combinatorial cases:

      (a) pre-auditor present, verdict recorded -> both True
      (b) pre-auditor present, verdict NOT recorded -> first True,
          second False
      (c) pre-auditor absent, verdict recorded -> both False
      (d) pre-auditor absent, verdict NOT recorded -> both False
    """
    import datetime as _dt

    now = _dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.timezone.utc)

    # Case (a): pre-auditor present, verdict recorded.
    bundle_a = {
        "rollup": _canonical_welle_7_rollup(),
        "sign_off": _canonical_welle_7_sign_off(),
        "pre_auditor": _canonical_welle_7_pre_auditor(),
    }
    h_a = emit_mod.compute_welle_7_audit_anchor_hash(bundle_a)
    marker_a = emit_mod.build_welle_7_audit_anchor_marker(
        bundle=bundle_a, anchor_hash=h_a, actor="pytest", now_utc=now
    )
    assert marker_a["pre_auditor_signaling_ready"] is True
    assert marker_a["pre_auditor_final_sealing_signaling_ready"] is True

    # Case (b): pre-auditor present, verdict NOT recorded.
    sign_off_no_verdict = dict(_canonical_welle_7_sign_off())
    sign_off_no_verdict["global_acceptance_verdict_recorded"] = False
    rollup_no_verdict = dict(_canonical_welle_7_rollup())
    rollup_no_verdict["global_acceptance_verdict_recorded"] = False
    bundle_b = {
        "rollup": rollup_no_verdict,
        "sign_off": sign_off_no_verdict,
        "pre_auditor": _canonical_welle_7_pre_auditor(),
    }
    h_b = emit_mod.compute_welle_7_audit_anchor_hash(bundle_b)
    marker_b = emit_mod.build_welle_7_audit_anchor_marker(
        bundle=bundle_b, anchor_hash=h_b, actor="pytest", now_utc=now
    )
    assert marker_b["pre_auditor_signaling_ready"] is True
    assert marker_b["pre_auditor_final_sealing_signaling_ready"] is False

    # Case (c): pre-auditor absent, verdict recorded.
    bundle_c = {
        "rollup": _canonical_welle_7_rollup(),
        "sign_off": _canonical_welle_7_sign_off(),
    }
    h_c = emit_mod.compute_welle_7_audit_anchor_hash(bundle_c)
    marker_c = emit_mod.build_welle_7_audit_anchor_marker(
        bundle=bundle_c, anchor_hash=h_c, actor="pytest", now_utc=now
    )
    assert marker_c["pre_auditor_signaling_ready"] is False
    assert marker_c["pre_auditor_final_sealing_signaling_ready"] is False

    # Case (d): pre-auditor absent, verdict NOT recorded.
    bundle_d = {
        "rollup": rollup_no_verdict,
        "sign_off": sign_off_no_verdict,
    }
    h_d = emit_mod.compute_welle_7_audit_anchor_hash(bundle_d)
    marker_d = emit_mod.build_welle_7_audit_anchor_marker(
        bundle=bundle_d, anchor_hash=h_d, actor="pytest", now_utc=now
    )
    assert marker_d["pre_auditor_signaling_ready"] is False
    assert marker_d["pre_auditor_final_sealing_signaling_ready"] is False


# --------------------------------------------------------------------- #
# Marker / envelope shape tests
# --------------------------------------------------------------------- #


def test_t12_marker_shape_contains_pinned_keys_and_parity_markers(emit_mod):
    """Marker dict carries the schema-v1 contract keys + welle_number=7
    + phase_3_final_sealing_tracking + the two Pre-Auditor-Final-
    Sealing-Signaling-Markers + Cross-Substrate-Parity-Markers list."""
    import datetime as _dt

    bundle = {
        "rollup": _canonical_welle_7_rollup(),
        "sign_off": _canonical_welle_7_sign_off(),
        "pre_auditor": _canonical_welle_7_pre_auditor(),
    }
    h = emit_mod.compute_welle_7_audit_anchor_hash(bundle)
    marker = emit_mod.build_welle_7_audit_anchor_marker(
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
        "phase_3_final_sealing_tracking",
        "pre_auditor_signaling_ready",
        "pre_auditor_final_sealing_signaling_ready",
        "wat_spool_envelope",
        "emitted_at_utc",
        "anchors",
        "operator_hand_next_step",
    }
    assert set(marker.keys()) == required, set(marker.keys()) ^ required
    assert marker["schema_version"] == 1
    assert marker["kind"] == "welle-7-audit-trail-anchor-marker"
    assert marker["mode"] == "welle-7-audit-anchor"
    assert marker["welle_number"] == 7
    assert marker["audit_trail_anchor"] == h
    # Tracking block surfaced correctly.
    tracking = marker["phase_3_final_sealing_tracking"]
    assert tracking["phase_3_final_sealing_active"] is True
    assert tracking["global_acceptance_verdict_recorded"] is True
    assert tracking["phase_3_complete_marker_ready"] is True
    # Wat-spool envelope.
    assert (
        marker["wat_spool_envelope"]["anchor_target"]
        == "opentimestamps-calendar"
    )
    assert (
        marker["wat_spool_envelope"]["kind"]
        == "welle-7-audit-trail-anchor-envelope"
    )
    # Final-sealing context anchor reference.
    assert (
        marker["anchors"]["welle_7_context"]
        == "phase-3-final-sealing-cutover-kw27"
    )
    assert marker["anchors"]["welle_7_cutover_date"] == "2026-07-01"
    assert marker["anchors"]["welle_7_sign_off_date"] == "2026-07-03"
    # Cross-coord anchors to Tag-69..Tag-74.
    assert marker["anchors"]["tomas_tag_69_welle_1_audit_anchor_pr"] == 439
    assert marker["anchors"]["tomas_tag_70_welle_2_audit_anchor_pr"] == 445
    assert marker["anchors"]["tomas_tag_71_welle_3_audit_anchor_pr"] == 450
    assert marker["anchors"]["tomas_tag_72_welle_4_audit_anchor_pr"] == 457
    assert marker["anchors"]["tomas_tag_73_welle_5_audit_anchor_pr"] == 464
    assert marker["anchors"]["tomas_tag_74_welle_6_audit_anchor_pr"] == 470
    # Final-sealing discipline anchor.
    assert (
        marker["anchors"]["phase_3_final_sealing_discipline"]
        == "tag-75-final-welle-global-acceptance-verdict-recording"
    )
    # Cross-Substrate-Parity-Markers list — Tag-75 final-welle pin.
    assert marker["anchors"]["cross_substrate_parity_markers"] == [
        "welle-1",
        "welle-2",
        "welle-3",
        "welle-4",
        "welle-5",
        "welle-6",
        "welle-7",
    ]


def test_t13_envelope_shape_contains_sandbox_boundary_flags(wire_mod):
    """Producer-envelope carries the explicit sandbox-boundary flags
    + the phase_3_final_sealing_tracking surface + the two pre-auditor
    signaling flags."""
    import datetime as _dt

    bundle = {
        "rollup": _canonical_welle_7_rollup(),
        "sign_off": _canonical_welle_7_sign_off(),
        "pre_auditor": _canonical_welle_7_pre_auditor(),
    }
    paths = {
        "rollup": "state/welle-7.json",
        "sign_off": "state/welle-7-sign-off.json",
        "pre_auditor": "state/welle-7-pre-auditor-decision.json",
    }
    tracking_stub = {
        "phase_3_final_sealing_active": True,
        "phase_3_final_sealing_status": "sealed",
        "phase_3_final_sealing_iso": "2026-07-03T15:00:00+00:00",
        "global_acceptance_verdict_recorded": True,
        "phase_3_complete_marker_ready": True,
        "phase_3_final_sealing_evidence_ref": "docs/y.md",
    }
    env = wire_mod.build_envelope(
        bundle=bundle,
        bundle_paths=paths,
        anchor_hash="f" * 64,
        actor="pytest",
        now_utc=_dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.timezone.utc),
        phase_3_final_sealing_tracking=tracking_stub,
        pre_auditor_signaling_ready=True,
        pre_auditor_final_sealing_signaling_ready=True,
    )
    assert env["kind"] == "welle-7-audit-trail-anchor-producer-envelope"
    assert env["schema_version"] == 1
    assert env["welle_number"] == 7
    assert env["sandbox_boundary"] == {
        "no_network_io": True,
        "no_ots_cli_subprocess": True,
        "stdlib_only": True,
    }
    # Tracking block round-trips.
    assert env["phase_3_final_sealing_tracking"] == tracking_stub
    # Pre-auditor signaling flags round-trip.
    assert env["pre_auditor_signaling_ready"] is True
    assert env["pre_auditor_final_sealing_signaling_ready"] is True
    # Cross-coord anchors.
    assert env["anchors"]["amara_tag_67_state_file_conventions_pr"] == 429
    assert env["anchors"]["tomas_tag_69_welle_1_audit_anchor_pr"] == 439
    assert env["anchors"]["tomas_tag_70_welle_2_audit_anchor_pr"] == 445
    assert env["anchors"]["tomas_tag_71_welle_3_audit_anchor_pr"] == 450
    assert env["anchors"]["tomas_tag_72_welle_4_audit_anchor_pr"] == 457
    assert env["anchors"]["tomas_tag_73_welle_5_audit_anchor_pr"] == 464
    assert env["anchors"]["tomas_tag_74_welle_6_audit_anchor_pr"] == 470
    assert (
        env["anchors"]["welle_7_context"]
        == "phase-3-final-sealing-cutover-kw27"
    )
    # Cross-Substrate-Parity-Markers list also on the envelope (full
    # Welle-1..7 lineage).
    assert env["anchors"]["cross_substrate_parity_markers"] == [
        "welle-1",
        "welle-2",
        "welle-3",
        "welle-4",
        "welle-5",
        "welle-6",
        "welle-7",
    ]


def test_t14_envelope_anchor_matches_amara_verifier_regex(
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
    assert env["welle_number"] == 7
    assert env["phase_3_final_sealing_tracking"][
        "phase_3_final_sealing_active"
    ] is True
    # Sign-off precedence for the global-acceptance-verdict-recorded
    # flag.
    assert (
        env["phase_3_final_sealing_tracking"][
            "global_acceptance_verdict_recorded"
        ]
        is True
    )
    # With the canonical bundle (pre-auditor present + verdict
    # recorded) BOTH signaling flags are True.
    assert env["pre_auditor_signaling_ready"] is True
    assert env["pre_auditor_final_sealing_signaling_ready"] is True


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


def test_t15_emit_cli_welle_7_mode_happy_path(tmp_path: Path):
    """End-to-end: emit_helper --mode welle-7-audit-anchor writes a
    marker file with a 64-hex anchor and the phase_3_final_sealing_
    tracking block surfaced."""
    paths = _write_bundle(tmp_path, include_optional=True)
    marker_out = tmp_path / "marker.json"

    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "welle-7-audit-anchor",
            "--welle-7-rollup",
            str(paths["rollup"]),
            "--welle-7-sign-off",
            str(paths["sign_off"]),
            "--welle-7-validation",
            str(paths["validation"]),
            "--welle-7-pre-auditor",
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
    assert marker["kind"] == "welle-7-audit-trail-anchor-marker"
    assert marker["welle_number"] == 7
    assert OTS_ANCHOR_RE.match(marker["audit_trail_anchor"])
    assert marker["bundle_keys"] == [
        "pre_auditor",
        "rollup",
        "sign_off",
        "validation",
    ]
    tracking = marker["phase_3_final_sealing_tracking"]
    assert tracking["phase_3_final_sealing_active"] is True
    assert tracking["phase_3_final_sealing_status"] in {
        "pending",
        "sealed",
        "escalated",
        "unknown",
    }
    assert tracking["global_acceptance_verdict_recorded"] is True
    assert tracking["phase_3_complete_marker_ready"] is True
    # The two final-sealing pre-auditor signaling flags are True for
    # the canonical bundle.
    assert marker["pre_auditor_signaling_ready"] is True
    assert marker["pre_auditor_final_sealing_signaling_ready"] is True


def test_t16_emit_cli_welle_7_missing_required_flag_exit_2(tmp_path: Path):
    """Omitting --welle-7-rollup must exit 2 with stderr help."""
    paths = _write_bundle(tmp_path, include_optional=False)
    marker_out = tmp_path / "marker.json"

    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "welle-7-audit-anchor",
            "--welle-7-sign-off",
            str(paths["sign_off"]),
            "--marker-out",
            str(marker_out),
        ]
    )
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert "welle-7-rollup" in (cp.stdout + cp.stderr)


def test_t17_wire_helper_cli_full_bundle(tmp_path: Path):
    """End-to-end: wire_helper with all four bundle parts produces
    envelope with bundle_keys including validation + pre_auditor
    and tracking block + final-sealing signaling flags surfaced."""
    paths = _write_bundle(tmp_path, include_optional=True)
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-7-rollup",
            str(paths["rollup"]),
            "--welle-7-sign-off",
            str(paths["sign_off"]),
            "--welle-7-validation",
            str(paths["validation"]),
            "--welle-7-pre-auditor",
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
    assert env["kind"] == "welle-7-audit-trail-anchor-producer-envelope"
    assert env["welle_number"] == 7
    assert env["bundle_keys"] == [
        "pre_auditor",
        "rollup",
        "sign_off",
        "validation",
    ]
    assert OTS_ANCHOR_RE.match(env["audit_trail_anchor"])
    assert env["actor"] == "pytest"
    assert env["emitted_at_utc"] == "2026-05-19T12:00:00+00:00"
    tracking = env["phase_3_final_sealing_tracking"]
    assert tracking["phase_3_final_sealing_active"] is True
    assert tracking["global_acceptance_verdict_recorded"] is True
    assert tracking["phase_3_complete_marker_ready"] is True
    assert env["pre_auditor_signaling_ready"] is True
    assert env["pre_auditor_final_sealing_signaling_ready"] is True


def test_t18_wire_helper_minimal_bundle_skips_missing_optionals(
    tmp_path: Path,
):
    """When validation + pre_auditor files are absent on disk, the
    envelope omits them from bundle_keys / bundle_paths AND
    the final-sealing tracking still surfaces from the rollup +
    sign-off. Pre-auditor-final-sealing-signaling MUST be False
    (no pre-auditor file present)."""
    paths = _write_bundle(tmp_path, include_optional=False)
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-7-rollup",
            str(paths["rollup"]),
            "--welle-7-sign-off",
            str(paths["sign_off"]),
            "--envelope-out",
            str(env_out),
        ]
    )
    assert cp.returncode == 0, cp.stderr
    env = json.loads(env_out.read_text(encoding="utf-8"))
    assert env["bundle_keys"] == ["rollup", "sign_off"]
    assert set(env["bundle_paths"].keys()) == {"rollup", "sign_off"}
    tracking = env["phase_3_final_sealing_tracking"]
    assert tracking["phase_3_final_sealing_active"] is True
    # Rollup status wins (rollup says pending).
    assert tracking["phase_3_final_sealing_status"] == "pending"
    # Sign-off precedence for the verdict flags.
    assert tracking["global_acceptance_verdict_recorded"] is True
    assert tracking["phase_3_complete_marker_ready"] is True
    # Pre-auditor absent -> both signaling flags False.
    assert env["pre_auditor_signaling_ready"] is False
    assert env["pre_auditor_final_sealing_signaling_ready"] is False


def test_t19_wire_helper_missing_rollup_file_exit_1(tmp_path: Path):
    """Pointing --welle-7-rollup at a non-existent path exits 1."""
    paths = _write_bundle(tmp_path, include_optional=False)
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-7-rollup",
            str(tmp_path / "does-not-exist.json"),
            "--welle-7-sign-off",
            str(paths["sign_off"]),
            "--envelope-out",
            str(env_out),
        ]
    )
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "welle-7-rollup" in (cp.stdout + cp.stderr)


def test_t20_wire_helper_malformed_json_exit_1(tmp_path: Path):
    """Malformed JSON in the rollup file surfaces an exit-1 error."""
    rollup = tmp_path / "welle-7.json"
    rollup.write_text("{not valid json", encoding="utf-8")
    sign_off = tmp_path / "welle-7-sign-off.json"
    sign_off.write_text(
        json.dumps(_canonical_welle_7_sign_off()), encoding="utf-8"
    )
    env_out = tmp_path / "envelope.json"

    cp = _run(
        [
            str(WIRE_HELPER),
            "--welle-7-rollup",
            str(rollup),
            "--welle-7-sign-off",
            str(sign_off),
            "--envelope-out",
            str(env_out),
        ]
    )
    assert cp.returncode == 1, cp.stdout + cp.stderr


# --------------------------------------------------------------------- #
# Cross-coord + sandbox-boundary invariants
# --------------------------------------------------------------------- #


def test_t21_wire_helper_stdlib_only():
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


def test_t22_emit_helper_welle_7_mode_no_network(monkeypatch, tmp_path: Path):
    """Confirm welle-7 mode does NOT touch the network. We monkeypatch
    ``socket.socket`` to raise; the mode must still succeed."""
    import socket as _socket

    real_socket = _socket.socket

    def _fail(*a, **kw):
        raise AssertionError(
            "sandbox-boundary violation: socket.socket called from "
            "welle-7-audit-anchor mode"
        )

    monkeypatch.setattr(_socket, "socket", _fail)

    paths = _write_bundle(tmp_path, include_optional=True)
    marker_out = tmp_path / "marker.json"

    emit_mod = _load_module("_emit_helper_tag75_no_net", EMIT_HELPER)
    rc = emit_mod.main(
        [
            "--mode",
            "welle-7-audit-anchor",
            "--welle-7-rollup",
            str(paths["rollup"]),
            "--welle-7-sign-off",
            str(paths["sign_off"]),
            "--welle-7-validation",
            str(paths["validation"]),
            "--welle-7-pre-auditor",
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


def test_t23_welle_1_2_3_4_5_6_7_kinds_disjoint(emit_mod):
    """Welle-1..7 marker/envelope kinds MUST be distinct strings so a
    downstream consumer can dispatch on ``kind`` unambiguously. This
    is the Tag-75 Welle-1..7-Kind-Disjointness-Pin (auftrag-mandatory,
    final-welle).
    """
    marker_kinds = {
        emit_mod.WELLE_1_KIND_MARKER,
        emit_mod.WELLE_2_KIND_MARKER,
        emit_mod.WELLE_3_KIND_MARKER,
        emit_mod.WELLE_4_KIND_MARKER,
        emit_mod.WELLE_5_KIND_MARKER,
        emit_mod.WELLE_6_KIND_MARKER,
        emit_mod.WELLE_7_KIND_MARKER,
    }
    envelope_kinds = {
        emit_mod.WELLE_1_KIND_ENVELOPE,
        emit_mod.WELLE_2_KIND_ENVELOPE,
        emit_mod.WELLE_3_KIND_ENVELOPE,
        emit_mod.WELLE_4_KIND_ENVELOPE,
        emit_mod.WELLE_5_KIND_ENVELOPE,
        emit_mod.WELLE_6_KIND_ENVELOPE,
        emit_mod.WELLE_7_KIND_ENVELOPE,
    }
    assert len(marker_kinds) == 7, marker_kinds
    assert len(envelope_kinds) == 7, envelope_kinds
    assert "welle-1" in emit_mod.WELLE_1_KIND_MARKER
    assert "welle-2" in emit_mod.WELLE_2_KIND_MARKER
    assert "welle-3" in emit_mod.WELLE_3_KIND_MARKER
    assert "welle-4" in emit_mod.WELLE_4_KIND_MARKER
    assert "welle-5" in emit_mod.WELLE_5_KIND_MARKER
    assert "welle-6" in emit_mod.WELLE_6_KIND_MARKER
    assert "welle-7" in emit_mod.WELLE_7_KIND_MARKER
    assert "welle-1" in emit_mod.WELLE_1_KIND_ENVELOPE
    assert "welle-2" in emit_mod.WELLE_2_KIND_ENVELOPE
    assert "welle-3" in emit_mod.WELLE_3_KIND_ENVELOPE
    assert "welle-4" in emit_mod.WELLE_4_KIND_ENVELOPE
    assert "welle-5" in emit_mod.WELLE_5_KIND_ENVELOPE
    assert "welle-6" in emit_mod.WELLE_6_KIND_ENVELOPE
    assert "welle-7" in emit_mod.WELLE_7_KIND_ENVELOPE


def test_t24_welle_7_mode_constant_present(emit_mod):
    """The Tag-75 mode constant is exposed at module level."""
    assert emit_mod.MODE_WELLE_7_AUDIT_ANCHOR == "welle-7-audit-anchor"
    # The Welle-7 ordering / required-key constants are also exposed
    # (Selin's producer imports them).
    assert emit_mod.WELLE_7_BUNDLE_ORDER == (
        "rollup",
        "sign_off",
        "validation",
        "pre_auditor",
    )
    assert emit_mod.WELLE_7_BUNDLE_REQUIRED == frozenset(
        {"rollup", "sign_off"}
    )
    # Status-enum surface is also exposed for downstream consumers
    # who want to validate before persisting.
    assert emit_mod.PHASE_3_FINAL_SEALING_STATUS_VALUES == frozenset(
        {"pending", "sealed", "escalated", "unknown"}
    )


def test_t25_emit_cli_welle_7_missing_marker_out_exit_2(tmp_path: Path):
    """Omitting --marker-out in welle-7-audit-anchor mode must exit 2."""
    paths = _write_bundle(tmp_path, include_optional=False)

    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "welle-7-audit-anchor",
            "--welle-7-rollup",
            str(paths["rollup"]),
            "--welle-7-sign-off",
            str(paths["sign_off"]),
        ]
    )
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert "--marker-out" in (cp.stdout + cp.stderr)


def test_t26_emit_cli_welle_7_sealing_inactive_when_absent(tmp_path: Path):
    """Bundle without the Final-Sealing fields surfaces
    sealing_active=False + status=unknown via the CLI happy path."""
    rollup = {"welle_number": 7, "status": "pending"}
    sign_off = {"welle_number": 7, "status": "signed-off"}
    rollup_path = tmp_path / "welle-7.json"
    sign_off_path = tmp_path / "welle-7-sign-off.json"
    rollup_path.write_text(json.dumps(rollup), encoding="utf-8")
    sign_off_path.write_text(json.dumps(sign_off), encoding="utf-8")
    marker_out = tmp_path / "marker.json"

    cp = _run(
        [
            str(EMIT_HELPER),
            "--mode",
            "welle-7-audit-anchor",
            "--welle-7-rollup",
            str(rollup_path),
            "--welle-7-sign-off",
            str(sign_off_path),
            "--marker-out",
            str(marker_out),
            "--now",
            "2026-05-19T12:00:00+00:00",
        ]
    )
    assert cp.returncode == 0, cp.stderr
    marker = json.loads(marker_out.read_text(encoding="utf-8"))
    tracking = marker["phase_3_final_sealing_tracking"]
    assert tracking["phase_3_final_sealing_active"] is False
    assert tracking["phase_3_final_sealing_status"] == "unknown"
    assert tracking["phase_3_final_sealing_iso"] == ""
    assert tracking["global_acceptance_verdict_recorded"] is False
    assert tracking["phase_3_complete_marker_ready"] is False
    assert tracking["phase_3_final_sealing_evidence_ref"] == ""
    # Both signaling flags False (no pre-auditor, no verdict).
    assert marker["pre_auditor_signaling_ready"] is False
    assert marker["pre_auditor_final_sealing_signaling_ready"] is False


def test_t27_marker_cross_substrate_parity_markers_list_pin(emit_mod):
    """The Tag-75 final-welle Cross-Substrate-Parity-Markers list MUST
    be the FULL Welle-1..7 sequence on the marker. This is the
    Welle-1..7-Kind-Disjointness-Pin (auftrag-mandatory).
    """
    import datetime as _dt

    bundle = {
        "rollup": _canonical_welle_7_rollup(),
        "sign_off": _canonical_welle_7_sign_off(),
    }
    h = emit_mod.compute_welle_7_audit_anchor_hash(bundle)
    marker = emit_mod.build_welle_7_audit_anchor_marker(
        bundle=bundle,
        anchor_hash=h,
        actor="pytest",
        now_utc=_dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.timezone.utc),
    )
    parity = marker["anchors"]["cross_substrate_parity_markers"]
    # Order matters (audit-trail-lineage left-to-right).
    assert parity == [
        "welle-1",
        "welle-2",
        "welle-3",
        "welle-4",
        "welle-5",
        "welle-6",
        "welle-7",
    ]
    # Length-pin: Welle-7 is the FINAL Welle of the Phase-3c-Welle-
    # Marathon, so the parity list is exactly seven entries.
    assert len(parity) == 7
