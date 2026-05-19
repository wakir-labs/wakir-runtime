#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-76 Phase-3-COMPLETE-marker Marathon-Closeout-Audit-Bundle tests.

Marathon-Closeout-Audit-Anchor-Bundle. Consolidates the seven
Welle-1..7 audit-anchor markers (outputs of the Tag-69..Tag-75
``wire_welle_*`` helpers / ``--mode welle-N-audit-anchor``) into a
single Phase-3-COMPLETE-marker that Henrik's Zone-N Audit-Evidence-
Index ingests as the canonical Phase-3-COMPLETE hand-off envelope.

Two tool-side surfaces under test:

  * ``tooling/ots/emit_manifest_hash_ots_marker.py
    --mode phase-3-complete-marker`` (Tomás Tag-76, this PR):
    consumes the seven welle-N audit-anchor markers, enforces the
    Welle-1..7-Kind-Disjointness-Pin at ingest, computes the bundle
    anchor, emits the Phase-3-COMPLETE marker.
  * ``tooling/ci/wire_phase_3_complete_audit_bundle.py`` (Tomás
    Tag-76, this PR): single-purpose helper that emits the
    producer-facing envelope Henrik's Zone-N consumer reads.

Coverage (>= 15 tests per Tag-76 auftrag, all-7-Welle-Cross-Anchor-
Validation):

  - load_phase_3_complete_bundle: count check, sort-by-welle-number
    invariance, malformed-JSON propagation.
  - assert_welle_1_7_kind_disjointness_pin: count, dict-type, welle-
    number coverage 1..7, duplicate detection, gap detection, kind-
    string match, anchor-hex shape.
  - compute_phase_3_complete_bundle_anchor: determinism + explicit
    recipe identity (sort + canonical-JSON concat + SHA-256), recipe
    identity with the per-Welle recipe.
  - build_phase_3_complete_marker: schema-v1 shape, bundle anchors
    list ordering, Phase-3-Final-Sealing-Tracking sourced from
    Welle-7, two Tag-75 signaling flag passthrough, Welle-1..7-Kind-
    Disjointness-Pin-OK.
  - CLI surface for both emit + wire helpers (smoke, error paths).
  - Wire-helper envelope shape conformance + path-mapping.
  - Cross-Substrate-Parity-Markers list surfaces full Welle-1..7.
  - Amara verifier-regex round-trip (``^$|^[0-9a-f]{64}$``).
  - Sandbox-boundary invariants (stdlib-only, no network).

Anchor: Tag-76 Marathon-Closeout-Audit-Anchor-Bundle.
Author: Tomás Reinhart (dev-engineering, Matrix-Lead, Zone-N hand-off).
"""

from __future__ import annotations

import datetime as _dt
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
WIRE_HELPER = (
    REPO_ROOT / "tooling" / "ci" / "wire_phase_3_complete_audit_bundle.py"
)

# Amara Tag-67 verifier regex: empty-string or 64-hex SHA-256.
OTS_ANCHOR_RE = re.compile(r"^$|^[0-9a-f]{64}$")

# Frozen ISO timestamp for deterministic envelope timestamps in tests.
FROZEN_NOW = _dt.datetime(2026, 7, 3, 15, 30, 0, tzinfo=_dt.timezone.utc)


def _load_module(name: str, path: Path):
    """Load a module from a file path without packaging machinery."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def emit_mod():
    return _load_module("_emit_helper_tag76", EMIT_HELPER)


@pytest.fixture(scope="module")
def wire_mod():
    return _load_module("_wire_helper_tag76", WIRE_HELPER)


# --------------------------------------------------------------------- #
# Canonical Welle-N marker fixtures
# --------------------------------------------------------------------- #


