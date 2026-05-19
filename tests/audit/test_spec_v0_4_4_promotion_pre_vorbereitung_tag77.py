# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-77 tests for the Wirelang-Spec v0.4.4 Promotion
Pre-Vorbereitung Substrate (Schluss-Stein of the Tag-63..Tag-72
substrate trilogy).
=========================================================================

Three-axis coverage:

  Axis A -- Snapshot-stub shape invariants over the live Tag-77 file
            ``tooling/audit/spec-v0-4-4-promotion-pre-readiness-snapshot.json``
            (skip-if-absent for portability).
  Axis B -- Helper smoke-tests via subprocess against
            ``tooling/audit/prepare_spec_v0_4_4_promotion_substrate.py``,
            including hermetic mutilated-stub variants in
            ``tmp_path`` for negative-control coverage.
  Axis C -- Doc §8 cross-anchor presence in
            ``docs/operations/wirelang-spec-v0-4-4-promotion-sequencing.md``.

Test inventory (>=18 hermetic, all stdlib + pytest):

  T01  Snapshot stub exists at the expected path.
  T02  Snapshot stub is well-formed JSON.
  T03  Snapshot declares ``audit_only: true`` and
       ``doc_form_only: true`` and ``indefinite_deferral_default:
       true``.
  T04  Snapshot declares ``tag: Tag-77`` and
       ``phase: promotion-pre-vorbereitung``.
  T05  Snapshot upstream_anchors enumerates Tag-63..Tag-72 PR
       references plus ADR-0007/0014/0023a/0023b/0025.
  T06  Snapshot sandbox_boundary sets every Tag-77 boundary flag
       to its audit-only default (no promotion-PR opening,
       no AR-authorisation request, no draft-ADR, no indefinite-
       deferral lifting, no Pin-Pack edit, no NATS-KV schema
       default change, no OTS-anchor activation; snapshot_default
       _mode == inspection-only; score_is_advisory_only).
  T07  Snapshot scoring_methodology declares score_range [0, 5],
       five named score_dimensions each at weight 1, and the
       advisory-only + not-a-promotion-authorisation flags.
  T08  Snapshot per_item_snapshot enumerates exactly five items
       (RES-D1..D5) each as kind:fixture.
  T09  Snapshot per-item entries all declare
       ``ceo_triage_authorisation: false`` (FROZEN-FALSE Tag-77
       invariant) and ``score: 4`` (Sandbox ceiling).
  T10  Snapshot per-item entries all declare the four substrate
       dimensions (substrate_pinned, ots_probe_coverage,
       pre_mortem_covered, hard_dep_substrate_prepared) as true.
  T11  Snapshot RES-D4 entry carries hard_dep_axis
       ``HD-1+HD-2+HD-3`` and hd_substrate_pr_refs pinning
       PR #446, #452, #458.
  T12  Snapshot aggregate_snapshot declares items_evaluated 5,
       items_at_ceiling_4 5, items_at_score_5 0, items_below_4 0,
       substrate_trilogy_complete true, verdict
       ``substrate-complete-ceo-triage-pending``,
       verdict_does_not_authorise_promotion true.
  T13  Snapshot what_this_snapshot_is_not explicitly negates
       promotion-PR, AR-authorisation, draft-ADR, Pin-Pack,
       NATS-KV, OTS-anchor activation, indefinite-deferral
       lifting, Henrik-Voss.
  T14  Snapshot snapshot_emit_discipline sets every emit-channel
       boundary to its audit-only default (score_emit_default ==
       inspection-only; score_emit_target ==
       stdout-of-helper-only; not emitted to notify-log,
       activity-log, audit-sample rotation; no timestamp drift).
  T15  Doc §8 cross-anchor present in promotion-sequencing doc
       referencing the snapshot stub + helper paths + Tag-77
       marker.
  T16  Helper subprocess exits 0 on the live snapshot stub.
  T17  Helper subprocess exits non-zero when ``audit_only`` is
       flipped to ``false`` (mutilated stub).
  T18  Helper subprocess exits non-zero when one RES-Dn entry has
       ``ceo_triage_authorisation`` flipped to true (Sandbox-
       boundary violation; the FROZEN-FALSE invariant is load-
       bearing).
  T19  Helper subprocess exits non-zero when a per-item entry's
       ``score`` is flipped to 5 (Sandbox ceiling violation;
       score 5 is unreachable from claude-dev hand).
  T20  Helper subprocess exits non-zero when one of the four
       substrate dimensions is flipped to false on a per-item
       entry (the Tag-63..Tag-72 substrate trilogy is load-
       bearing).
  T21  Helper subprocess exits non-zero when the aggregate
       verdict is flipped away from
       ``substrate-complete-ceo-triage-pending``.
  T22  Helper subprocess exits non-zero when the
       hd_substrate_pr_refs on RES-D4 is corrupted (a wrong PR
       number for HD-1/HD-2/HD-3).
  T23  Sandbox-boundary invariant: snapshot MUST NOT enumerate
       any per-item entry with ``ceo_triage_authorisation: true``
       (frozen-false at Tag-77).
  T24  Sandbox-boundary invariant: snapshot's aggregate
       ``items_at_score_5`` MUST be 0 in any Tag-77 snapshot.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
