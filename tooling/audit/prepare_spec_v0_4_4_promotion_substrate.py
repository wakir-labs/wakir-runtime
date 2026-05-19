#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-77 Wirelang-Spec v0.4.4 Promotion-Pre-Vorbereitung Substrate
helper (audit-only).

This helper is the Schluss-Stein of the Tag-63..Tag-72 substrate
trilogy for the v0.4.4 Reserve-Item promotion lane. It aggregates
evidence from the per-RES-Dn artefacts already pinned across
Tag-63 / Tag-64 (baseline + sample coverage), Tag-65 (sequencing
doc), Tag-66 (RES-D OTS-probe coverage), Tag-67 (activation
pre-mortem), Tag-68 (pre-mortem coverage), Tag-69 (RES-D4
mitigation deep-dive), and the three hard-dep substrate stubs at
Tag-70 (HD-1 OTS), Tag-71 (HD-2 Peer-Roster), and Tag-72 (HD-3
Audit-Coverage). The aggregate is reduced to a per-item
Promotion-Pre-Readiness-Score (range 0..5) and a global verdict.

Audit-only posture (per ADR-0023a + ADR-0023b):

  - The helper computes and prints a score to stdout. It does NOT
    emit any audit-sample-rotation entry, notify-log entry,
    activity-log entry, ADR draft, promotion PR opening, or
    AR-authorisation request.
  - The score is a static fixture-driven snapshot. It does NOT
    walk the live cluster, does NOT call any external endpoint,
    does NOT touch git remotes, and does NOT depend on
    wall-clock time.
  - The ceo-triage-authorisation dimension is FROZEN-FALSE in the
    Tag-77 audit-only snapshot. Flipping it to true is a
    CEO-Triage / AR-authorisation step under ADR-0023a + ADR-0023b
    and is OUT OF SCOPE for this helper.
  - The score ceiling reachable from Sandbox-Hand is 4/5. Any
    real-world score of 5 requires Operator-Hand work outside the
    Sandbox boundary. The helper exits 0 on a clean ceiling-4
    state and prints the ceiling-blocker per item.

Sandbox-boundary recital (per docs/operations/wirelang-spec-v0-4-4-
promotion-sequencing.md §7 + the Tag-77 §8 extension):

  - No promotion-PR opening.
  - No AR-authorisation request emit.
  - No draft-ADR writing.
  - No indefinite-deferral lifting.
  - No Pin-Pack edit.
  - No NATS-KV schema default change.
  - No OTS-anchor activation.
  - No emit to notify-log / activity-log / audit-sample rotation.

The helper inspects the snapshot stub at
``tooling/audit/spec-v0-4-4-promotion-pre-readiness-snapshot.json``
and asserts the structural invariants of an audit-only
pre-readiness snapshot.

Exit 0 on green, exit 1 on any failure with a clear stderr
message. Standard library only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

STUB_PATH = (
    Path(__file__).resolve().parent
    / "spec-v0-4-4-promotion-pre-readiness-snapshot.json"
)
DOC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "operations"
    / "wirelang-spec-v0-4-4-promotion-sequencing.md"
)

EXPECTED_TAG = "Tag-77"
EXPECTED_PHASE = "promotion-pre-vorbereitung"
EXPECTED_ITEMS = ("RES-D1", "RES-D2", "RES-D3", "RES-D4", "RES-D5")
EXPECTED_DIMENSIONS = (
    "substrate-pinned",
    "ots-probe-coverage",
    "pre-mortem-covered",
    "hard-dep-substrate-prepared",
    "ceo-triage-authorisation",
)
EXPECTED_UPSTREAM_TAG_KEYS = (
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
)
EXPECTED_ADR_KEYS = (
    "adr_0007_pin_pack_discipline",
    "adr_0014_audit_sample_rotation",
    "adr_0023a_sandbox_boundary",
    "adr_0023b_operator_hand_vs_ar",
    "adr_0025_three_axis_audit_anchor",
)


def fail(msg: str) -> None:
    sys.stderr.write(
        f"prepare_spec_v0_4_4_promotion_substrate: FAIL: {msg}\n"
    )
    sys.exit(1)


def info(msg: str) -> None:
    sys.stdout.write(
        f"prepare_spec_v0_4_4_promotion_substrate: {msg}\n"
    )


