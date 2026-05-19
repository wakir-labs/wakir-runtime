# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-71 tests for the RES-D4 HD-2 Peer-Roster
Substrate-Preparation artifacts.
=========================================================================

Two-axis coverage (parallel to Tag-70 §6.2 test-suite structure):

  Axis A -- Stub-file shape invariants over the live Tag-71 stub
            ``tooling/audit/res-d4-hd2-peer-roster-stub.json``
            (skip-if-absent for portability).
  Axis B -- Helper smoke-tests via subprocess against
            ``tooling/audit/prepare_res_d4_hd2_peer_roster_substrate.py``,
            including hermetic mutilated-stub variants in
            ``tmp_path`` for negative-control coverage.

Test inventory (>=12 hermetic, all stdlib + pytest):

  T01  Stub-file exists at the expected path.
  T02  Stub-file is well-formed JSON.
  T03  Stub-file declares ``audit_only: true`` and
       ``doc_form_only: true``.
  T04  Stub-file declares ``tag: Tag-71`` and ``hard_dep: HD-2``.
  T05  Stub-file enumerates exactly three fixture-peers and each
       carries ``kind: fixture`` and contributes 0 to production
       count.
  T06  Stub-file's third fixture-peer is the loose-count-forbidden
       negative-control with ``expected_verifier_branch: reject``.
  T07  Stub-file enumerates exactly three fixture-frames covering
       the three roster-states defined in the deep-dive §6.3
       catalogue.
  T08  Stub-file's third fixture-frame is the
       roster-snapshot-frame--loose-count-forbidden negative-control
       with ``expected_verifier_branch: reject``.
  T09  Stub-file's strict-interpretation invariant explicitly
       enumerates the three production-excludes categories and
       cites the Tag-67 §5.1 B2 failure-mode.
  T10  Stub-file enumerates exactly three roster-mutation events
       (peer-added, peer-removed, kind-promoted) and all default
       to not-emitted-in-audit-only.
  T11  Stub-file's sandbox-boundary section sets every boundary to
       its audit-only default (no production peer-count claim, no
       Selin direction emit, no CFO ratification envelope emit, no
       kind-field default change).
  T12  Stub-file's ``what_this_stub_is_not`` section explicitly
       negates production peer-count claim, draft-ADR, promotion-
       PR, Selin direction, CFO ratification, indefinite-deferral-
       lifting, and AR-authorisation request.
  T13  Deep-dive doc references the stub-file path and the helper
       path under §6.3 with the Tag-71 marker.
  T14  Helper subprocess exits 0 on the live stub-file.
  T15  Helper subprocess exits non-zero when ``audit_only`` is
       flipped to ``false`` (mutilated stub).
  T16  Helper subprocess exits non-zero when the loose-count-
       forbidden fixture-peer is removed.
  T17  Helper subprocess exits non-zero when the loose-count-
       forbidden fixture-frame is removed.
  T18  Helper subprocess exits non-zero when the
       ``kind-promoted`` roster-mutation event is dropped.
  T19  Sandbox-boundary invariant: the stub MUST NOT enumerate any
       production-claim URL or production-active peer-id (no
       claims about real federation peers).
  T20  Reuse-discipline invariant: every fixture-peer and every
       fixture-frame declares ``tag_60_compat: true`` (Tag-71
       reuses Tag-60 base shape).
  T21  Cross-anchor invariant: stub upstream_anchors references
       Tag-67 + Tag-65 + Tag-69 deep-dive + Tag-70 HD-1 PR #446 +
       Tag-69 PR #440 + Tag-60 PR #382.
  T22  Strict-interpretation pinpoint: helper rejects a mutilated
       stub where ``minimum_two_peers`` is loosened from ``>= 2``.
  T23  Production-count contribution invariant: every fixture-peer
       contributes exactly 0 to the production count (audit-only
       pin).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
STUB_REL = "tooling/audit/res-d4-hd2-peer-roster-stub.json"
STUB_PATH = REPO_ROOT / STUB_REL
HELPER_REL = "tooling/audit/prepare_res_d4_hd2_peer_roster_substrate.py"
HELPER_PATH = REPO_ROOT / HELPER_REL
DOC_REL = "docs/operations/res-d4-high-residual-mitigation-deep-dive.md"
DOC_PATH = REPO_ROOT / DOC_REL