STUB_REL = (
    "tooling/audit/spec-v0-4-4-promotion-pre-readiness-snapshot.json"
)
STUB_PATH = REPO_ROOT / STUB_REL
HELPER_REL = (
    "tooling/audit/prepare_spec_v0_4_4_promotion_substrate.py"
)
HELPER_PATH = REPO_ROOT / HELPER_REL
DOC_REL = (
    "docs/operations/wirelang-spec-v0-4-4-promotion-sequencing.md"
)
DOC_PATH = REPO_ROOT / DOC_REL

EXPECTED_ITEMS = ("RES-D1", "RES-D2", "RES-D3", "RES-D4", "RES-D5")
EXPECTED_DIMENSIONS = (
    "substrate-pinned",
    "ots-probe-coverage",
    "pre-mortem-covered",
    "hard-dep-substrate-prepared",
    "ceo-triage-authorisation",
)


# --------------------------------------------------------------- #
# Fixtures                                                         #
# --------------------------------------------------------------- #


def _load_stub() -> dict:
    if not STUB_PATH.exists():
        pytest.skip(f"Tag-77 snapshot stub not present at {STUB_REL}")
    with STUB_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _hermetic_stub_copy(tmp_path: Path) -> dict:
    """Copy the stub into tmp_path and return the parsed dict so the
    caller can mutate it before re-serialising via _write_mutated_stub.
    """
    if not STUB_PATH.exists():
        pytest.skip(f"Tag-77 snapshot stub not present at {STUB_REL}")
    return json.loads(STUB_PATH.read_text(encoding="utf-8"))