def _make_welle_marker(welle_number: int, *, anchor_suffix: str = "") -> dict:
    """Synthesise a canonical Welle-N audit-anchor marker.

    Carries the minimum fields required by the Phase-3-COMPLETE-marker
    ingest (welle_number, kind, audit_trail_anchor) plus the Welle-7-
    specific Phase-3-Final-Sealing-Tracking surface fields when
    ``welle_number == 7`` so the closeout marker can source the
    tracking block from there.
    """
    # Deterministic 64-hex hash per welle_number.
    base = f"welle-{welle_number}-anchor{anchor_suffix}"
    anchor = hashlib.sha256(base.encode("utf-8")).hexdigest()
    marker: dict = {
        "schema_version": 1,
        "kind": f"welle-{welle_number}-audit-trail-anchor-marker",
        "mode": f"welle-{welle_number}-audit-anchor",
        "welle_number": welle_number,
        "audit_trail_anchor": anchor,
        "bundle_keys": ["rollup", "sign_off"],
        "emitted_at_utc": FROZEN_NOW.isoformat(),
    }
    if welle_number == 7:
        marker["phase_3_final_sealing_tracking"] = {
            "phase_3_final_sealing_active": True,
            "phase_3_final_sealing_status": "sealed",
            "phase_3_final_sealing_iso": "2026-07-03T15:00:00+00:00",
            "global_acceptance_verdict_recorded": True,
            "phase_3_complete_marker_ready": True,
            "phase_3_final_sealing_evidence_ref": (
                "docs/operations/phase-3-final-sealing-runbook.md"
            ),
        }
        marker["pre_auditor_signaling_ready"] = True
        marker["pre_auditor_final_sealing_signaling_ready"] = True
    return marker


def _write_seven_markers(
    tmp_path: Path, *, mutate: dict | None = None
) -> list[Path]:
    """Write seven canonical markers to disk and return their paths.

    ``mutate`` is an optional ``{welle_number: dict-of-overrides}``
    mapping for per-test customisation. The marker for
    ``welle_number`` will be dict-merged with the override.
    """
    paths: list[Path] = []
    mutate = mutate or {}
    for n in (1, 2, 3, 4, 5, 6, 7):
        marker = _make_welle_marker(n)
        if n in mutate:
            marker.update(mutate[n])
        path = tmp_path / f"welle-{n}-audit-anchor.json"
        path.write_text(
            json.dumps(marker, sort_keys=True), encoding="utf-8"
        )
        paths.append(path)
    return paths


# --------------------------------------------------------------------- #
# load_phase_3_complete_bundle tests
# --------------------------------------------------------------------- #


def test_t01_load_bundle_count_mismatch_raises(emit_mod, tmp_path):
    """Loader rejects bundle with != 7 markers."""
    paths = _write_seven_markers(tmp_path)[:6]
    with pytest.raises(
        ValueError, match="expects 7 welle markers, got 6"
    ):
        emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)


def test_t02_load_bundle_sort_invariance(emit_mod, tmp_path):
    """Loader sorts markers by welle_number regardless of input order."""
    paths = _write_seven_markers(tmp_path)
    # Pass in reverse order (welle-7 first).
    reversed_paths = list(reversed(paths))
    markers = emit_mod.load_phase_3_complete_bundle(
        welle_marker_paths=reversed_paths
    )
    welle_numbers = [m["welle_number"] for m in markers]
    assert welle_numbers == [1, 2, 3, 4, 5, 6, 7]