EXPECTED_PEERS = (
    "fixture-peer-A",
    "fixture-peer-B",
    "loose-count-forbidden",
)
EXPECTED_FRAMES = (
    "roster-snapshot-frame--pending-production-growth",
    "roster-snapshot-frame--single-production-insufficient",
    "roster-snapshot-frame--loose-count-forbidden",
)
EXPECTED_ROSTER_EVENTS = (
    "roster-mutation--peer-added",
    "roster-mutation--peer-removed",
    "roster-mutation--kind-promoted",
)


# --------------------------------------------------------------- #
# Stub fixtures                                                    #
# --------------------------------------------------------------- #


def _load_stub() -> dict:
    if not STUB_PATH.exists():
        pytest.skip(f"Tag-71 stub not present at {STUB_REL}")
    with STUB_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _hermetic_stub_copy(tmp_path: Path) -> Path:
    """Copy the stub into tmp_path for mutation."""
    if not STUB_PATH.exists():
        pytest.skip(f"Tag-71 stub not present at {STUB_REL}")
    copy = tmp_path / "stub.json"
    copy.write_text(
        STUB_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return copy


def _run_helper_against(tmp_stub: Path) -> subprocess.CompletedProcess:
    """Run the helper with STUB_PATH redirected via a tmp tree.

    The helper resolves STUB_PATH relative to its own location, so
    we re-create a minimal tree in tmp and invoke from there.
    """
    if not HELPER_PATH.exists():
        pytest.skip(f"Tag-71 helper not present at {HELPER_REL}")
    tmp_tooling = tmp_stub.parent / "tooling" / "audit"
    tmp_tooling.mkdir(parents=True, exist_ok=True)
    helper_copy = (
        tmp_tooling / "prepare_res_d4_hd2_peer_roster_substrate.py"
    )
    shutil.copy(HELPER_PATH, helper_copy)
    stub_copy = tmp_tooling / "res-d4-hd2-peer-roster-stub.json"
    stub_copy.write_text(
        tmp_stub.read_text(encoding="utf-8"), encoding="utf-8"
    )
    # Also copy the deep-dive doc so cross-anchor check finds it.
    if DOC_PATH.exists():
        tmp_doc_dir = tmp_stub.parent / "docs" / "operations"
        tmp_doc_dir.mkdir(parents=True, exist_ok=True)
        doc_copy = (
            tmp_doc_dir
            / "res-d4-high-residual-mitigation-deep-dive.md"
        )
        doc_copy.write_text(
            DOC_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )
    return subprocess.run(
        [sys.executable, str(helper_copy)],
        capture_output=True,
        text=True,
        check=False,
    )


# --------------------------------------------------------------- #
# Axis A -- stub-shape invariants                                 #
# --------------------------------------------------------------- #


def test_t01_stub_file_exists():
    assert STUB_PATH.exists(), (
        f"Tag-71 stub missing at {STUB_REL}"
    )


def test_t02_stub_is_well_formed_json():
    text = (
        STUB_PATH.read_text(encoding="utf-8")
        if STUB_PATH.exists()
        else None
    )
    if text is None:
        pytest.skip(f"Tag-71 stub not present at {STUB_REL}")
    json.loads(text)  # raises on malformed


def test_t03_stub_declares_audit_only_and_doc_form_only():
    stub = _load_stub()
    assert stub.get("audit_only") is True, (
        "stub must declare 'audit_only: true'"
    )
    assert stub.get("doc_form_only") is True, (
        "stub must declare 'doc_form_only: true'"
    )


def test_t04_stub_declares_tag71_and_hd_2():
    stub = _load_stub()
    assert stub.get("tag") == "Tag-71", (
        f"stub must declare 'tag: Tag-71', got {stub.get('tag')!r}"
    )
    assert stub.get("hard_dep") == "HD-2", (
        f"stub must declare 'hard_dep: HD-2', got "
        f"{stub.get('hard_dep')!r}"
    )


def test_t05_three_fixture_peers_all_kind_fixture():
    stub = _load_stub()
    peers = stub.get("fixture_peers") or []
    assert len(peers) == 3, (
        f"fixture_peers must enumerate exactly 3 peers, "
        f"got {len(peers)}"
    )
    ids = sorted(p.get("peer_id") for p in peers)
    assert ids == sorted(EXPECTED_PEERS), (
        f"fixture-peer ids mismatch: {ids!r}"
    )
    for peer in peers:
        assert peer.get("kind") == "fixture", (
            f"peer {peer.get('peer_id')!r} missing 'kind: fixture'"
        )
        assert (
            peer.get("expected_production_count_contribution") == 0
        ), (
            f"peer {peer.get('peer_id')!r} must contribute 0 to "
            "production count (strict-interpretation)"
        )
        assert peer.get("expected_resolver_call") is False, (
            f"peer {peer.get('peer_id')!r} must declare "
            "'expected_resolver_call: false'"
        )


def test_t06_negative_control_peer_rejects():
    stub = _load_stub()
    peers = stub.get("fixture_peers") or []
    negative = next(
        (
            p
            for p in peers
            if p.get("peer_id") == "loose-count-forbidden"
        ),
        None,
    )
    assert negative is not None, (
        "negative-control fixture-peer 'loose-count-forbidden' "
        "missing"
    )
    assert negative.get("expected_verifier_branch") == "reject", (
        "negative-control peer must declare "
        "'expected_verifier_branch: reject'"
    )


def test_t07_three_fixture_frames_all_kind_fixture():
    stub = _load_stub()
    frames = stub.get("fixture_frames") or []
    assert len(frames) == 3, (
        f"fixture_frames must enumerate exactly 3 frames, "
        f"got {len(frames)}"
    )
    names = sorted(f.get("name") for f in frames)
    assert names == sorted(EXPECTED_FRAMES), (
        f"fixture-frame names mismatch: {names!r}"
    )
    for frame in frames:
        assert frame.get("kind") == "fixture", (
            f"frame {frame.get('name')!r} missing 'kind: fixture'"
        )
        assert frame.get("expected_resolver_call") is False, (
            f"frame {frame.get('name')!r} must declare "
            "'expected_resolver_call: false'"
        )


def test_t08_negative_control_frame_rejects():
    stub = _load_stub()
    frames = stub.get("fixture_frames") or []
    negative = next(
        (
            f
            for f in frames
            if f.get("name")
            == "roster-snapshot-frame--loose-count-forbidden"
        ),
        None,
    )
    assert negative is not None, (
        "negative-control fixture-frame missing"
    )
    assert negative.get("expected_verifier_branch") == "reject", (
        "negative-control frame must declare "
        "'expected_verifier_branch: reject'"
    )


def test_t09_strict_interpretation_invariant_explicit():
    stub = _load_stub()
    strict = stub.get("strict_interpretation_invariant") or {}
    assert strict.get("minimum_two_peers") == ">= 2", (
        "minimum_two_peers must declare '>= 2'"
    )
    excludes = strict.get("production_excludes") or []
    for required in (
        "test-fixture",
        "catalogue-stub",
        "tag-60-pre-activation-fixture",
    ):
        assert required in excludes, (
            f"production_excludes must enumerate '{required}'"
        )
    assert "B2" in str(
        strict.get("loose_interpretation_is_failure_mode", "")
    ), (
        "loose_interpretation_is_failure_mode must reference "
        "Tag-67 §5.1 B2"
    )


def test_t10_roster_mutation_event_inventory_complete():
    stub = _load_stub()
    events = stub.get("roster_mutation_event_inventory") or []
    names = [e.get("event_name") for e in events]
    for expected in EXPECTED_ROSTER_EVENTS:
        assert expected in names, (
            f"roster_mutation_event_inventory missing "
            f"required event '{expected}'"
        )
    for event in events:
        assert (
            event.get("default_state") == "not-emitted-in-audit-only"
        ), (
            f"event {event.get('event_name')!r} must default "
            "to 'not-emitted-in-audit-only'"
        )
        assert (
            event.get("kind_discriminator_required") is True
        ), (
            f"event {event.get('event_name')!r} must require "
            "kind discriminator"
        )


def test_t11_sandbox_boundary_all_defaults_set():
    stub = _load_stub()
    boundary = stub.get("sandbox_boundary") or {}
    for key in (
        "no_production_peer_count_claim",
        "no_selin_federation_direction_emit",
        "no_cfo_ratification_envelope_emit",
        "no_kind_field_default_change",
    ):
        assert boundary.get(key) is True, (
            f"sandbox_boundary.{key} must be true"
        )
    assert (
        boundary.get("verifier_production_count_default") == "strict"
    ), (
        "verifier_production_count_default must be 'strict'"
    )


def test_t12_what_this_stub_is_not_negations():
    stub = _load_stub()
    negatives = stub.get("what_this_stub_is_not") or []
    blob = " ".join(str(n) for n in negatives)
    for phrase in (
        "production peer-count claim",
        "draft-ADR",
        "promotion-PR opening",
        "direction to Selin",
        "CFO ratification envelope",
        "indefinite-deferral",
        "AR-authorisation request",
    ):
        assert phrase in blob, (
            f"what_this_stub_is_not missing negation '{phrase}'"
        )


def test_t13_deep_dive_doc_references_stub_and_helper():
    if not DOC_PATH.exists():
        pytest.skip(f"Deep-dive doc not present at {DOC_REL}")
    text = DOC_PATH.read_text(encoding="utf-8")
    for needle in (
        "tooling/audit/res-d4-hd2-peer-roster-stub.json",
        "tooling/audit/prepare_res_d4_hd2_peer_roster_substrate.py",
        "### 6.3",
        "Tag-71",
    ):
        assert needle in text, (
            f"deep-dive doc missing required cross-anchor "
            f"'{needle}'"
        )


# --------------------------------------------------------------- #
# Axis B -- helper subprocess smoke-tests                         #
# --------------------------------------------------------------- #


def test_t14_helper_green_on_live_stub(tmp_path):
    if not HELPER_PATH.exists():
        pytest.skip(f"helper not present at {HELPER_REL}")
    if not STUB_PATH.exists():
        pytest.skip(f"stub not present at {STUB_REL}")
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"helper must exit 0 on live stub, got "
        f"{result.returncode}: stderr={result.stderr!r}"
    )
    assert "OK:" in result.stdout, (
        f"helper green-path stdout must contain 'OK:', got "
        f"{result.stdout!r}"
    )