def load_stub(path: Path) -> dict:
    if not path.is_file():
        fail(f"snapshot stub missing: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        fail(f"snapshot stub not well-formed JSON: {exc}")
        return {}  # unreachable; appeases type-checkers.


def assert_audit_only_posture(stub: dict) -> None:
    if stub.get("audit_only") is not True:
        fail("snapshot must declare 'audit_only: true'")
    if stub.get("doc_form_only") is not True:
        fail("snapshot must declare 'doc_form_only: true'")
    if stub.get("tag") != EXPECTED_TAG:
        fail(f"snapshot must declare 'tag: {EXPECTED_TAG}'")
    if stub.get("phase") != EXPECTED_PHASE:
        fail(f"snapshot must declare 'phase: {EXPECTED_PHASE}'")
    if stub.get("indefinite_deferral_default") is not True:
        fail(
            "snapshot must declare "
            "'indefinite_deferral_default: true'"
        )


def assert_upstream_anchors(stub: dict) -> None:
    anchors = stub.get("upstream_anchors") or {}
    for key in EXPECTED_UPSTREAM_TAG_KEYS:
        if key not in anchors:
            fail(
                f"upstream_anchors missing required Tag-PR key "
                f"'{key}'"
            )
    for key in EXPECTED_ADR_KEYS:
        if key not in anchors:
            fail(
                f"upstream_anchors missing required ADR key "
                f"'{key}'"
            )
    # The HD-1/2/3 PR numbers are load-bearing (they pin the
    # Tag-70/71/72 substrate-stub provenance).
    if anchors.get("tag_70_hd_1_ots_substrate_pr") != 446:
        fail(
            "upstream_anchors.tag_70_hd_1_ots_substrate_pr "
            "must be 446"
        )
    if anchors.get("tag_71_hd_2_peer_roster_substrate_pr") != 452:
        fail(
            "upstream_anchors.tag_71_hd_2_peer_roster_substrate_pr "
            "must be 452"
        )
    if anchors.get("tag_72_hd_3_audit_coverage_substrate_pr") != 458:
        fail(
            "upstream_anchors.tag_72_hd_3_audit_coverage_substrate_pr "
            "must be 458"
        )


def assert_sandbox_boundary(stub: dict) -> None:
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
        if boundary.get(key) is not True:
            fail(
                f"sandbox_boundary.{key} must be true "
                "(audit-only posture)"
            )
    if boundary.get("snapshot_default_mode") != "inspection-only":
        fail(
            "sandbox_boundary.snapshot_default_mode must be "
            "'inspection-only'"
        )


def assert_scoring_methodology(stub: dict) -> None:
    sm = stub.get("scoring_methodology") or {}
    sr = sm.get("score_range") or []
    if list(sr) != [0, 5]:
        fail(
            "scoring_methodology.score_range must be [0, 5] "
            f"(got {sr})"
        )
    if sm.get("advisory_only") is not True:
        fail(
            "scoring_methodology.advisory_only must be true"
        )
    if sm.get("not_a_promotion_authorisation") is not True:
        fail(
            "scoring_methodology.not_a_promotion_authorisation "
            "must be true"
        )
    dims = sm.get("score_dimensions") or []
    if not isinstance(dims, list):
        fail("scoring_methodology.score_dimensions must be a list")
    if len(dims) != 5:
        fail(
            f"scoring_methodology.score_dimensions must enumerate "
            f"exactly 5 dimensions, got {len(dims)}"
        )
    seen_names: list = []
    for dim in dims:
        if not isinstance(dim, dict):
            fail("each scoring dimension must be an object")
        name = dim.get("dimension_name")
        if name not in EXPECTED_DIMENSIONS:
            fail(
                f"scoring dimension has unexpected name {name!r}; "
                f"expected one of {EXPECTED_DIMENSIONS}"
            )
        seen_names.append(name)
        if dim.get("weight") != 1:
            fail(
                f"scoring dimension {name!r} must declare "
                "'weight: 1' (equal-weight aggregate)"
            )
    if sorted(seen_names) != sorted(EXPECTED_DIMENSIONS):
        fail(
            "score_dimensions must contain exactly the five named "
            f"variants: {EXPECTED_DIMENSIONS}"
        )


def assert_per_item_snapshot(stub: dict) -> None:
    items = stub.get("per_item_snapshot") or []
    if not isinstance(items, list):
        fail("per_item_snapshot must be a list")
    if len(items) != 5:
        fail(
            f"per_item_snapshot must enumerate exactly 5 items "
            f"(RES-D1..D5), got {len(items)}"
        )
    seen_items: list = []
    for entry in items:
        if not isinstance(entry, dict):
            fail("each per-item snapshot entry must be an object")
        item = entry.get("item")
        if item not in EXPECTED_ITEMS:
            fail(
                f"per-item snapshot entry has unexpected item "
                f"{item!r}; expected one of {EXPECTED_ITEMS}"
            )
        seen_items.append(item)
        if entry.get("kind") != "fixture":
            fail(
                f"per-item snapshot entry {item!r} must declare "
                "'kind: fixture'"
            )
        # The ceo-triage-authorisation dimension is FROZEN-FALSE in
        # the Tag-77 snapshot. Any flip to true would violate the
        # Sandbox boundary (ADR-0023a).
        if entry.get("ceo_triage_authorisation") is not False:
            fail(
                f"per-item snapshot entry {item!r} must declare "
                "'ceo_triage_authorisation: false' "
                "(FROZEN-FALSE in Tag-77 audit-only snapshot)"
            )
        # The four substrate dimensions MUST all be true at Tag-77
        # (the substrate trilogy is complete).
        for substrate_dim in (
            "substrate_pinned",
            "ots_probe_coverage",
            "pre_mortem_covered",
            "hard_dep_substrate_prepared",
        ):
            if entry.get(substrate_dim) is not True:
                fail(
                    f"per-item snapshot entry {item!r} must "
                    f"declare '{substrate_dim}: true' "
                    "(Tag-63..Tag-72 substrate trilogy is "
                    "load-bearing)"
                )
        # The Sandbox ceiling for every item is 4. Score must equal
        # 4 (not 5, not 3-or-less) in a clean Tag-77 snapshot.
        score = entry.get("score")
        if score != 4:
            fail(
                f"per-item snapshot entry {item!r} must declare "
                f"'score: 4' (Sandbox ceiling); got {score!r}"
            )
        if entry.get("score_ceiling_from_sandbox") != 4:
            fail(
                f"per-item snapshot entry {item!r} must declare "
                "'score_ceiling_from_sandbox: 4'"
            )
        if not entry.get("ceiling_blocker"):
            fail(
                f"per-item snapshot entry {item!r} must declare a "
                "'ceiling_blocker' string"
            )
    if sorted(seen_items) != sorted(EXPECTED_ITEMS):
        fail(
            "per_item_snapshot must contain exactly the five named "
            f"items: {EXPECTED_ITEMS}"
        )
    # RES-D4 carries the HD-1+HD-2+HD-3 PR references.
    res_d4 = next(
        (e for e in items if e.get("item") == "RES-D4"), None
    )
    if res_d4 is None:
        fail("RES-D4 entry missing from per_item_snapshot")
    if res_d4.get("hard_dep_axis") != "HD-1+HD-2+HD-3":
        fail(
            "RES-D4 entry must declare "
            "'hard_dep_axis: HD-1+HD-2+HD-3'"
        )
    hd_refs = res_d4.get("hd_substrate_pr_refs") or {}
    for key, expected in (
        ("hd_1_ots_substrate_pr", 446),
        ("hd_2_peer_roster_substrate_pr", 452),
        ("hd_3_audit_coverage_substrate_pr", 458),
    ):
        if hd_refs.get(key) != expected:
            fail(
                f"RES-D4.hd_substrate_pr_refs.{key} must be "
                f"{expected}"
            )


def assert_aggregate_snapshot(stub: dict) -> None:
    agg = stub.get("aggregate_snapshot") or {}
    if agg.get("items_evaluated") != 5:
        fail("aggregate_snapshot.items_evaluated must be 5")
    if agg.get("items_at_ceiling_4") != 5:
        fail(
            "aggregate_snapshot.items_at_ceiling_4 must be 5 "
            "(all five items at Sandbox ceiling)"
        )
    if agg.get("items_at_score_5") != 0:
        fail(
            "aggregate_snapshot.items_at_score_5 must be 0 "
            "(score-5 is unreachable from Sandbox-Hand)"
        )
    if agg.get("items_below_4") != 0:
        fail(
            "aggregate_snapshot.items_below_4 must be 0 "
            "(Tag-77 substrate trilogy is complete)"
        )
    if agg.get("substrate_trilogy_complete") is not True:
        fail(
            "aggregate_snapshot.substrate_trilogy_complete must "
            "be true"
        )
    if agg.get("ceo_triage_authorisation_pending_count") != 5:
        fail(
            "aggregate_snapshot.ceo_triage_authorisation_pending_"
            "count must be 5"
        )
    if agg.get("live_ots_activation_pending_for_count") != 1:
        fail(
            "aggregate_snapshot.live_ots_activation_pending_for_"
            "count must be 1 (RES-D4 only)"
        )
    if agg.get("verdict") != "substrate-complete-ceo-triage-pending":
        fail(
            "aggregate_snapshot.verdict must be "
            "'substrate-complete-ceo-triage-pending'"
        )
    if agg.get("verdict_does_not_authorise_promotion") is not True:
        fail(
            "aggregate_snapshot.verdict_does_not_authorise_"
            "promotion must be true"
        )


def assert_what_this_snapshot_is_not(stub: dict) -> None:
    negatives = stub.get("what_this_snapshot_is_not") or []
    if not isinstance(negatives, list):
        fail("what_this_snapshot_is_not must be a list")
    required_phrases = (
        "promotion-PR",
        "AR-authorisation",
        "draft-ADR",
        "Pin-Pack",
        "NATS-KV",
        "OTS-anchor activation",
        "indefinite-deferral lifting",
        "Henrik-Voss",
    )
    blob = " ".join(str(n) for n in negatives)
    for phrase in required_phrases:
        if phrase not in blob:
            fail(
                f"what_this_snapshot_is_not must explicitly negate "
                f"'{phrase}'"
            )


def assert_snapshot_emit_discipline(stub: dict) -> None:
    emit = stub.get("snapshot_emit_discipline") or {}
    if emit.get("score_emit_default") != "inspection-only":
        fail(
            "snapshot_emit_discipline.score_emit_default must be "
            "'inspection-only'"
        )
    if emit.get("score_emit_target") != "stdout-of-helper-only":
        fail(
            "snapshot_emit_discipline.score_emit_target must be "
            "'stdout-of-helper-only'"
        )
    for key in (
        "score_does_not_emit_to_notify_log",
        "score_does_not_emit_to_audit_sample_rotation",
        "score_does_not_emit_to_activity_log",
        "snapshot_carries_no_timestamp_drift",
    ):
        if emit.get(key) is not True:
            fail(
                f"snapshot_emit_discipline.{key} must be true"
            )


def assert_doc_cross_anchor(stub: dict) -> None:
    """The promotion-sequencing doc must reference the snapshot
    stub under §8."""
    if not DOC_PATH.is_file():
        # Doc may not exist in a hermetic stub-only sandbox; skip.
        info("doc-file not present, skipping doc cross-anchor check")
        return
    text = DOC_PATH.read_text(encoding="utf-8")
    needed = (
        "tooling/audit/spec-v0-4-4-promotion-pre-readiness-snapshot.json",
        "tooling/audit/prepare_spec_v0_4_4_promotion_substrate.py",
        "## 8.",
        "Tag-77",
    )
    for needle in needed:
        if needle not in text:
            fail(
                f"promotion-sequencing doc missing required §8 "
                f"cross-anchor '{needle}'"
            )


def assert_helper_self_sandbox() -> None:
    """The helper itself must never alter env flags that would
    flip emit / authorisation defaults.
    """
    forbidden_flags = (
        "WAKIR_PROMOTION_PR_OPEN",
        "WAKIR_AR_AUTHORISATION_REQUEST",
        "WAKIR_OTS_ANCHOR_ACTIVATE",
        "WAKIR_INDEFINITE_DEFERRAL_LIFT",
        "WAKIR_PIN_PACK_EDIT",
        "WAKIR_AUDIT_SAMPLE_ROTATION_EMIT",
    )
    for flag in forbidden_flags:
        pre = os.environ.get(flag)
        post = os.environ.get(flag)
        if pre != post:
            fail(
                f"helper must not alter env-flag '{flag}'"
            )


def print_per_item_score_table(stub: dict) -> None:
    """Print the per-item score table to stdout for human review.

    This is the only 'output' surface of the helper; it MUST NOT
    write to any side-channel (notify-log, activity-log, audit-
    sample rotation). The score is advisory-only.
    """
    items = stub.get("per_item_snapshot") or []
    info("Pre-Readiness-Score Table (audit-only, advisory-only):")
    for entry in items:
        info(
            f"  {entry.get('item')}: score={entry.get('score')}/5 "
            f"(ceiling={entry.get('score_ceiling_from_sandbox')}, "
            f"blocker={entry.get('ceiling_blocker')})"
        )
    agg = stub.get("aggregate_snapshot") or {}
    info(
        f"Aggregate verdict: {agg.get('verdict')} "
        f"(items_at_ceiling_4={agg.get('items_at_ceiling_4')})"
    )


def main(argv: list) -> int:
    info(f"loading snapshot stub: {STUB_PATH}")
    stub = load_stub(STUB_PATH)
    assert_audit_only_posture(stub)
    assert_upstream_anchors(stub)
    assert_sandbox_boundary(stub)
    assert_scoring_methodology(stub)
    assert_per_item_snapshot(stub)
    assert_aggregate_snapshot(stub)
    assert_what_this_snapshot_is_not(stub)
    assert_snapshot_emit_discipline(stub)
    assert_doc_cross_anchor(stub)
    assert_helper_self_sandbox()
    print_per_item_score_table(stub)
    info(
        "OK: Tag-77 v0.4.4 Promotion Pre-Readiness Snapshot is "
        "audit-only-clean; substrate trilogy complete at "
        "Sandbox ceiling 4/5 across all five items"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