def _run_helper_against_mutated(
    tmp_path: Path, mutator
) -> subprocess.CompletedProcess:
    """Apply `mutator(stub_dict)` (in-place mutation), write the
    mutated stub into a tmp tree alongside a copy of the helper,
    and invoke the helper as a subprocess. Returns the
    CompletedProcess.
    """
    if not HELPER_PATH.exists():
        pytest.skip(f"Tag-77 helper not present at {HELPER_REL}")
    stub = _hermetic_stub_copy(tmp_path)
    mutator(stub)
    tmp_tooling = tmp_path / "tooling" / "audit"
    tmp_tooling.mkdir(parents=True, exist_ok=True)
    helper_copy = (
        tmp_tooling / "prepare_spec_v0_4_4_promotion_substrate.py"
    )
    shutil.copy(HELPER_PATH, helper_copy)
    stub_copy = (
        tmp_tooling
        / "spec-v0-4-4-promotion-pre-readiness-snapshot.json"
    )
    stub_copy.write_text(
        json.dumps(stub, indent=2), encoding="utf-8"
    )
    # Mirror the doc so the §8 cross-anchor check finds the
    # required substrings.
    if DOC_PATH.exists():
        tmp_doc_dir = tmp_path / "docs" / "operations"
        tmp_doc_dir.mkdir(parents=True, exist_ok=True)
        doc_copy = (
            tmp_doc_dir
            / "wirelang-spec-v0-4-4-promotion-sequencing.md"
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


def _run_helper_on_live() -> subprocess.CompletedProcess:
    if not HELPER_PATH.exists():
        pytest.skip(f"Tag-77 helper not present at {HELPER_REL}")
    return subprocess.run(
        [sys.executable, str(HELPER_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )


# --------------------------------------------------------------- #
# Axis A -- Snapshot-shape invariants                             #
# --------------------------------------------------------------- #


def test_t01_snapshot_stub_exists():
    assert STUB_PATH.exists(), (
        f"Tag-77 snapshot stub missing at {STUB_REL}"
    )


def test_t02_snapshot_is_well_formed_json():
    if not STUB_PATH.exists():
        pytest.skip(f"Tag-77 snapshot stub not present at {STUB_REL}")
    text = STUB_PATH.read_text(encoding="utf-8")
    json.loads(text)  # raises on malformed


def test_t03_snapshot_declares_audit_only_and_indef_deferral():
    stub = _load_stub()
    assert stub.get("audit_only") is True
    assert stub.get("doc_form_only") is True
    assert stub.get("indefinite_deferral_default") is True


def test_t04_snapshot_declares_tag77_and_phase():
    stub = _load_stub()
    assert stub.get("tag") == "Tag-77", (
        f"snapshot must declare 'tag: Tag-77', got "
        f"{stub.get('tag')!r}"
    )
    assert stub.get("phase") == "promotion-pre-vorbereitung", (
        f"snapshot must declare "
        f"'phase: promotion-pre-vorbereitung', got "
        f"{stub.get('phase')!r}"
    )


def test_t05_upstream_anchors_enumerated():
    stub = _load_stub()
    anchors = stub.get("upstream_anchors") or {}
    for tag_key in (
        "tag_63_v0_4_4_draft_pr",
        "tag_64_res_d_coverage_pr",
        "tag_65_promotion_sequencing_pr",
        "tag_66_res_d_ots_probe_pr",
        "tag_67_activation_pre_mortem_pr",
        "tag_68_pre_mortem_coverage_pr",
        "tag_69_res_d4_deep_dive_pr",
        "tag_70_hd_1_ots_substrate_pr",
        "tag_71_hd_2_peer_roster_substrate_pr",
        "tag_72_hd_3_audit_coverage_substrate_pr",
    ):
        assert tag_key in anchors, (
            f"upstream_anchors missing required Tag-PR key "
            f"'{tag_key}'"
        )
    for adr_key in (
        "adr_0007_pin_pack_discipline",
        "adr_0014_audit_sample_rotation",
        "adr_0023a_sandbox_boundary",
        "adr_0023b_operator_hand_vs_ar",
        "adr_0025_three_axis_audit_anchor",
    ):
        assert adr_key in anchors, (
            f"upstream_anchors missing required ADR key "
            f"'{adr_key}'"
        )
    # Hard-dep PR numbers are load-bearing.
    assert anchors.get("tag_70_hd_1_ots_substrate_pr") == 446
    assert anchors.get("tag_71_hd_2_peer_roster_substrate_pr") == 452
    assert (
        anchors.get("tag_72_hd_3_audit_coverage_substrate_pr") == 458
    )


def test_t06_sandbox_boundary_all_defaults_set():
    stub = _load_stub()
    boundary = stub.get("sandbox_boundary") or {}
    for key in (
        "no_promotion_pr_opening",
        "no_ar_authorisation_request_emit",
        "no_draft_adr_writing",
        "no_indefinite_deferral_lifting",
        "no_pin_pack_edit",
        "no_nats_kv_schema_default_change",
        "no_ots_anchor_activation",
        "score_is_advisory_only",
    ):
        assert boundary.get(key) is True, (
            f"sandbox_boundary.{key} must be true (audit-only)"
        )
    assert (
        boundary.get("snapshot_default_mode") == "inspection-only"
    )


def test_t07_scoring_methodology_shape():
    stub = _load_stub()
    sm = stub.get("scoring_methodology") or {}
    assert list(sm.get("score_range") or []) == [0, 5]
    assert sm.get("advisory_only") is True
    assert sm.get("not_a_promotion_authorisation") is True
    dims = sm.get("score_dimensions") or []
    assert len(dims) == 5
    names = sorted(d.get("dimension_name") for d in dims)
    assert names == sorted(EXPECTED_DIMENSIONS), (
        f"score_dimensions names mismatch: {names!r}"
    )
    for dim in dims:
        assert dim.get("weight") == 1, (
            f"dimension {dim.get('dimension_name')!r} must declare "
            "'weight: 1' (equal-weight aggregate)"
        )


def test_t08_per_item_snapshot_enumerates_all_five():
    stub = _load_stub()
    items = stub.get("per_item_snapshot") or []
    assert len(items) == 5, (
        f"per_item_snapshot must enumerate 5 items, got {len(items)}"
    )
    names = sorted(e.get("item") for e in items)
    assert names == sorted(EXPECTED_ITEMS), (
        f"per_item_snapshot names mismatch: {names!r}"
    )
    for entry in items:
        assert entry.get("kind") == "fixture", (
            f"per-item entry {entry.get('item')!r} must declare "
            "'kind: fixture'"
        )


def test_t09_per_item_ceo_triage_frozen_false_score_4():
    stub = _load_stub()
    for entry in stub.get("per_item_snapshot") or []:
        item = entry.get("item")
        assert entry.get("ceo_triage_authorisation") is False, (
            f"per-item entry {item!r} must declare "
            "'ceo_triage_authorisation: false' (FROZEN-FALSE at "
            "Tag-77)"
        )
        assert entry.get("score") == 4, (
            f"per-item entry {item!r} must declare 'score: 4' "
            "(Sandbox ceiling)"
        )
        assert entry.get("score_ceiling_from_sandbox") == 4
        assert entry.get("ceiling_blocker"), (
            f"per-item entry {item!r} must declare a "
            "'ceiling_blocker' string"
        )


def test_t10_per_item_substrate_dimensions_all_true():
    stub = _load_stub()
    for entry in stub.get("per_item_snapshot") or []:
        item = entry.get("item")
        for dim in (
            "substrate_pinned",
            "ots_probe_coverage",
            "pre_mortem_covered",
            "hard_dep_substrate_prepared",
        ):
            assert entry.get(dim) is True, (
                f"per-item entry {item!r} must declare "
                f"'{dim}: true' (substrate trilogy is "
                "load-bearing)"
            )


def test_t11_res_d4_hd_substrate_pr_refs():
    stub = _load_stub()
    items = stub.get("per_item_snapshot") or []
    res_d4 = next(
        (e for e in items if e.get("item") == "RES-D4"), None
    )
    assert res_d4 is not None, "RES-D4 entry missing"
    assert res_d4.get("hard_dep_axis") == "HD-1+HD-2+HD-3"
    hd_refs = res_d4.get("hd_substrate_pr_refs") or {}
    assert hd_refs.get("hd_1_ots_substrate_pr") == 446
    assert hd_refs.get("hd_2_peer_roster_substrate_pr") == 452
    assert hd_refs.get("hd_3_audit_coverage_substrate_pr") == 458


def test_t12_aggregate_snapshot_verdict():
    stub = _load_stub()
    agg = stub.get("aggregate_snapshot") or {}
    assert agg.get("items_evaluated") == 5
    assert agg.get("items_at_ceiling_4") == 5
    assert agg.get("items_at_score_5") == 0
    assert agg.get("items_below_4") == 0
    assert agg.get("substrate_trilogy_complete") is True
    assert agg.get("ceo_triage_authorisation_pending_count") == 5
    assert agg.get("live_ots_activation_pending_for_count") == 1
    assert (
        agg.get("verdict") == "substrate-complete-ceo-triage-pending"
    )
    assert agg.get("verdict_does_not_authorise_promotion") is True


def test_t13_what_this_snapshot_is_not_explicit_negations():
    stub = _load_stub()
    negatives = stub.get("what_this_snapshot_is_not") or []
    blob = " ".join(str(n) for n in negatives)
    for phrase in (
        "promotion-PR",
        "AR-authorisation",
        "draft-ADR",
        "Pin-Pack",
        "NATS-KV",
        "OTS-anchor activation",
        "indefinite-deferral lifting",
        "Henrik-Voss",
    ):
        assert phrase in blob, (
            f"what_this_snapshot_is_not must explicitly negate "
            f"'{phrase}'"
        )


def test_t14_snapshot_emit_discipline_all_boundaries():
    stub = _load_stub()
    emit = stub.get("snapshot_emit_discipline") or {}
    assert emit.get("score_emit_default") == "inspection-only"
    assert emit.get("score_emit_target") == "stdout-of-helper-only"
    assert emit.get("score_does_not_emit_to_notify_log") is True
    assert (
        emit.get("score_does_not_emit_to_audit_sample_rotation")
        is True
    )
    assert emit.get("score_does_not_emit_to_activity_log") is True
    assert emit.get("snapshot_carries_no_timestamp_drift") is True


# --------------------------------------------------------------- #
# Axis C -- Doc §8 cross-anchor                                   #
# --------------------------------------------------------------- #


def test_t15_doc_section_8_cross_anchor_present():
    if not DOC_PATH.exists():
        pytest.skip(f"doc not present at {DOC_REL}")
    text = DOC_PATH.read_text(encoding="utf-8")
    for needle in (
        "## 8.",
        "Tag-77",
        "Promotion Pre-Readiness",
        "spec-v0-4-4-promotion-pre-readiness-snapshot.json",
        "prepare_spec_v0_4_4_promotion_substrate.py",
        "substrate-complete-ceo-triage-pending",
        "Schluss-Stein",
    ):
        assert needle in text, (
            f"doc §8 missing required cross-anchor '{needle}'"
        )


# --------------------------------------------------------------- #
# Axis B -- Helper subprocess smoke + mutilation                   #
# --------------------------------------------------------------- #


def test_t16_helper_exits_0_on_live_snapshot():
    result = _run_helper_on_live()
    assert result.returncode == 0, (
        f"helper expected exit 0, got {result.returncode}; "
        f"stderr={result.stderr!r}"
    )
    # Sanity: stdout must mention the per-item score line for each
    # of RES-D1..D5 (advisory-only score-table print).
    for item in EXPECTED_ITEMS:
        assert item in result.stdout, (
            f"helper stdout must mention {item} in score table; "
            f"stdout={result.stdout!r}"
        )


def test_t17_helper_rejects_audit_only_false(tmp_path):
    def mutator(stub: dict) -> None:
        stub["audit_only"] = False

    result = _run_helper_against_mutated(tmp_path, mutator)
    assert result.returncode != 0, (
        "helper must reject snapshot with audit_only:false"
    )
    assert "audit_only" in result.stderr, (
        f"helper stderr must mention 'audit_only'; "
        f"stderr={result.stderr!r}"
    )


def test_t18_helper_rejects_ceo_triage_authorisation_flip(tmp_path):
    def mutator(stub: dict) -> None:
        # Flip the first RES-Dn entry's ceo_triage_authorisation
        # to true (FROZEN-FALSE invariant violation).
        items = stub.get("per_item_snapshot") or []
        items[0]["ceo_triage_authorisation"] = True

    result = _run_helper_against_mutated(tmp_path, mutator)
    assert result.returncode != 0, (
        "helper must reject snapshot with any per-item "
        "ceo_triage_authorisation flipped to true"
    )
    assert "ceo_triage_authorisation" in result.stderr, (
        f"helper stderr must mention "
        f"'ceo_triage_authorisation'; stderr={result.stderr!r}"
    )


def test_t19_helper_rejects_score_5(tmp_path):
    def mutator(stub: dict) -> None:
        # Flip score to 5 on the first item (Sandbox ceiling
        # violation).
        items = stub.get("per_item_snapshot") or []
        items[0]["score"] = 5

    result = _run_helper_against_mutated(tmp_path, mutator)
    assert result.returncode != 0, (
        "helper must reject snapshot with any per-item score == 5 "
        "(Sandbox ceiling violation)"
    )
    assert "score" in result.stderr, (
        f"helper stderr must mention 'score'; "
        f"stderr={result.stderr!r}"
    )


def test_t20_helper_rejects_substrate_dimension_false(tmp_path):
    def mutator(stub: dict) -> None:
        # Flip the substrate_pinned dim to false on the first item.
        items = stub.get("per_item_snapshot") or []
        items[0]["substrate_pinned"] = False

    result = _run_helper_against_mutated(tmp_path, mutator)
    assert result.returncode != 0, (
        "helper must reject snapshot with substrate_pinned:false "
        "on any per-item entry"
    )
    assert "substrate_pinned" in result.stderr, (
        f"helper stderr must mention 'substrate_pinned'; "
        f"stderr={result.stderr!r}"
    )


def test_t21_helper_rejects_verdict_drift(tmp_path):
    def mutator(stub: dict) -> None:
        agg = stub.get("aggregate_snapshot") or {}
        agg["verdict"] = "promotion-authorised"  # forbidden!

    result = _run_helper_against_mutated(tmp_path, mutator)
    assert result.returncode != 0, (
        "helper must reject snapshot with verdict drifted from "
        "'substrate-complete-ceo-triage-pending'"
    )
    assert "verdict" in result.stderr, (
        f"helper stderr must mention 'verdict'; "
        f"stderr={result.stderr!r}"
    )


def test_t22_helper_rejects_corrupted_hd_pr_refs(tmp_path):
    def mutator(stub: dict) -> None:
        items = stub.get("per_item_snapshot") or []
        res_d4 = next(
            (e for e in items if e.get("item") == "RES-D4"), None
        )
        assert res_d4 is not None
        # Corrupt the HD-1 substrate PR number.
        res_d4["hd_substrate_pr_refs"]["hd_1_ots_substrate_pr"] = 999

    result = _run_helper_against_mutated(tmp_path, mutator)
    assert result.returncode != 0, (
        "helper must reject snapshot with corrupted "
        "hd_substrate_pr_refs (PR provenance is load-bearing)"
    )
    assert "hd_1_ots_substrate_pr" in result.stderr, (
        f"helper stderr must mention 'hd_1_ots_substrate_pr'; "
        f"stderr={result.stderr!r}"
    )


# --------------------------------------------------------------- #
# Sandbox-boundary invariants                                      #
# --------------------------------------------------------------- #


def test_t23_no_per_item_with_ceo_triage_true():
    """The Tag-77 snapshot MUST NOT enumerate any per-item entry
    with ceo_triage_authorisation flipped to true. This is the
    load-bearing FROZEN-FALSE invariant of audit-only posture."""
    stub = _load_stub()
    for entry in stub.get("per_item_snapshot") or []:
        assert entry.get("ceo_triage_authorisation") is False, (
            f"per-item entry {entry.get('item')!r} must declare "
            "'ceo_triage_authorisation: false'"
        )


def test_t24_aggregate_items_at_score_5_is_zero():
    """In any Tag-77 audit-only snapshot,
    aggregate_snapshot.items_at_score_5 MUST be 0. The Sandbox
    ceiling is 4/5 by construction (Dim 5 ceo-triage-authorisation
    is FROZEN-FALSE); a non-zero items_at_score_5 would indicate
    a Sandbox-boundary violation."""
    stub = _load_stub()
    agg = stub.get("aggregate_snapshot") or {}
    assert agg.get("items_at_score_5") == 0, (
        f"aggregate_snapshot.items_at_score_5 must be 0 in any "
        f"Tag-77 audit-only snapshot; got "
        f"{agg.get('items_at_score_5')!r}"
    )