def test_t15_helper_fails_when_audit_only_flipped(tmp_path):
    stub_copy = _hermetic_stub_copy(tmp_path)
    data = json.loads(stub_copy.read_text(encoding="utf-8"))
    data["audit_only"] = False
    stub_copy.write_text(json.dumps(data), encoding="utf-8")
    result = _run_helper_against(stub_copy)
    assert result.returncode != 0, (
        "helper must reject stub with audit_only flipped to false"
    )
    assert "audit_only" in result.stderr, (
        "diagnostic must mention 'audit_only'"
    )


def test_t16_helper_fails_when_negative_control_peer_removed(
    tmp_path,
):
    stub_copy = _hermetic_stub_copy(tmp_path)
    data = json.loads(stub_copy.read_text(encoding="utf-8"))
    data["fixture_peers"] = [
        p
        for p in data["fixture_peers"]
        if p.get("peer_id") != "loose-count-forbidden"
    ]
    stub_copy.write_text(json.dumps(data), encoding="utf-8")
    result = _run_helper_against(stub_copy)
    assert result.returncode != 0, (
        "helper must reject stub when negative-control peer "
        "is removed"
    )


def test_t17_helper_fails_when_negative_control_frame_removed(
    tmp_path,
):
    stub_copy = _hermetic_stub_copy(tmp_path)
    data = json.loads(stub_copy.read_text(encoding="utf-8"))
    data["fixture_frames"] = [
        f
        for f in data["fixture_frames"]
        if f.get("name")
        != "roster-snapshot-frame--loose-count-forbidden"
    ]
    stub_copy.write_text(json.dumps(data), encoding="utf-8")
    result = _run_helper_against(stub_copy)
    assert result.returncode != 0, (
        "helper must reject stub when negative-control frame "
        "is removed"
    )


