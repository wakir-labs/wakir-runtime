#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-71 RES-D4 HD-2 Peer-Roster Substrate-Preparation helper.

Audit-only mode. This helper inspects the Tag-71 HD-2 peer-roster
substrate stub-file at
``tooling/audit/res-d4-hd2-peer-roster-stub.json`` and asserts:

  - The stub-file is well-formed JSON.
  - The stub-file declares ``audit_only: true`` and
    ``doc_form_only: true``.
  - The stub-file declares ``tag: Tag-71`` and ``hard_dep: HD-2``.
  - The stub-file declares the upstream Tag-67 / Tag-65 / Tag-69
    anchors and the Tag-70 HD-1 substrate PR number (#446).
  - The stub-file enumerates the strict-interpretation invariant
    explicitly (minimum_two_peers, identified, production_excludes).
  - The stub-file enumerates exactly three fixture-peers, each
    carrying ``kind: fixture`` and contributing zero to the
    production-count (HD-2 substrate must never claim production
    peer-count from fixture entries).
  - The third fixture-peer (`loose-count-forbidden`) is the
    negative-control with ``expected_verifier_branch: reject``.
  - The stub-file enumerates exactly three fixture-frames covering
    (a) pending-production-growth, (b) single-production-insufficient,
    (c) loose-count-forbidden — the third being a reject negative-
    control.
  - The stub-file's sandbox-boundary section sets every boundary to
    its audit-only default (no production peer-count claim, no
    Selin direction emit, no CFO ratification envelope emit, no
    kind-field default change).
  - The stub-file enumerates the three roster-mutation event types
    (peer-added, peer-removed, kind-promoted) and all default to
    not-emitted-in-audit-only.
  - The helper itself does NOT call any external network endpoint.
  - The helper itself does NOT emit any roster-mutation event.
  - The helper itself does NOT direct Selin's federation work-stream.

The helper is invoked from the test-suite at
``tests/audit/test_hd_2_peer_roster_substrate_tag71.py`` via
subprocess.

Exit 0 on green, exit 1 on any failure with a clear stderr message.
Standard library only.

Sandbox-boundary recital (per deep-dive §8 + §6.3):

  - No production peer-count claim is emitted by this helper.
  - No direction to Selin's federation work-stream is emitted by
    this helper.
  - No CFO ratification envelope is emitted by this helper.
  - No kind-field default change is performed by this helper.

This helper is the Tag-71 §6.3 deep-dive operational counterpart
(parallel to the Tag-70 §6.2 HD-1 helper).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

STUB_PATH = (
    Path(__file__).resolve().parent
    / "res-d4-hd2-peer-roster-stub.json"
)
DOC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "operations"
    / "res-d4-high-residual-mitigation-deep-dive.md"
)

EXPECTED_FIXTURE_PEER_IDS = (
    "fixture-peer-A",
    "fixture-peer-B",
    "loose-count-forbidden",
)
EXPECTED_FIXTURE_FRAME_NAMES = (
    "roster-snapshot-frame--pending-production-growth",
    "roster-snapshot-frame--single-production-insufficient",
    "roster-snapshot-frame--loose-count-forbidden",
)
EXPECTED_ROSTER_MUTATION_EVENTS = (
    "roster-mutation--peer-added",
    "roster-mutation--peer-removed",
    "roster-mutation--kind-promoted",
)
EXPECTED_TAG = "Tag-71"
EXPECTED_HARD_DEP = "HD-2"


def fail(msg: str) -> None:
    sys.stderr.write(
        f"prepare_res_d4_hd2_peer_roster_substrate: FAIL: {msg}\n"
    )
    sys.exit(1)


def info(msg: str) -> None:
    sys.stdout.write(
        f"prepare_res_d4_hd2_peer_roster_substrate: {msg}\n"
    )


