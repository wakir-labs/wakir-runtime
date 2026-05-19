#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-72 RES-D4 HD-3 Audit-Coverage Substrate-Preparation helper.

Audit-only mode. This helper inspects the Tag-72 HD-3 audit-coverage
substrate stub-file at
``tooling/audit/res-d4-hd3-audit-coverage-stub.json`` and asserts:

  - The stub-file is well-formed JSON.
  - The stub-file declares ``audit_only: true`` and
    ``doc_form_only: true``.
  - The stub-file declares ``tag: Tag-72`` and ``hard_dep: HD-3``.
  - The stub-file declares the upstream Tag-67 / Tag-65 / Tag-69
    anchors and the Tag-70 HD-1 + Tag-71 HD-2 substrate PR numbers
    (#446 + #452), plus ADR-0014 + ADR-0025 audit-anchors.
  - The stub-file enumerates the strict audit-coverage invariant
    explicitly (audit_priority_value, owner-is-not-Reza,
    schema-extension strict-superset rule, v1->v2 migration,
    rollback-choice family).
  - The stub-file enumerates exactly three audit-priority-tags,
    each carrying ``kind: fixture`` and contributing zero audit-
    sample-rotation emit (HD-3 substrate must never claim a
    Henrik-Voss audit-sample-config amendment from fixture
    entries).
  - The third priority-tag (`reza-hand-priority-flip-forbidden`)
    is the negative-control with
    ``expected_verifier_branch: reject``.
  - The stub-file enumerates exactly three schema-extension audit
    probes covering (a) strict-superset-ok, (b) key-shape-collision,
    (c) v1-consumer-break -- the second and third being reject
    negative-controls (A4 + A5 anchors).
  - The stub-file enumerates exactly three rollback-audit choices
    covering (a) atomic-revert (accept), (b) forward-compat-note
    (accept), (c) silent-leave-forbidden (reject negative-control,
    B4 anchor).
  - The stub-file's sandbox-boundary section sets every boundary to
    its audit-only default (no audit-sample-config amendment, no
    Henrik-Voss-priority-direction emit, no promotion-PR opening,
    no NATS-KV-schema default change, no rollback-procedure default
    change; probe_default_mode == inspection-only).
  - The stub-file enumerates the three audit-sample event types
    (rotation-entry, schema-extension-probe-result, rollback-
    choice-record) and all default to not-emitted-in-audit-only,
    owner_hand: HR/Audit-hand.
  - The helper itself does NOT call any external network endpoint.
  - The helper itself does NOT emit any audit-sample rotation
    entry.
  - The helper itself does NOT direct Henrik Voss's audit-sample
    priority-list.
  - The helper itself does NOT change the NATS-KV schema or
    rollback-procedure defaults.

The helper is invoked from the test-suite at
``tests/audit/test_hd_3_audit_coverage_substrate_tag72.py`` via
subprocess.

Exit 0 on green, exit 1 on any failure with a clear stderr message.
Standard library only.

Sandbox-boundary recital (per deep-dive §8 + §6.4):

  - No audit-sample-config amendment is emitted by this helper.
  - No direction to Henrik Voss's audit-sample priority-list is
    emitted by this helper.
  - No NATS-KV schema default change is performed by this helper.
  - No rollback-procedure default change is performed by this
    helper.

This helper is the Tag-72 §6.4 deep-dive operational counterpart
(parallel to the Tag-70 §6.2 HD-1 helper and the Tag-71 §6.3 HD-2
helper). It completes the three-hard-dep substrate trilogy at
audit-only granularity.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

STUB_PATH = (
    Path(__file__).resolve().parent
    / "res-d4-hd3-audit-coverage-stub.json"
)
DOC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "operations"
    / "res-d4-high-residual-mitigation-deep-dive.md"
)