def test_t18_helper_fails_when_kind_promoted_event_dropped(
    tmp_path,
):
    stub_copy = _hermetic_stub_copy(tmp_path)
    data = json.loads(stub_copy.read_text(encoding="utf-8"))
    data["roster_mutation_event_inventory"] = [
        e
        for e in data["roster_mutation_event_inventory"]
        if e.get("event_name") != "roster-mutation--kind-promoted"
    ]
    stub_copy.write_text(json.dumps(data), encoding="utf-8")
    result = _run_helper_against(stub_copy)
    assert result.returncode != 0, (
        "helper must reject stub when kind-promoted event is "
        "dropped from inventory"
    )
    assert "kind-promoted" in result.stderr, (
        "diagnostic must mention the missing event name"
    )


def test_t19_no_production_claim_in_stub():
    """Sandbox-boundary: stub MUST NOT claim production peers."""
    if not STUB_PATH.exists():
        pytest.skip(f"stub not present at {STUB_REL}")
    stub = _load_stub()
    # Every fixture-peer must declare kind: fixture (not production).
    peers = stub.get("fixture_peers") or []
    for peer in peers:
        assert peer.get("kind") == "fixture", (
            f"peer {peer.get('peer_id')!r} must declare "
            "'kind: fixture' (no production peer-count claim)"
        )
    # No fixture-frame may claim production_count >= 2 (which would
    # be a HD-2-satisfied claim).
    frames = stub.get("fixture_frames") or []
    for frame in frames:
        prod_count = frame.get("expected_production_count")
        if prod_count is not None:
            assert prod_count < 2, (
                f"frame {frame.get('name')!r} must NOT declare "
                f"production_count >= 2 (would be HD-2-satisfied "
                f"claim); got {prod_count}"
            )