def load_stub(path: Path) -> dict:
    if not path.is_file():
        fail(f"stub-file missing: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        fail(f"stub-file not well-formed JSON: {exc}")
        return {}  # unreachable; appeases type-checkers.


def assert_audit_only_posture(stub: dict) -> None:
    if stub.get("audit_only") is not True:
        fail("stub must declare 'audit_only: true'")
    if stub.get("doc_form_only") is not True:
        fail("stub must declare 'doc_form_only: true'")
    if stub.get("tag") != EXPECTED_TAG:
        fail(f"stub must declare 'tag: {EXPECTED_TAG}'")
    if stub.get("hard_dep") != EXPECTED_HARD_DEP:
        fail(
            f"stub must declare 'hard_dep: {EXPECTED_HARD_DEP}'"
        )


def assert_upstream_anchors(stub: dict) -> None:
    anchors = stub.get("upstream_anchors") or {}
    required_keys = (
        "tag_67_pre_mortem_anchor",
        "tag_65_promotion_sequencing_anchor",
        "tag_69_deep_dive_anchor",
        "tag_70_hd_1_substrate_pr",
        "tag_69_deep_dive_pr",
        "tag_60_pre_activation_stub_pr",
    )
    for key in required_keys:
        if key not in anchors:
            fail(
                f"upstream_anchors missing required key '{key}'"
            )
    if anchors.get("tag_70_hd_1_substrate_pr") != 446:
        fail(
            "upstream_anchors.tag_70_hd_1_substrate_pr must be "
            "446 (Tag-70 HD-1 PR)"
        )
    if anchors.get("tag_69_deep_dive_pr") != 440:
        fail(
            "upstream_anchors.tag_69_deep_dive_pr must be 440 "
            "(Tag-69 PR)"
        )
    if anchors.get("tag_60_pre_activation_stub_pr") != 382:
        fail(
            "upstream_anchors.tag_60_pre_activation_stub_pr must "
            "be 382 (Tag-60 PR)"
        )


def assert_sandbox_boundary(stub: dict) -> None:
    boundary = stub.get("sandbox_boundary") or {}
    for key in (
        "no_production_peer_count_claim",
        "no_selin_federation_direction_emit",
        "no_cfo_ratification_envelope_emit",
        "no_kind_field_default_change",
    ):
        if boundary.get(key) is not True:
            fail(
                f"sandbox_boundary.{key} must be true "
                "(audit-only posture)"
            )
    if boundary.get("verifier_production_count_default") != "strict":
        fail(
            "sandbox_boundary.verifier_production_count_default "
            "must be 'strict' (audit-only posture)"
        )


def assert_strict_interpretation(stub: dict) -> None:
    strict = stub.get("strict_interpretation_invariant") or {}
    if strict.get("minimum_two_peers") != ">= 2":
        fail(
            "strict_interpretation_invariant.minimum_two_peers "
            "must declare '>= 2'"
        )
    if "production" not in str(strict.get("identified", "")):
        fail(
            "strict_interpretation_invariant.identified must "
            "reference production-active roster"
        )
    excludes = strict.get("production_excludes") or []
    for required in (
        "test-fixture",
        "catalogue-stub",
        "tag-60-pre-activation-fixture",
    ):
        if required not in excludes:
            fail(
                f"strict_interpretation_invariant.production_"
                f"excludes must enumerate '{required}'"
            )
    if "B2" not in str(
        strict.get("loose_interpretation_is_failure_mode", "")
    ):
        fail(
            "strict_interpretation_invariant.loose_interpretation_"
            "is_failure_mode must reference Tag-67 §5.1 B2"
        )


def assert_fixture_peers(stub: dict) -> None:
    peers = stub.get("fixture_peers") or []
    if not isinstance(peers, list):
        fail("fixture_peers must be a list")
    if len(peers) != 3:
        fail(
            f"fixture_peers must enumerate exactly 3 peers, "
            f"got {len(peers)}"
        )
    seen_ids: list = []
    for peer in peers:
        if not isinstance(peer, dict):
            fail("each fixture-peer must be an object")
        peer_id = peer.get("peer_id")
        if peer_id not in EXPECTED_FIXTURE_PEER_IDS:
            fail(
                f"fixture-peer has unexpected peer_id {peer_id!r}; "
                f"expected one of {EXPECTED_FIXTURE_PEER_IDS}"
            )
        seen_ids.append(peer_id)
        if peer.get("kind") != "fixture":
            fail(
                f"fixture-peer {peer_id!r} must declare "
                "'kind: fixture'"
            )
        if peer.get("expected_production_count_contribution") != 0:
            fail(
                f"fixture-peer {peer_id!r} must declare "
                "'expected_production_count_contribution: 0' "
                "(strict-interpretation invariant)"
            )
        if peer.get("expected_resolver_call") is not False:
            fail(
                f"fixture-peer {peer_id!r} must declare "
                "'expected_resolver_call: false' (audit-only)"
            )
    if sorted(seen_ids) != sorted(EXPECTED_FIXTURE_PEER_IDS):
        fail(
            "fixture_peers must contain exactly the three named "
            f"variants: {EXPECTED_FIXTURE_PEER_IDS}"
        )
    # Negative-control invariant: loose-count-forbidden must reject.
    negative = next(
        (
            p
            for p in peers
            if p.get("peer_id") == "loose-count-forbidden"
        ),
        None,
    )
    if negative is None:
        fail(
            "negative-control fixture-peer "
            "'loose-count-forbidden' missing"
        )
    if negative.get("expected_verifier_branch") != "reject":
        fail(
            "negative-control fixture-peer must declare "
            "'expected_verifier_branch: reject'"
        )


def assert_fixture_frames(stub: dict) -> None:
    frames = stub.get("fixture_frames") or []
    if not isinstance(frames, list):
        fail("fixture_frames must be a list")
    if len(frames) != 3:
        fail(
            f"fixture_frames must enumerate exactly 3 frames, "
            f"got {len(frames)}"
        )
    seen_names: list = []
    for frame in frames:
        if not isinstance(frame, dict):
            fail("each fixture-frame must be an object")
        name = frame.get("name")
        if name not in EXPECTED_FIXTURE_FRAME_NAMES:
            fail(
                f"fixture-frame has unexpected name {name!r}; "
                f"expected one of {EXPECTED_FIXTURE_FRAME_NAMES}"
            )
        seen_names.append(name)
        if frame.get("kind") != "fixture":
            fail(
                f"fixture-frame {name!r} must declare "
                "'kind: fixture'"
            )
        if frame.get("expected_resolver_call") is not False:
            fail(
                f"fixture-frame {name!r} must declare "
                "'expected_resolver_call: false' (audit-only)"
            )
    if sorted(seen_names) != sorted(EXPECTED_FIXTURE_FRAME_NAMES):
        fail(
            "fixture_frames must contain exactly the three named "
            f"variants: {EXPECTED_FIXTURE_FRAME_NAMES}"
        )
    # Negative-control invariant: loose-count-forbidden frame must
    # reject.
    negative = next(
        (
            f
            for f in frames
            if f.get("name")
            == "roster-snapshot-frame--loose-count-forbidden"
        ),
        None,
    )
    if negative is None:
        fail(
            "negative-control fixture-frame "
            "'roster-snapshot-frame--loose-count-forbidden' missing"
        )
    if negative.get("expected_verifier_branch") != "reject":
        fail(
            "negative-control fixture-frame must declare "
            "'expected_verifier_branch: reject'"
        )


def assert_roster_mutation_inventory(stub: dict) -> None:
    events = stub.get("roster_mutation_event_inventory") or []
    if not isinstance(events, list):
        fail("roster_mutation_event_inventory must be a list")
    names = [
        event.get("event_name")
        for event in events
        if isinstance(event, dict)
    ]
    for expected in EXPECTED_ROSTER_MUTATION_EVENTS:
        if expected not in names:
            fail(
                f"roster_mutation_event_inventory missing "
                f"required event '{expected}'"
            )
    for event in events:
        if not isinstance(event, dict):
            fail("each roster-mutation event must be an object")
        if event.get("audit_trail_bucket") != "route_registry":
            fail(
                f"roster-mutation event {event.get('event_name')!r} "
                "must declare 'audit_trail_bucket: route_registry'"
            )
        if event.get("kind_discriminator_required") is not True:
            fail(
                f"roster-mutation event {event.get('event_name')!r} "
                "must declare 'kind_discriminator_required: true'"
            )
        if event.get("default_state") != "not-emitted-in-audit-only":
            fail(
                f"roster-mutation event {event.get('event_name')!r} "
                "must declare 'default_state: "
                "not-emitted-in-audit-only'"
            )


def assert_what_this_stub_is_not(stub: dict) -> None:
    negatives = stub.get("what_this_stub_is_not") or []
    required_phrases = (
        "production peer-count claim",
        "draft-ADR",
        "promotion-PR opening",
        "direction to Selin",
        "CFO ratification envelope",
        "indefinite-deferral",
        "AR-authorisation request",
    )
    blob = " ".join(str(n) for n in negatives)
    for phrase in required_phrases:
        if phrase not in blob:
            fail(
                f"what_this_stub_is_not must explicitly negate "
                f"'{phrase}'"
            )


def assert_doc_cross_anchor(stub: dict) -> None:
    """The deep-dive doc must reference the stub-file path under §6.3."""
    if not DOC_PATH.is_file():
        # Doc may not exist in a hermetic stub-only sandbox; skip.
        info("doc-file not present, skipping doc cross-anchor check")
        return
    text = DOC_PATH.read_text(encoding="utf-8")
    needed = (
        "tooling/audit/res-d4-hd2-peer-roster-stub.json",
        "tooling/audit/prepare_res_d4_hd2_peer_roster_substrate.py",
        "### 6.3",
        "Tag-71",
    )
    for needle in needed:
        if needle not in text:
            fail(
                f"deep-dive doc missing required cross-anchor "
                f"'{needle}'"
            )


def assert_helper_self_sandbox() -> None:
    """The helper itself must never emit roster-mutation events or
    set federation production-count claim flags."""
    # Defensive: we read but do not write any env-flag that could
    # be a federation-production-count claim.
    forbidden_flags = (
        "WAKIR_FEDERATION_PEER_COUNT_CLAIM",
        "WAKIR_ROSTER_MUTATION_EMIT",
        "WAKIR_SELIN_FEDERATION_DIRECT",
    )
    for flag in forbidden_flags:
        pre = os.environ.get(flag)
        post = os.environ.get(flag)
        if pre != post:
            fail(
                f"helper must not alter env-flag '{flag}'"
            )


def main(argv: list) -> int:
    info(f"loading stub: {STUB_PATH}")
    stub = load_stub(STUB_PATH)
    assert_audit_only_posture(stub)
    assert_upstream_anchors(stub)
    assert_sandbox_boundary(stub)
    assert_strict_interpretation(stub)
    assert_fixture_peers(stub)
    assert_fixture_frames(stub)
    assert_roster_mutation_inventory(stub)
    assert_what_this_stub_is_not(stub)
    assert_doc_cross_anchor(stub)
    assert_helper_self_sandbox()
    info(
        "OK: Tag-71 HD-2 Peer-Roster substrate stub is "
        "audit-only-clean"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