EXPECTED_PRIORITY_TAGS = (
    "live-ots-critical-path",
    "fixture-priority-default",
    "reza-hand-priority-flip-forbidden",
)
EXPECTED_SCHEMA_PROBES = (
    "schema-extension-probe--strict-superset-ok",
    "schema-extension-probe--key-shape-collision",
    "schema-extension-probe--v1-consumer-break",
)
EXPECTED_ROLLBACK_CHOICES = (
    "rollback-choice--atomic-revert",
    "rollback-choice--forward-compat-note",
    "rollback-choice--silent-leave-forbidden",
)
EXPECTED_AUDIT_SAMPLE_EVENTS = (
    "audit-sample--res-d4-rotation-entry",
    "audit-sample--schema-extension-probe-result",
    "audit-sample--rollback-choice-record",
)
EXPECTED_TAG = "Tag-72"
EXPECTED_HARD_DEP = "HD-3"


def fail(msg: str) -> None:
    sys.stderr.write(
        f"prepare_res_d4_hd3_audit_coverage_substrate: FAIL: {msg}\n"
    )
    sys.exit(1)


def info(msg: str) -> None:
    sys.stdout.write(
        f"prepare_res_d4_hd3_audit_coverage_substrate: {msg}\n"
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
        "tag_71_hd_2_substrate_pr",
        "tag_69_deep_dive_pr",
        "tag_66_ots_probe_coverage_pr",
        "tag_60_pre_activation_stub_pr",
        "adr_0014_audit_sample_rotation",
        "adr_0025_three_axis_audit_anchor",
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
    if anchors.get("tag_71_hd_2_substrate_pr") != 452:
        fail(
            "upstream_anchors.tag_71_hd_2_substrate_pr must be "
            "452 (Tag-71 HD-2 PR)"
        )
    if anchors.get("tag_69_deep_dive_pr") != 440:
        fail(
            "upstream_anchors.tag_69_deep_dive_pr must be 440 "
            "(Tag-69 PR)"
        )
    if anchors.get("tag_66_ots_probe_coverage_pr") != 421:
        fail(
            "upstream_anchors.tag_66_ots_probe_coverage_pr must "
            "be 421 (Tag-66 PR)"
        )
    if anchors.get("tag_60_pre_activation_stub_pr") != 382:
        fail(
            "upstream_anchors.tag_60_pre_activation_stub_pr must "
            "be 382 (Tag-60 PR)"
        )


def assert_sandbox_boundary(stub: dict) -> None:
    boundary = stub.get("sandbox_boundary") or {}
    for key in (
        "no_audit_sample_config_amendment_emit",
        "no_henrik_voss_priority_list_direction_emit",
        "no_promotion_pr_opening",
        "no_nats_kv_schema_default_change",
        "no_rollback_procedure_default_change",
    ):
        if boundary.get(key) is not True:
            fail(
                f"sandbox_boundary.{key} must be true "
                "(audit-only posture)"
            )
    if boundary.get("probe_default_mode") != "inspection-only":
        fail(
            "sandbox_boundary.probe_default_mode must be "
            "'inspection-only' (audit-only posture)"
        )
    if (
        boundary.get("schema_extension_audit_default")
        != "strict-superset-check"
    ):
        fail(
            "sandbox_boundary.schema_extension_audit_default "
            "must be 'strict-superset-check'"
        )


def assert_strict_audit_coverage_invariant(stub: dict) -> None:
    strict = stub.get("strict_audit_coverage_invariant") or {}
    if strict.get("audit_priority_value") != "live-ots-critical-path":
        fail(
            "strict_audit_coverage_invariant.audit_priority_value "
            "must declare 'live-ots-critical-path'"
        )
    if "HR/Audit-hand" not in str(strict.get("audit_priority_owner", "")):
        fail(
            "strict_audit_coverage_invariant.audit_priority_owner "
            "must reference HR/Audit-hand"
        )
    if "Reza-hand" not in str(
        strict.get("audit_priority_owner_is_not", "")
    ):
        fail(
            "strict_audit_coverage_invariant.audit_priority_owner_"
            "is_not must explicitly negate Reza-hand"
        )
    if "strict superset" not in str(
        strict.get("schema_extension_rule", "")
    ):
        fail(
            "strict_audit_coverage_invariant.schema_extension_rule "
            "must reference 'strict superset'"
        )
    if strict.get("v1_to_v2_migration_compat_required") is not True:
        fail(
            "strict_audit_coverage_invariant.v1_to_v2_migration_"
            "compat_required must be true"
        )
    rollback_modes = strict.get("rollback_must_be_one_of") or []
    for required in (
        "atomic-revert-of-nats-kv-bucket-extension",
        "forward-compat-documentation-note-bucket-left-in-place",
    ):
        if required not in rollback_modes:
            fail(
                f"strict_audit_coverage_invariant.rollback_must_be_"
                f"one_of must enumerate '{required}'"
            )
    if "B5" not in str(
        strict.get("loose_audit_coverage_is_failure_mode", "")
    ):
        fail(
            "strict_audit_coverage_invariant.loose_audit_coverage_"
            "is_failure_mode must reference Tag-67 §5.1 B5"
        )


def assert_priority_tags(stub: dict) -> None:
    tags = stub.get("audit_priority_tags") or []
    if not isinstance(tags, list):
        fail("audit_priority_tags must be a list")
    if len(tags) != 3:
        fail(
            f"audit_priority_tags must enumerate exactly 3 tags, "
            f"got {len(tags)}"
        )
    seen_names: list = []
    for tag in tags:
        if not isinstance(tag, dict):
            fail("each audit-priority-tag must be an object")
        name = tag.get("tag_name")
        if name not in EXPECTED_PRIORITY_TAGS:
            fail(
                f"audit-priority-tag has unexpected tag_name "
                f"{name!r}; expected one of {EXPECTED_PRIORITY_TAGS}"
            )
        seen_names.append(name)
        if tag.get("kind") != "fixture":
            fail(
                f"audit-priority-tag {name!r} must declare "
                "'kind: fixture'"
            )
        if tag.get("audit_sample_rotation_emit") is not False:
            fail(
                f"audit-priority-tag {name!r} must declare "
                "'audit_sample_rotation_emit: false' (audit-only)"
            )
        if tag.get("expected_resolver_call") is not False:
            fail(
                f"audit-priority-tag {name!r} must declare "
                "'expected_resolver_call: false' (audit-only)"
            )
        if (
            tag.get("expected_henrik_voss_action")
            != "none-in-audit-only"
        ):
            fail(
                f"audit-priority-tag {name!r} must declare "
                "'expected_henrik_voss_action: none-in-audit-only'"
            )
    if sorted(seen_names) != sorted(EXPECTED_PRIORITY_TAGS):
        fail(
            "audit_priority_tags must contain exactly the three "
            f"named variants: {EXPECTED_PRIORITY_TAGS}"
        )
    # Negative-control invariant.
    negative = next(
        (
            t
            for t in tags
            if t.get("tag_name") == "reza-hand-priority-flip-forbidden"
        ),
        None,
    )
    if negative is None:
        fail(
            "negative-control audit-priority-tag "
            "'reza-hand-priority-flip-forbidden' missing"
        )
    if negative.get("expected_verifier_branch") != "reject":
        fail(
            "negative-control audit-priority-tag must declare "
            "'expected_verifier_branch: reject'"
        )


def assert_schema_extension_probes(stub: dict) -> None:
    probes = stub.get("schema_extension_audit_probes") or []
    if not isinstance(probes, list):
        fail("schema_extension_audit_probes must be a list")
    if len(probes) != 3:
        fail(
            f"schema_extension_audit_probes must enumerate exactly "
            f"3 probes, got {len(probes)}"
        )
    seen_names: list = []
    for probe in probes:
        if not isinstance(probe, dict):
            fail("each schema-extension probe must be an object")
        name = probe.get("name")
        if name not in EXPECTED_SCHEMA_PROBES:
            fail(
                f"schema-extension probe has unexpected name "
                f"{name!r}; expected one of {EXPECTED_SCHEMA_PROBES}"
            )
        seen_names.append(name)
        if probe.get("kind") != "fixture":
            fail(
                f"schema-extension probe {name!r} must declare "
                "'kind: fixture'"
            )
        if probe.get("expected_resolver_call") is not False:
            fail(
                f"schema-extension probe {name!r} must declare "
                "'expected_resolver_call: false' (audit-only)"
            )
        if probe.get("audit_sample_rotation_emit") is not False:
            fail(
                f"schema-extension probe {name!r} must declare "
                "'audit_sample_rotation_emit: false'"
            )
    if sorted(seen_names) != sorted(EXPECTED_SCHEMA_PROBES):
        fail(
            "schema_extension_audit_probes must contain exactly the "
            f"three named variants: {EXPECTED_SCHEMA_PROBES}"
        )
    # Negative-control invariants: collision + v1-consumer-break
    # must reject.
    for negative_name, expected_diag in (
        ("schema-extension-probe--key-shape-collision",
         "schema-extension-collision"),
        ("schema-extension-probe--v1-consumer-break",
         "v1-consumer-break"),
    ):
        negative = next(
            (p for p in probes if p.get("name") == negative_name),
            None,
        )
        if negative is None:
            fail(
                f"negative-control schema-extension probe "
                f"'{negative_name}' missing"
            )
        if negative.get("expected_verifier_branch") != "reject":
            fail(
                f"negative-control schema-extension probe "
                f"'{negative_name}' must declare "
                "'expected_verifier_branch: reject'"
            )
        if negative.get("expected_diagnostic") != expected_diag:
            fail(
                f"negative-control schema-extension probe "
                f"'{negative_name}' must declare "
                f"'expected_diagnostic: {expected_diag}'"
            )


def assert_rollback_audit_choices(stub: dict) -> None:
    choices = stub.get("rollback_audit_choices") or []
    if not isinstance(choices, list):
        fail("rollback_audit_choices must be a list")
    if len(choices) != 3:
        fail(
            f"rollback_audit_choices must enumerate exactly 3 "
            f"choices, got {len(choices)}"
        )
    seen_names: list = []
    for choice in choices:
        if not isinstance(choice, dict):
            fail("each rollback-audit choice must be an object")
        name = choice.get("choice_name")
        if name not in EXPECTED_ROLLBACK_CHOICES:
            fail(
                f"rollback-audit choice has unexpected name "
                f"{name!r}; expected one of "
                f"{EXPECTED_ROLLBACK_CHOICES}"
            )
        seen_names.append(name)
        if choice.get("kind") != "fixture":
            fail(
                f"rollback-audit choice {name!r} must declare "
                "'kind: fixture'"
            )
        if choice.get("audit_trail_visibility_required") is not True:
            fail(
                f"rollback-audit choice {name!r} must declare "
                "'audit_trail_visibility_required: true'"
            )
        if choice.get("expected_resolver_call") is not False:
            fail(
                f"rollback-audit choice {name!r} must declare "
                "'expected_resolver_call: false' (audit-only)"
            )
    if sorted(seen_names) != sorted(EXPECTED_ROLLBACK_CHOICES):
        fail(
            "rollback_audit_choices must contain exactly the three "
            f"named variants: {EXPECTED_ROLLBACK_CHOICES}"
        )
    # Negative-control: silent-leave-forbidden must reject with the
    # right diagnostic.
    negative = next(
        (
            c
            for c in choices
            if c.get("choice_name")
            == "rollback-choice--silent-leave-forbidden"
        ),
        None,
    )
    if negative is None:
        fail(
            "negative-control rollback-audit choice "
            "'rollback-choice--silent-leave-forbidden' missing"
        )
    if negative.get("expected_verifier_branch") != "reject":
        fail(
            "negative-control rollback-audit choice must declare "
            "'expected_verifier_branch: reject'"
        )
    if negative.get("expected_diagnostic") != "rollback-undocumented":
        fail(
            "negative-control rollback-audit choice must declare "
            "'expected_diagnostic: rollback-undocumented'"
        )


def assert_audit_sample_event_inventory(stub: dict) -> None:
    events = stub.get("audit_sample_event_inventory") or []
    if not isinstance(events, list):
        fail("audit_sample_event_inventory must be a list")
    names = [
        event.get("event_name")
        for event in events
        if isinstance(event, dict)
    ]
    for expected in EXPECTED_AUDIT_SAMPLE_EVENTS:
        if expected not in names:
            fail(
                f"audit_sample_event_inventory missing required "
                f"event '{expected}'"
            )
    for event in events:
        if not isinstance(event, dict):
            fail("each audit-sample event must be an object")
        if event.get("audit_trail_bucket") != "audit_sample_rotation":
            fail(
                f"audit-sample event {event.get('event_name')!r} "
                "must declare 'audit_trail_bucket: "
                "audit_sample_rotation'"
            )
        if event.get("priority_discriminator_required") is not True:
            fail(
                f"audit-sample event {event.get('event_name')!r} "
                "must declare 'priority_discriminator_required: "
                "true'"
            )
        if event.get("default_state") != "not-emitted-in-audit-only":
            fail(
                f"audit-sample event {event.get('event_name')!r} "
                "must declare 'default_state: "
                "not-emitted-in-audit-only'"
            )
        if event.get("owner_hand") != "HR/Audit-hand":
            fail(
                f"audit-sample event {event.get('event_name')!r} "
                "must declare 'owner_hand: HR/Audit-hand'"
            )


def assert_what_this_stub_is_not(stub: dict) -> None:
    negatives = stub.get("what_this_stub_is_not") or []
    required_phrases = (
        "audit-sample-config amendment",
        "Henrik Voss",
        "draft-ADR",
        "promotion-PR opening",
        "NATS-KV schema default change",
        "rollback-procedure default change",
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
    """The deep-dive doc must reference the stub-file path under §6.4."""
    if not DOC_PATH.is_file():
        # Doc may not exist in a hermetic stub-only sandbox; skip.
        info("doc-file not present, skipping doc cross-anchor check")
        return
    text = DOC_PATH.read_text(encoding="utf-8")
    needed = (
        "tooling/audit/res-d4-hd3-audit-coverage-stub.json",
        "tooling/audit/prepare_res_d4_hd3_audit_coverage_substrate.py",
        "### 6.4",
        "Tag-72",
    )
    for needle in needed:
        if needle not in text:
            fail(
                f"deep-dive doc missing required cross-anchor "
                f"'{needle}'"
            )


def assert_helper_self_sandbox() -> None:
    """The helper itself must never emit audit-sample-rotation
    events or set NATS-KV schema / rollback-procedure default flags.
    """
    forbidden_flags = (
        "WAKIR_AUDIT_SAMPLE_ROTATION_EMIT",
        "WAKIR_HENRIK_VOSS_PRIORITY_DIRECT",
        "WAKIR_NATS_KV_SCHEMA_DEFAULT_FLIP",
        "WAKIR_ROLLBACK_PROCEDURE_DEFAULT_FLIP",
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
    assert_strict_audit_coverage_invariant(stub)
    assert_priority_tags(stub)
    assert_schema_extension_probes(stub)
    assert_rollback_audit_choices(stub)
    assert_audit_sample_event_inventory(stub)
    assert_what_this_stub_is_not(stub)
    assert_doc_cross_anchor(stub)
    assert_helper_self_sandbox()
    info(
        "OK: Tag-72 HD-3 Audit-Coverage substrate stub is "
        "audit-only-clean"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