def test_t20_fixture_entries_declare_tag_60_compat():
    stub = _load_stub()
    peers = stub.get("fixture_peers") or []
    for peer in peers:
        assert peer.get("tag_60_compat") is True, (
            f"peer {peer.get('peer_id')!r} must declare "
            "'tag_60_compat: true' (Tag-71 reuses Tag-60 shape)"
        )
    frames = stub.get("fixture_frames") or []
    for frame in frames:
        assert frame.get("tag_60_compat") is True, (
            f"frame {frame.get('name')!r} must declare "
            "'tag_60_compat: true' (Tag-71 reuses Tag-60 shape)"
        )


def test_t21_upstream_anchors_cite_tag_67_65_69_70_60():
    stub = _load_stub()
    anchors = stub.get("upstream_anchors") or {}
    assert "Tag-67" in str(
        anchors.get("tag_67_pre_mortem_anchor", "")
    ) or "§5.1" in str(
        anchors.get("tag_67_pre_mortem_anchor", "")
    ), "tag_67_pre_mortem_anchor must reference Tag-67 §5"
    assert "Tag-65" in str(
        anchors.get("tag_65_promotion_sequencing_anchor", "")
    ) or "§2.4" in str(
        anchors.get("tag_65_promotion_sequencing_anchor", "")
    ), (
        "tag_65_promotion_sequencing_anchor must reference Tag-65 "
        "§2.4 activation-trigger"
    )
    assert anchors.get("tag_70_hd_1_substrate_pr") == 446, (
        "tag_70_hd_1_substrate_pr must be 446"
    )
    assert anchors.get("tag_69_deep_dive_pr") == 440, (
        "tag_69_deep_dive_pr must be 440"
    )
    assert anchors.get("tag_60_pre_activation_stub_pr") == 382, (
        "tag_60_pre_activation_stub_pr must be 382"
    )


def test_t22_helper_fails_when_strict_invariant_loosened(tmp_path):
    """Helper rejects a mutilated stub where minimum_two_peers is
    loosened from '>= 2'."""
    stub_copy = _hermetic_stub_copy(tmp_path)
    data = json.loads(stub_copy.read_text(encoding="utf-8"))
    data["strict_interpretation_invariant"]["minimum_two_peers"] = (
        ">= 1"
    )
    stub_copy.write_text(json.dumps(data), encoding="utf-8")
    result = _run_helper_against(stub_copy)
    assert result.returncode != 0, (
        "helper must reject stub when minimum_two_peers is "
        "loosened from '>= 2'"
    )
    assert "minimum_two_peers" in result.stderr or "strict" in (
        result.stderr.lower()
    ), (
        "diagnostic must mention the strict-interpretation "
        "invariant"
    )


def test_t23_every_fixture_peer_zero_production_contribution():
    """Production-count invariant: every fixture-peer contributes
    exactly 0 to production count (audit-only pin)."""
    stub = _load_stub()
    peers = stub.get("fixture_peers") or []
    total = sum(
        p.get("expected_production_count_contribution", 0)
        for p in peers
    )
    assert total == 0, (
        f"sum of production-count contributions across all "
        f"fixture-peers must be 0 (audit-only); got {total}"
    )