def test_t03_load_bundle_malformed_json_propagates(emit_mod, tmp_path):
    """Malformed JSON in a marker file propagates as JSONDecodeError."""
    paths = _write_seven_markers(tmp_path)
    paths[3].write_text("not-json{{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)


# --------------------------------------------------------------------- #
# assert_welle_1_7_kind_disjointness_pin tests
# --------------------------------------------------------------------- #


def test_t04_disjointness_pin_happy_path(emit_mod, tmp_path):
    """Seven canonical markers pass the disjointness-pin assertion."""
    paths = _write_seven_markers(tmp_path)
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    # Must not raise.
    emit_mod.assert_welle_1_7_kind_disjointness_pin(markers)


def test_t05_disjointness_pin_rejects_duplicate_welle_number(
    emit_mod, tmp_path
):
    """Duplicate welle_number triggers the disjointness violation."""
    paths = _write_seven_markers(tmp_path)
    # Overwrite welle-2 marker with a marker carrying welle_number=1.
    duplicate = _make_welle_marker(1, anchor_suffix="-dup")
    paths[1].write_text(
        json.dumps(duplicate, sort_keys=True), encoding="utf-8"
    )
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    with pytest.raises(
        ValueError, match="welle_number=1"
    ):
        emit_mod.assert_welle_1_7_kind_disjointness_pin(markers)


def test_t06_disjointness_pin_rejects_gap_in_welle_numbers(
    emit_mod, tmp_path
):
    """Gap in welle_numbers (e.g. missing 5) triggers the violation."""
    paths = _write_seven_markers(tmp_path)
    # Overwrite welle-5 with a marker carrying welle_number=8 (gap).
    gap_marker = _make_welle_marker(8, anchor_suffix="-gap")
    paths[4].write_text(
        json.dumps(gap_marker, sort_keys=True), encoding="utf-8"
    )
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    with pytest.raises(
        ValueError, match="expected 5"
    ):
        emit_mod.assert_welle_1_7_kind_disjointness_pin(markers)


def test_t07_disjointness_pin_rejects_wrong_kind_string(emit_mod, tmp_path):
    """Mismatched ``kind`` string triggers the disjointness violation."""
    paths = _write_seven_markers(tmp_path)
    bad_marker = _make_welle_marker(3)
    bad_marker["kind"] = "welle-3-foreign-kind"
    paths[2].write_text(
        json.dumps(bad_marker, sort_keys=True), encoding="utf-8"
    )
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    with pytest.raises(
        ValueError, match="Welle-1..7-Kind-Disjointness-Pin violated"
    ):
        emit_mod.assert_welle_1_7_kind_disjointness_pin(markers)


def test_t08_disjointness_pin_rejects_non_hex_anchor(emit_mod, tmp_path):
    """Invalid audit_trail_anchor (non-hex / wrong length) triggers."""
    paths = _write_seven_markers(tmp_path)
    bad_marker = _make_welle_marker(4)
    bad_marker["audit_trail_anchor"] = "deadbeef"  # length 8, not 64
    paths[3].write_text(
        json.dumps(bad_marker, sort_keys=True), encoding="utf-8"
    )
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    with pytest.raises(
        ValueError, match="invalid audit_trail_anchor"
    ):
        emit_mod.assert_welle_1_7_kind_disjointness_pin(markers)


# --------------------------------------------------------------------- #
# compute_phase_3_complete_bundle_anchor tests
# --------------------------------------------------------------------- #


def test_t09_bundle_anchor_deterministic_and_64hex(emit_mod, tmp_path):
    """Bundle anchor is deterministic + matches the OTS verifier regex."""
    paths = _write_seven_markers(tmp_path)
    markers_1 = emit_mod.load_phase_3_complete_bundle(
        welle_marker_paths=paths
    )
    markers_2 = emit_mod.load_phase_3_complete_bundle(
        welle_marker_paths=list(reversed(paths))
    )
    h1 = emit_mod.compute_phase_3_complete_bundle_anchor(markers_1)
    h2 = emit_mod.compute_phase_3_complete_bundle_anchor(markers_2)
    assert h1 == h2
    assert OTS_ANCHOR_RE.match(h1), h1
    assert len(h1) == 64


def test_t10_bundle_anchor_explicit_recipe(emit_mod, tmp_path):
    """Bundle anchor recipe: sort + canonical-JSON concat + SHA-256.

    Spell out the recipe in the test so an accidental drift in the
    closeout-bundle hash construction surfaces here.
    """
    paths = _write_seven_markers(tmp_path)
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    expected = hashlib.sha256(
        b"\n".join(
            emit_mod._canonical_json_bytes(m) for m in markers
        )
    ).hexdigest()
    assert emit_mod.compute_phase_3_complete_bundle_anchor(markers) == expected


def test_t11_bundle_anchor_changes_when_any_input_marker_changes(
    emit_mod, tmp_path
):
    """Mutating any single Welle marker MUST change the bundle anchor."""
    paths_a = _write_seven_markers(tmp_path)
    markers_a = emit_mod.load_phase_3_complete_bundle(
        welle_marker_paths=paths_a
    )
    h_a = emit_mod.compute_phase_3_complete_bundle_anchor(markers_a)

    tmp_b = tmp_path / "variant-b"
    tmp_b.mkdir()
    paths_b = _write_seven_markers(
        tmp_b,
        mutate={5: {"audit_trail_anchor": "f" * 64}},
    )
    markers_b = emit_mod.load_phase_3_complete_bundle(
        welle_marker_paths=paths_b
    )
    h_b = emit_mod.compute_phase_3_complete_bundle_anchor(markers_b)

    assert h_a != h_b


# --------------------------------------------------------------------- #
# build_phase_3_complete_marker tests
# --------------------------------------------------------------------- #


def test_t12_marker_shape_contains_pinned_keys(emit_mod, tmp_path):
    """Phase-3-COMPLETE marker carries the schema-v1 contract keys."""
    paths = _write_seven_markers(tmp_path)
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    emit_mod.assert_welle_1_7_kind_disjointness_pin(markers)
    bundle_anchor = emit_mod.compute_phase_3_complete_bundle_anchor(markers)
    marker = emit_mod.build_phase_3_complete_marker(
        markers=markers,
        bundle_anchor=bundle_anchor,
        actor="pytest",
        now_utc=FROZEN_NOW,
    )
    for key in (
        "schema_version",
        "kind",
        "mode",
        "phase_3_complete_bundle_anchor",
        "welle_bundle_count",
        "welle_bundle_anchors",
        "phase_3_final_sealing_tracking",
        "global_acceptance_verdict_recorded",
        "phase_3_complete_marker_ready",
        "pre_auditor_final_sealing_signaling_ready",
        "welle_1_7_kind_disjointness_pin_ok",
        "wat_spool_envelope",
        "emitted_at_utc",
        "anchors",
        "operator_hand_next_step",
    ):
        assert key in marker, f"missing key: {key}"

    assert marker["kind"] == "phase-3-complete-marker"
    assert marker["mode"] == "phase-3-complete-marker"
    assert marker["welle_bundle_count"] == 7
    assert marker["welle_1_7_kind_disjointness_pin_ok"] is True
    assert marker["phase_3_complete_bundle_anchor"] == bundle_anchor


def test_t13_marker_welle_bundle_anchors_ordering_and_content(
    emit_mod, tmp_path
):
    """``welle_bundle_anchors`` lists the seven welle anchors in
    welle-number order (sort by welle_number ascending) with the
    expected kind strings."""
    paths = _write_seven_markers(tmp_path)
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    bundle_anchor = emit_mod.compute_phase_3_complete_bundle_anchor(markers)
    marker = emit_mod.build_phase_3_complete_marker(
        markers=markers,
        bundle_anchor=bundle_anchor,
        actor="pytest",
        now_utc=FROZEN_NOW,
    )
    bundle_anchors = marker["welle_bundle_anchors"]
    assert len(bundle_anchors) == 7
    for idx, entry in enumerate(bundle_anchors, start=1):
        assert entry["welle_number"] == idx
        assert entry["kind"] == f"welle-{idx}-audit-trail-anchor-marker"
        assert OTS_ANCHOR_RE.match(entry["audit_trail_anchor"])


def test_t14_marker_sourcing_phase_3_tracking_from_welle_7(
    emit_mod, tmp_path
):
    """``phase_3_final_sealing_tracking`` is sourced from the Welle-7
    marker (markers[-1] after sort). The two Tag-75 signaling flags
    pass through unchanged."""
    paths = _write_seven_markers(tmp_path)
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    bundle_anchor = emit_mod.compute_phase_3_complete_bundle_anchor(markers)
    marker = emit_mod.build_phase_3_complete_marker(
        markers=markers,
        bundle_anchor=bundle_anchor,
        actor="pytest",
        now_utc=FROZEN_NOW,
    )
    tracking = marker["phase_3_final_sealing_tracking"]
    assert tracking["phase_3_final_sealing_active"] is True
    assert tracking["phase_3_final_sealing_status"] == "sealed"
    assert (
        tracking["phase_3_final_sealing_iso"]
        == "2026-07-03T15:00:00+00:00"
    )
    assert tracking["global_acceptance_verdict_recorded"] is True
    assert tracking["phase_3_complete_marker_ready"] is True
    # Top-level summary mirrors.
    assert marker["global_acceptance_verdict_recorded"] is True
    assert marker["phase_3_complete_marker_ready"] is True
    assert marker["pre_auditor_final_sealing_signaling_ready"] is True


def test_t15_marker_summary_inactive_when_welle_7_not_sealed(
    emit_mod, tmp_path
):
    """When Welle-7 marker has no tracking block / verdict-recorded
    is False, the closeout marker surfaces inactive defaults."""
    paths = _write_seven_markers(
        tmp_path,
        mutate={
            7: {
                "phase_3_final_sealing_tracking": {
                    "phase_3_final_sealing_active": False,
                    "phase_3_final_sealing_status": "pending",
                    "phase_3_final_sealing_iso": "",
                    "global_acceptance_verdict_recorded": False,
                    "phase_3_complete_marker_ready": False,
                    "phase_3_final_sealing_evidence_ref": "",
                },
                "pre_auditor_final_sealing_signaling_ready": False,
            }
        },
    )
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    bundle_anchor = emit_mod.compute_phase_3_complete_bundle_anchor(markers)
    marker = emit_mod.build_phase_3_complete_marker(
        markers=markers,
        bundle_anchor=bundle_anchor,
        actor="pytest",
        now_utc=FROZEN_NOW,
    )
    assert marker["global_acceptance_verdict_recorded"] is False
    assert marker["phase_3_complete_marker_ready"] is False
    assert marker["pre_auditor_final_sealing_signaling_ready"] is False


def test_t16_marker_anchors_carry_cross_substrate_parity_markers(
    emit_mod, tmp_path
):
    """``anchors.cross_substrate_parity_markers`` lists all seven Welle
    slugs, and the Tag-69..75 PR refs are pinned numbers (not None)
    while the Tag-76 PR ref remains None until merged."""
    paths = _write_seven_markers(tmp_path)
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    bundle_anchor = emit_mod.compute_phase_3_complete_bundle_anchor(markers)
    marker = emit_mod.build_phase_3_complete_marker(
        markers=markers,
        bundle_anchor=bundle_anchor,
        actor="pytest",
        now_utc=FROZEN_NOW,
    )
    anchors = marker["anchors"]
    assert anchors["cross_substrate_parity_markers"] == [
        "welle-1",
        "welle-2",
        "welle-3",
        "welle-4",
        "welle-5",
        "welle-6",
        "welle-7",
    ]
    for pr_key in (
        "tomas_tag_69_welle_1_audit_anchor_pr",
        "tomas_tag_70_welle_2_audit_anchor_pr",
        "tomas_tag_71_welle_3_audit_anchor_pr",
        "tomas_tag_72_welle_4_audit_anchor_pr",
        "tomas_tag_73_welle_5_audit_anchor_pr",
        "tomas_tag_74_welle_6_audit_anchor_pr",
        "tomas_tag_75_welle_7_audit_anchor_pr",
    ):
        assert isinstance(anchors[pr_key], int) and anchors[pr_key] > 0


# --------------------------------------------------------------------- #
# CLI surface tests (emit helper, --mode phase-3-complete-marker)
# --------------------------------------------------------------------- #


def test_t17_cli_emit_phase_3_complete_smoke(emit_mod, tmp_path):
    """CLI smoke: emit_manifest_hash_ots_marker.py --mode phase-3-
    complete-marker writes a valid marker JSON."""
    paths = _write_seven_markers(tmp_path)
    out = tmp_path / "phase-3-complete-marker.json"
    argv = [
        "--mode",
        "phase-3-complete-marker",
        "--welle-1-marker",
        str(paths[0]),
        "--welle-2-marker",
        str(paths[1]),
        "--welle-3-marker",
        str(paths[2]),
        "--welle-4-marker",
        str(paths[3]),
        "--welle-5-marker",
        str(paths[4]),
        "--welle-6-marker",
        str(paths[5]),
        "--welle-7-marker",
        str(paths[6]),
        "--marker-out",
        str(out),
        "--actor",
        "pytest",
        "--now",
        FROZEN_NOW.isoformat(),
    ]
    rc = emit_mod.main(argv)
    assert rc == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["kind"] == "phase-3-complete-marker"
    assert doc["welle_bundle_count"] == 7
    assert OTS_ANCHOR_RE.match(doc["phase_3_complete_bundle_anchor"])


def test_t18_cli_emit_missing_welle_marker_arg_returns_2(emit_mod, tmp_path):
    """Missing one of the --welle-N-marker args returns usage-error rc=2."""
    paths = _write_seven_markers(tmp_path)
    out = tmp_path / "phase-3-complete-marker.json"
    # Drop --welle-4-marker.
    argv = [
        "--mode",
        "phase-3-complete-marker",
        "--welle-1-marker",
        str(paths[0]),
        "--welle-2-marker",
        str(paths[1]),
        "--welle-3-marker",
        str(paths[2]),
        # missing --welle-4-marker
        "--welle-5-marker",
        str(paths[4]),
        "--welle-6-marker",
        str(paths[5]),
        "--welle-7-marker",
        str(paths[6]),
        "--marker-out",
        str(out),
    ]
    rc = emit_mod.main(argv)
    assert rc == 2


def test_t19_cli_emit_missing_file_returns_1(emit_mod, tmp_path):
    """Existing welle marker arg pointing to missing file returns rc=1."""
    paths = _write_seven_markers(tmp_path)
    out = tmp_path / "phase-3-complete-marker.json"
    missing = tmp_path / "does-not-exist.json"
    argv = [
        "--mode",
        "phase-3-complete-marker",
        "--welle-1-marker",
        str(paths[0]),
        "--welle-2-marker",
        str(paths[1]),
        "--welle-3-marker",
        str(paths[2]),
        "--welle-4-marker",
        str(missing),
        "--welle-5-marker",
        str(paths[4]),
        "--welle-6-marker",
        str(paths[5]),
        "--welle-7-marker",
        str(paths[6]),
        "--marker-out",
        str(out),
    ]
    rc = emit_mod.main(argv)
    assert rc == 1


def test_t20_cli_emit_disjointness_violation_returns_1(emit_mod, tmp_path):
    """Disjointness-pin violation surfaces as rc=1 from the CLI."""
    paths = _write_seven_markers(tmp_path)
    # Corrupt welle-2 by giving it welle_number=1 (duplicate).
    duplicate = _make_welle_marker(1, anchor_suffix="-dup")
    paths[1].write_text(
        json.dumps(duplicate, sort_keys=True), encoding="utf-8"
    )
    out = tmp_path / "phase-3-complete-marker.json"
    argv = [
        "--mode",
        "phase-3-complete-marker",
        "--welle-1-marker",
        str(paths[0]),
        "--welle-2-marker",
        str(paths[1]),
        "--welle-3-marker",
        str(paths[2]),
        "--welle-4-marker",
        str(paths[3]),
        "--welle-5-marker",
        str(paths[4]),
        "--welle-6-marker",
        str(paths[5]),
        "--welle-7-marker",
        str(paths[6]),
        "--marker-out",
        str(out),
    ]
    rc = emit_mod.main(argv)
    assert rc == 1
    # Marker MUST NOT have been written.
    assert not out.exists()


# --------------------------------------------------------------------- #
# Wire-helper tests
# --------------------------------------------------------------------- #


def test_t21_wire_helper_emit_envelope_shape(wire_mod, tmp_path):
    """Wire-helper emit_envelope returns a producer-facing envelope
    with the contract keys + welle_marker_paths mapping."""
    paths = _write_seven_markers(tmp_path)
    envelope = wire_mod.emit_envelope(
        welle_marker_paths=paths,
        actor="pytest",
        now_utc=FROZEN_NOW,
    )
    assert envelope["kind"] == "phase-3-complete-marker-producer-envelope"
    assert envelope["welle_bundle_count"] == 7
    assert envelope["welle_1_7_kind_disjointness_pin_ok"] is True
    assert envelope["sandbox_boundary"]["stdlib_only"] is True
    assert envelope["sandbox_boundary"]["no_network_io"] is True
    assert envelope["sandbox_boundary"]["no_ots_cli_subprocess"] is True
    # Path mapping reflects each Welle's source file.
    for n in (1, 2, 3, 4, 5, 6, 7):
        assert envelope["welle_marker_paths"][f"welle-{n}"] == str(
            paths[n - 1]
        )


def test_t22_wire_helper_envelope_anchor_matches_emit_module(
    wire_mod, emit_mod, tmp_path
):
    """Wire-helper bundle anchor == emit-module compute function output.

    Ensures the two surfaces (CLI ``--mode phase-3-complete-marker``
    and the wire-helper) always agree on the bundle hash recipe.
    """
    paths = _write_seven_markers(tmp_path)
    envelope = wire_mod.emit_envelope(
        welle_marker_paths=paths,
        actor="pytest",
        now_utc=FROZEN_NOW,
    )
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    expected = emit_mod.compute_phase_3_complete_bundle_anchor(markers)
    assert envelope["phase_3_complete_bundle_anchor"] == expected


def test_t23_wire_helper_cli_smoke_subprocess(tmp_path):
    """End-to-end subprocess invocation of the wire helper CLI."""
    paths = _write_seven_markers(tmp_path)
    out = tmp_path / "phase-3-complete-envelope.json"
    cmd = [
        sys.executable,
        str(WIRE_HELPER),
        "--welle-1-marker",
        str(paths[0]),
        "--welle-2-marker",
        str(paths[1]),
        "--welle-3-marker",
        str(paths[2]),
        "--welle-4-marker",
        str(paths[3]),
        "--welle-5-marker",
        str(paths[4]),
        "--welle-6-marker",
        str(paths[5]),
        "--welle-7-marker",
        str(paths[6]),
        "--envelope-out",
        str(out),
        "--actor",
        "pytest",
        "--now",
        FROZEN_NOW.isoformat(),
    ]
    res = subprocess.run(
        cmd, check=False, capture_output=True, text=True
    )
    assert res.returncode == 0, res.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["kind"] == "phase-3-complete-marker-producer-envelope"
    assert doc["welle_bundle_count"] == 7
    assert OTS_ANCHOR_RE.match(doc["phase_3_complete_bundle_anchor"])


def test_t24_wire_helper_cli_missing_marker_returns_1(tmp_path):
    """CLI returns rc=1 when a referenced marker file does not exist."""
    paths = _write_seven_markers(tmp_path)
    missing = tmp_path / "missing.json"
    out = tmp_path / "phase-3-complete-envelope.json"
    cmd = [
        sys.executable,
        str(WIRE_HELPER),
        "--welle-1-marker",
        str(paths[0]),
        "--welle-2-marker",
        str(missing),
        "--welle-3-marker",
        str(paths[2]),
        "--welle-4-marker",
        str(paths[3]),
        "--welle-5-marker",
        str(paths[4]),
        "--welle-6-marker",
        str(paths[5]),
        "--welle-7-marker",
        str(paths[6]),
        "--envelope-out",
        str(out),
    ]
    res = subprocess.run(
        cmd, check=False, capture_output=True, text=True
    )
    assert res.returncode == 1
    assert not out.exists()


# --------------------------------------------------------------------- #
# All-7-Welle-Cross-Anchor-Validation
# --------------------------------------------------------------------- #


def test_t25_cross_anchor_validation_all_seven_anchors_distinct(
    emit_mod, tmp_path
):
    """The seven Welle audit_trail_anchors are independently distinct
    (no two Welle anchors collide by construction)."""
    paths = _write_seven_markers(tmp_path)
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    anchors = [m["audit_trail_anchor"] for m in markers]
    assert len(anchors) == 7
    assert len(set(anchors)) == 7


def test_t26_cross_anchor_validation_bundle_anchor_changes_per_welle(
    emit_mod, tmp_path
):
    """Mutating EACH of the seven Welle markers in isolation changes
    the bundle anchor -- proves the bundle hash genuinely depends on
    ALL seven inputs (no silent dependence on a subset).
    """
    base_paths = _write_seven_markers(tmp_path)
    base_markers = emit_mod.load_phase_3_complete_bundle(
        welle_marker_paths=base_paths
    )
    base_anchor = emit_mod.compute_phase_3_complete_bundle_anchor(
        base_markers
    )

    for welle in range(1, 8):
        variant_dir = tmp_path / f"variant-welle-{welle}"
        variant_dir.mkdir()
        # Mutate ONLY the welle-`welle` marker.
        mutated = _make_welle_marker(welle, anchor_suffix=f"-mut-{welle}")
        variant_paths: list[Path] = []
        for n in (1, 2, 3, 4, 5, 6, 7):
            target = variant_dir / f"welle-{n}-audit-anchor.json"
            if n == welle:
                target.write_text(
                    json.dumps(mutated, sort_keys=True),
                    encoding="utf-8",
                )
            else:
                # Reuse the canonical marker for this welle.
                target.write_text(
                    base_paths[n - 1].read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            variant_paths.append(target)
        variant_markers = emit_mod.load_phase_3_complete_bundle(
            welle_marker_paths=variant_paths
        )
        variant_anchor = emit_mod.compute_phase_3_complete_bundle_anchor(
            variant_markers
        )
        assert variant_anchor != base_anchor, (
            f"bundle anchor unchanged when welle-{welle} marker "
            f"mutated -- bundle hash does not depend on welle-{welle}"
        )


def test_t27_cross_anchor_kind_string_disjointness_seven_distinct(
    emit_mod, tmp_path
):
    """The seven expected kind strings are pairwise distinct -- the
    Welle-1..7-Kind-Disjointness-Pin invariant verified directly on
    the module constant."""
    kinds = list(emit_mod.PHASE_3_COMPLETE_EXPECTED_KINDS)
    assert len(kinds) == 7
    assert len(set(kinds)) == 7
    for n, k in enumerate(kinds, start=1):
        assert k == f"welle-{n}-audit-trail-anchor-marker"


# --------------------------------------------------------------------- #
# Hash recipe identity with per-Welle recipe + sandbox-boundary
# --------------------------------------------------------------------- #


def test_t28_bundle_hash_recipe_identical_to_welle_recipe_shape(
    emit_mod, tmp_path
):
    """The closeout-bundle recipe is the per-Welle recipe applied to
    the welle markers as the bundle: canonical-JSON of each marker,
    concatenated with single newline separators, SHA-256 over concat.

    Pinned via the explicit equality in test_t10, but reaffirmed here
    against the Welle-1 helper to prove cross-substrate-parity: the
    same recipe applied to a {rollup, sign_off} bundle (Welle-1) and
    to the seven-marker bundle (Phase-3-COMPLETE) is the SAME function
    shape.
    """
    paths = _write_seven_markers(tmp_path)
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)

    # Closeout-bundle hash via the module helper.
    bundle_anchor = emit_mod.compute_phase_3_complete_bundle_anchor(markers)

    # Reimplement the recipe locally and assert equality.
    local = hashlib.sha256(
        b"\n".join(emit_mod._canonical_json_bytes(m) for m in markers)
    ).hexdigest()
    assert bundle_anchor == local

    # And the per-Welle recipe shape: SHA-256 over canonical-JSON
    # bundle parts concat'd with single newline separators. Apply it
    # to a Welle-1 bundle and prove the bytes-in/bytes-out behaviour
    # matches.
    welle_1_bundle = {
        "rollup": {"welle_number": 1, "stub": True},
        "sign_off": {"welle_number": 1, "status": "stub"},
    }
    welle_1_hash = emit_mod.compute_welle_1_audit_anchor_hash(welle_1_bundle)
    welle_1_recipe = hashlib.sha256(
        b"\n".join(
            emit_mod._canonical_json_bytes(welle_1_bundle[k])
            for k in ("rollup", "sign_off")
        )
    ).hexdigest()
    assert welle_1_hash == welle_1_recipe


def test_t29_sandbox_boundary_no_network_no_subprocess(wire_mod, tmp_path):
    """Wire-helper envelope explicitly pins sandbox-boundary invariants.

    Hermetic audit-only: no network, no OTS calendar call, stdlib-only.
    Test reads the envelope and asserts the sandbox boundary block
    surfaces the three invariants as ``True``.
    """
    paths = _write_seven_markers(tmp_path)
    envelope = wire_mod.emit_envelope(
        welle_marker_paths=paths,
        actor="pytest",
        now_utc=FROZEN_NOW,
    )
    sb = envelope["sandbox_boundary"]
    assert sb == {
        "no_network_io": True,
        "no_ots_cli_subprocess": True,
        "stdlib_only": True,
    }


def test_t30_wat_spool_envelope_carries_bundle_anchor(emit_mod, tmp_path):
    """The marker's ``wat_spool_envelope`` carries the bundle anchor
    + the canonical OTS calendar anchor target (mirror of the per-
    Welle marker envelopes)."""
    paths = _write_seven_markers(tmp_path)
    markers = emit_mod.load_phase_3_complete_bundle(welle_marker_paths=paths)
    bundle_anchor = emit_mod.compute_phase_3_complete_bundle_anchor(markers)
    marker = emit_mod.build_phase_3_complete_marker(
        markers=markers,
        bundle_anchor=bundle_anchor,
        actor="pytest",
        now_utc=FROZEN_NOW,
    )
    spool = marker["wat_spool_envelope"]
    assert spool["schema_version"] == 1
    assert spool["kind"] == "phase-3-complete-marker-envelope"
    assert spool["phase_3_complete_bundle_anchor"] == bundle_anchor
    assert spool["anchor_target"] == emit_mod.ANCHOR_TARGET_OTS_CALENDAR
    assert spool["actor"] == "pytest"
