# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-72 tests for the RES-D4 HD-3 Audit-Coverage
Substrate-Preparation artifacts.
=========================================================================

Two-axis coverage (parallel to Tag-70 §6.2 and Tag-71 §6.3 test-suite
structure):

  Axis A -- Stub-file shape invariants over the live Tag-72 stub
            ``tooling/audit/res-d4-hd3-audit-coverage-stub.json``
            (skip-if-absent for portability).
  Axis B -- Helper smoke-tests via subprocess against
            ``tooling/audit/prepare_res_d4_hd3_audit_coverage_substrate.py``,
            including hermetic mutilated-stub variants in
            ``tmp_path`` for negative-control coverage.

Test inventory (>=12 hermetic, all stdlib + pytest):

  T01  Stub-file exists at the expected path.
  T02  Stub-file is well-formed JSON.
  T03  Stub-file declares ``audit_only: true`` and
       ``doc_form_only: true``.
  T04  Stub-file declares ``tag: Tag-72`` and ``hard_dep: HD-3``.
  T05  Stub-file enumerates exactly three audit-priority-tags and
       each carries ``kind: fixture`` and
       ``audit_sample_rotation_emit: false``.
  T06  Stub-file's third priority-tag is the
       reza-hand-priority-flip-forbidden negative-control with
       ``expected_verifier_branch: reject``.
  T07  Stub-file enumerates exactly three schema-extension audit
       probes covering the three probe-states defined in the
       deep-dive §6.4 catalogue.
  T08  Stub-file's collision + v1-consumer-break probes are
       reject-branch negative-controls with the correct expected
       diagnostics.
  T09  Stub-file enumerates exactly three rollback-audit choices
       (atomic-revert, forward-compat-note, silent-leave-forbidden)
       and the silent-leave variant is reject-branch.
  T10  Stub-file enumerates exactly three audit-sample events
       (rotation-entry, schema-extension-probe-result, rollback-
       choice-record) and all default to not-emitted-in-audit-only
       with owner_hand HR/Audit-hand.
  T11  Stub-file's strict-audit-coverage-invariant explicitly
       declares the audit_priority_value, owner-is-not-Reza,
       strict-superset rule, v1-to-v2 compat, rollback family,
       and cites the Tag-67 §5.1 B5 failure-mode.
  T12  Stub-file's sandbox-boundary section sets every boundary to
       its audit-only default (no audit-sample-config amendment,
       no Henrik-Voss-priority direction emit, no promotion-PR
       opening, no NATS-KV-schema default change, no rollback-
       procedure default change; probe_default_mode ==
       inspection-only; schema_extension_audit_default ==
       strict-superset-check).
  T13  Stub-file's ``what_this_stub_is_not`` section explicitly
       negates audit-sample-config amendment, Henrik Voss
       direction, draft-ADR, promotion-PR, NATS-KV schema default
       change, rollback-procedure default change, indefinite-
       deferral lifting, and AR-authorisation request.
  T14  Deep-dive doc references the stub-file path and the helper
       path under §6.4 with the Tag-72 marker.
  T15  Helper subprocess exits 0 on the live stub-file.
  T16  Helper subprocess exits non-zero when ``audit_only`` is
       flipped to ``false`` (mutilated stub).
  T17  Helper subprocess exits non-zero when the reza-hand-
       priority-flip-forbidden priority-tag is removed.
  T18  Helper subprocess exits non-zero when the
       schema-extension-probe--v1-consumer-break probe is removed.
  T19  Helper subprocess exits non-zero when the silent-leave-
       forbidden rollback choice is removed.
  T20  Helper subprocess exits non-zero when the
       res-d4-rotation-entry audit-sample event is dropped.
  T21  Sandbox-boundary invariant: stub MUST NOT enumerate any
       production-tag with an audit_sample_rotation_emit true
       value, and no probe / choice may declare
       expected_resolver_call true.
  T22  Reuse-discipline invariant: every priority-tag, every
       schema-extension probe, every rollback choice declares
       ``tag_60_compat: true``.
  T23  Cross-anchor invariant: stub upstream_anchors references
       Tag-67 + Tag-65 + Tag-69 deep-dive + Tag-70 HD-1 PR #446 +
       Tag-71 HD-2 PR #452 + Tag-69 PR #440 + Tag-66 PR #421 +
       Tag-60 PR #382 + ADR-0014 + ADR-0025.
  T24  Hand-boundary invariant: helper rejects a mutilated stub
       where the audit_priority_owner is flipped to Reza-hand
       (HR/Audit-hand ownership is load-bearing).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
STUB_REL = "tooling/audit/res-d4-hd3-audit-coverage-stub.json"
STUB_PATH = REPO_ROOT / STUB_REL
HELPER_REL = (
    "tooling/audit/prepare_res_d4_hd3_audit_coverage_substrate.py"
)
HELPER_PATH = REPO_ROOT / HELPER_REL
DOC_REL = "docs/operations/res-d4-high-residual-mitigation-deep-dive.md"
DOC_PATH = REPO_ROOT / DOC_REL

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


# --------------------------------------------------------------- #
# Stub fixtures                                                    #
# --------------------------------------------------------------- #


def _load_stub() -> dict:
    if not STUB_PATH.exists():
        pytest.skip(f"Tag-72 stub not present at {STUB_REL}")
    with STUB_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _hermetic_stub_copy(tmp_path: Path) -> Path:
    """Copy the stub into tmp_path for mutation."""
    if not STUB_PATH.exists():
        pytest.skip(f"Tag-72 stub not present at {STUB_REL}")
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
        pytest.skip(f"Tag-72 helper not present at {HELPER_REL}")
    tmp_tooling = tmp_stub.parent / "tooling" / "audit"
    tmp_tooling.mkdir(parents=True, exist_ok=True)
    helper_copy = (
        tmp_tooling
        / "prepare_res_d4_hd3_audit_coverage_substrate.py"
    )
    shutil.copy(HELPER_PATH, helper_copy)
    stub_copy = tmp_tooling / "res-d4-hd3-audit-coverage-stub.json"
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
        f"Tag-72 stub missing at {STUB_REL}"
    )


def test_t02_stub_is_well_formed_json():
    text = (
        STUB_PATH.read_text(encoding="utf-8")
        if STUB_PATH.exists()
        else None
    )
    if text is None:
        pytest.skip(f"Tag-72 stub not present at {STUB_REL}")
    json.loads(text)  # raises on malformed


def test_t03_stub_declares_audit_only_and_doc_form_only():
    stub = _load_stub()
    assert stub.get("audit_only") is True, (
        "stub must declare 'audit_only: true'"
    )
    assert stub.get("doc_form_only") is True, (
        "stub must declare 'doc_form_only: true'"
    )


def test_t04_stub_declares_tag72_and_hd_3():
    stub = _load_stub()
    assert stub.get("tag") == "Tag-72", (
        f"stub must declare 'tag: Tag-72', got {stub.get('tag')!r}"
    )
    assert stub.get("hard_dep") == "HD-3", (
        f"stub must declare 'hard_dep: HD-3', got "
        f"{stub.get('hard_dep')!r}"
    )


def test_t05_three_priority_tags_all_kind_fixture():
    stub = _load_stub()
    tags = stub.get("audit_priority_tags") or []
    assert len(tags) == 3, (
        f"audit_priority_tags must enumerate exactly 3 tags, "
        f"got {len(tags)}"
    )
    names = sorted(t.get("tag_name") for t in tags)
    assert names == sorted(EXPECTED_PRIORITY_TAGS), (
        f"audit-priority-tag names mismatch: {names!r}"
    )
    for tag in tags:
        assert tag.get("kind") == "fixture", (
            f"tag {tag.get('tag_name')!r} missing 'kind: fixture'"
        )
        assert tag.get("audit_sample_rotation_emit") is False, (
            f"tag {tag.get('tag_name')!r} must declare "
            "'audit_sample_rotation_emit: false' (audit-only)"
        )
        assert tag.get("expected_resolver_call") is False, (
            f"tag {tag.get('tag_name')!r} must declare "
            "'expected_resolver_call: false'"
        )
        assert (
            tag.get("expected_henrik_voss_action")
            == "none-in-audit-only"
        ), (
            f"tag {tag.get('tag_name')!r} must declare "
            "'expected_henrik_voss_action: none-in-audit-only'"
        )


def test_t06_negative_control_priority_tag_rejects():
    stub = _load_stub()
    tags = stub.get("audit_priority_tags") or []
    negative = next(
        (
            t
            for t in tags
            if t.get("tag_name")
            == "reza-hand-priority-flip-forbidden"
        ),
        None,
    )
    assert negative is not None, (
        "negative-control priority-tag "
        "'reza-hand-priority-flip-forbidden' missing"
    )
    assert negative.get("expected_verifier_branch") == "reject", (
        "negative-control priority-tag must declare "
        "'expected_verifier_branch: reject'"
    )


def test_t07_three_schema_extension_probes_all_kind_fixture():
    stub = _load_stub()
    probes = stub.get("schema_extension_audit_probes") or []
    assert len(probes) == 3, (
        f"schema_extension_audit_probes must enumerate exactly 3 "
        f"probes, got {len(probes)}"
    )
    names = sorted(p.get("name") for p in probes)
    assert names == sorted(EXPECTED_SCHEMA_PROBES), (
        f"schema-extension probe names mismatch: {names!r}"
    )
    for probe in probes:
        assert probe.get("kind") == "fixture", (
            f"probe {probe.get('name')!r} missing 'kind: fixture'"
        )
        assert probe.get("expected_resolver_call") is False, (
            f"probe {probe.get('name')!r} must declare "
            "'expected_resolver_call: false'"
        )


def test_t08_schema_extension_negative_controls_with_diagnostics():
    stub = _load_stub()
    probes = stub.get("schema_extension_audit_probes") or []
    for name, expected_diag in (
        ("schema-extension-probe--key-shape-collision",
         "schema-extension-collision"),
        ("schema-extension-probe--v1-consumer-break",
         "v1-consumer-break"),
    ):
        negative = next(
            (p for p in probes if p.get("name") == name),
            None,
        )
        assert negative is not None, (
            f"negative-control schema-extension probe "
            f"'{name}' missing"
        )
        assert (
            negative.get("expected_verifier_branch") == "reject"
        ), (
            f"negative-control probe '{name}' must declare "
            "'expected_verifier_branch: reject'"
        )
        assert (
            negative.get("expected_diagnostic") == expected_diag
        ), (
            f"negative-control probe '{name}' must declare "
            f"'expected_diagnostic: {expected_diag}'"
        )


def test_t09_three_rollback_choices_silent_leave_rejects():
    stub = _load_stub()
    choices = stub.get("rollback_audit_choices") or []
    assert len(choices) == 3, (
        f"rollback_audit_choices must enumerate exactly 3 "
        f"choices, got {len(choices)}"
    )
    names = sorted(c.get("choice_name") for c in choices)
    assert names == sorted(EXPECTED_ROLLBACK_CHOICES), (
        f"rollback-choice names mismatch: {names!r}"
    )
    silent = next(
        (
            c
            for c in choices
            if c.get("choice_name")
            == "rollback-choice--silent-leave-forbidden"
        ),
        None,
    )
    assert silent is not None, (
        "negative-control rollback-choice "
        "'rollback-choice--silent-leave-forbidden' missing"
    )
    assert silent.get("expected_verifier_branch") == "reject", (
        "silent-leave rollback-choice must declare "
        "'expected_verifier_branch: reject'"
    )
    assert (
        silent.get("expected_diagnostic") == "rollback-undocumented"
    ), (
        "silent-leave rollback-choice must declare "
        "'expected_diagnostic: rollback-undocumented'"
    )
    # Accept-path choices: atomic-revert + forward-compat-note both
    # require audit_trail_visibility.
    for accept_name in (
        "rollback-choice--atomic-revert",
        "rollback-choice--forward-compat-note",
    ):
        accept = next(
            (
                c
                for c in choices
                if c.get("choice_name") == accept_name
            ),
            None,
        )
        assert accept is not None, (
            f"accept-path rollback-choice '{accept_name}' missing"
        )
        assert accept.get("expected_verifier_branch") == "accept", (
            f"accept-path rollback-choice '{accept_name}' must "
            "declare 'expected_verifier_branch: accept'"
        )
        assert (
            accept.get("audit_trail_visibility_required") is True
        ), (
            f"accept-path rollback-choice '{accept_name}' must "
            "declare 'audit_trail_visibility_required: true'"
        )


def test_t10_audit_sample_event_inventory_complete():
    stub = _load_stub()
    events = stub.get("audit_sample_event_inventory") or []
    names = [e.get("event_name") for e in events]
    for expected in EXPECTED_AUDIT_SAMPLE_EVENTS:
        assert expected in names, (
            f"audit_sample_event_inventory missing required "
            f"event '{expected}'"
        )
    for event in events:
        assert (
            event.get("default_state") == "not-emitted-in-audit-only"
        ), (
            f"event {event.get('event_name')!r} must default "
            "to 'not-emitted-in-audit-only'"
        )
        assert (
            event.get("priority_discriminator_required") is True
        ), (
            f"event {event.get('event_name')!r} must require "
            "priority discriminator"
        )
        assert event.get("owner_hand") == "HR/Audit-hand", (
            f"event {event.get('event_name')!r} must declare "
            "'owner_hand: HR/Audit-hand'"
        )


def test_t11_strict_audit_coverage_invariant_explicit():
    stub = _load_stub()
    strict = stub.get("strict_audit_coverage_invariant") or {}
    assert (
        strict.get("audit_priority_value") == "live-ots-critical-path"
    ), (
        "audit_priority_value must declare 'live-ots-critical-path'"
    )
    assert "HR/Audit-hand" in str(
        strict.get("audit_priority_owner", "")
    ), "audit_priority_owner must reference HR/Audit-hand"
    assert "Reza-hand" in str(
        strict.get("audit_priority_owner_is_not", "")
    ), "audit_priority_owner_is_not must negate Reza-hand"
    assert "strict superset" in str(
        strict.get("schema_extension_rule", "")
    ), "schema_extension_rule must reference 'strict superset'"
    assert strict.get("v1_to_v2_migration_compat_required") is True, (
        "v1_to_v2_migration_compat_required must be true"
    )
    rollback_modes = strict.get("rollback_must_be_one_of") or []
    for required in (
        "atomic-revert-of-nats-kv-bucket-extension",
        "forward-compat-documentation-note-bucket-left-in-place",
    ):
        assert required in rollback_modes, (
            f"rollback_must_be_one_of must enumerate '{required}'"
        )
    assert "B5" in str(
        strict.get("loose_audit_coverage_is_failure_mode", "")
    ), (
        "loose_audit_coverage_is_failure_mode must reference "
        "Tag-67 §5.1 B5"
    )


def test_t12_sandbox_boundary_all_defaults_set():
    stub = _load_stub()
    boundary = stub.get("sandbox_boundary") or {}
    for key in (
        "no_audit_sample_config_amendment_emit",
        "no_henrik_voss_priority_list_direction_emit",
        "no_promotion_pr_opening",
        "no_nats_kv_schema_default_change",
        "no_rollback_procedure_default_change",
    ):
        assert boundary.get(key) is True, (
            f"sandbox_boundary.{key} must be true"
        )
    assert boundary.get("probe_default_mode") == "inspection-only", (
        "probe_default_mode must be 'inspection-only'"
    )
    assert (
        boundary.get("schema_extension_audit_default")
        == "strict-superset-check"
    ), (
        "schema_extension_audit_default must be "
        "'strict-superset-check'"
    )


def test_t13_what_this_stub_is_not_negations():
    stub = _load_stub()
    negatives = stub.get("what_this_stub_is_not") or []
    blob = " ".join(str(n) for n in negatives)
    for phrase in (
        "audit-sample-config amendment",
        "Henrik Voss",
        "draft-ADR",
        "promotion-PR opening",
        "NATS-KV schema default change",
        "rollback-procedure default change",
        "indefinite-deferral",
        "AR-authorisation request",
    ):
        assert phrase in blob, (
            f"what_this_stub_is_not missing negation '{phrase}'"
        )


def test_t14_deep_dive_doc_references_stub_and_helper():
    if not DOC_PATH.exists():
        pytest.skip(f"Deep-dive doc not present at {DOC_REL}")
    text = DOC_PATH.read_text(encoding="utf-8")
    for needle in (
        "tooling/audit/res-d4-hd3-audit-coverage-stub.json",
        "tooling/audit/prepare_res_d4_hd3_audit_coverage_substrate.py",
        "### 6.4",
        "Tag-72",
    ):
        assert needle in text, (
            f"deep-dive doc missing required cross-anchor "
            f"'{needle}'"
        )


# --------------------------------------------------------------- #
# Axis B -- helper subprocess smoke-tests                         #
# --------------------------------------------------------------- #


def test_t15_helper_green_on_live_stub():
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


def test_t16_helper_fails_when_audit_only_flipped(tmp_path):
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


def test_t17_helper_fails_when_negative_control_priority_tag_removed(
    tmp_path,
):
    stub_copy = _hermetic_stub_copy(tmp_path)
    data = json.loads(stub_copy.read_text(encoding="utf-8"))
    data["audit_priority_tags"] = [
        t
        for t in data["audit_priority_tags"]
        if t.get("tag_name") != "reza-hand-priority-flip-forbidden"
    ]
    stub_copy.write_text(json.dumps(data), encoding="utf-8")
    result = _run_helper_against(stub_copy)
    assert result.returncode != 0, (
        "helper must reject stub when negative-control "
        "priority-tag is removed"
    )


def test_t18_helper_fails_when_v1_consumer_break_probe_removed(
    tmp_path,
):
    stub_copy = _hermetic_stub_copy(tmp_path)
    data = json.loads(stub_copy.read_text(encoding="utf-8"))
    data["schema_extension_audit_probes"] = [
        p
        for p in data["schema_extension_audit_probes"]
        if p.get("name")
        != "schema-extension-probe--v1-consumer-break"
    ]
    stub_copy.write_text(json.dumps(data), encoding="utf-8")
    result = _run_helper_against(stub_copy)
    assert result.returncode != 0, (
        "helper must reject stub when v1-consumer-break "
        "negative-control probe is removed"
    )


def test_t19_helper_fails_when_silent_leave_choice_removed(
    tmp_path,
):
    stub_copy = _hermetic_stub_copy(tmp_path)
    data = json.loads(stub_copy.read_text(encoding="utf-8"))
    data["rollback_audit_choices"] = [
        c
        for c in data["rollback_audit_choices"]
        if c.get("choice_name")
        != "rollback-choice--silent-leave-forbidden"
    ]
    stub_copy.write_text(json.dumps(data), encoding="utf-8")
    result = _run_helper_against(stub_copy)
    assert result.returncode != 0, (
        "helper must reject stub when silent-leave-forbidden "
        "negative-control rollback-choice is removed"
    )


def test_t20_helper_fails_when_res_d4_rotation_entry_dropped(
    tmp_path,
):
    stub_copy = _hermetic_stub_copy(tmp_path)
    data = json.loads(stub_copy.read_text(encoding="utf-8"))
    data["audit_sample_event_inventory"] = [
        e
        for e in data["audit_sample_event_inventory"]
        if e.get("event_name")
        != "audit-sample--res-d4-rotation-entry"
    ]
    stub_copy.write_text(json.dumps(data), encoding="utf-8")
    result = _run_helper_against(stub_copy)
    assert result.returncode != 0, (
        "helper must reject stub when res-d4-rotation-entry "
        "audit-sample event is dropped"
    )
    assert "res-d4-rotation-entry" in result.stderr, (
        "diagnostic must mention the missing event name"
    )


def test_t21_no_production_claim_in_stub():
    """Sandbox-boundary: stub MUST NOT claim audit-sample-rotation
    emit or resolver-calls in audit-only mode."""
    if not STUB_PATH.exists():
        pytest.skip(f"stub not present at {STUB_REL}")
    stub = _load_stub()
    # Priority tags: all rotation-emit = false, all kind: fixture.
    for tag in stub.get("audit_priority_tags") or []:
        assert tag.get("kind") == "fixture", (
            f"tag {tag.get('tag_name')!r} must be kind: fixture"
        )
        assert tag.get("audit_sample_rotation_emit") is False, (
            f"tag {tag.get('tag_name')!r} must NOT emit "
            "audit-sample-rotation in audit-only"
        )
        assert tag.get("expected_resolver_call") is False, (
            f"tag {tag.get('tag_name')!r} must NOT expect "
            "resolver call"
        )
    # Schema-extension probes: no rotation emit, no resolver call.
    for probe in stub.get("schema_extension_audit_probes") or []:
        assert probe.get("audit_sample_rotation_emit") is False, (
            f"probe {probe.get('name')!r} must NOT emit rotation"
        )
        assert probe.get("expected_resolver_call") is False, (
            f"probe {probe.get('name')!r} must NOT expect "
            "resolver call"
        )
    # Rollback choices: no resolver call.
    for choice in stub.get("rollback_audit_choices") or []:
        assert choice.get("expected_resolver_call") is False, (
            f"choice {choice.get('choice_name')!r} must NOT "
            "expect resolver call"
        )


def test_t22_fixture_entries_declare_tag_60_compat():
    stub = _load_stub()
    for tag in stub.get("audit_priority_tags") or []:
        assert tag.get("tag_60_compat") is True, (
            f"tag {tag.get('tag_name')!r} must declare "
            "'tag_60_compat: true'"
        )
    for probe in stub.get("schema_extension_audit_probes") or []:
        assert probe.get("tag_60_compat") is True, (
            f"probe {probe.get('name')!r} must declare "
            "'tag_60_compat: true'"
        )
    for choice in stub.get("rollback_audit_choices") or []:
        assert choice.get("tag_60_compat") is True, (
            f"choice {choice.get('choice_name')!r} must declare "
            "'tag_60_compat: true'"
        )


def test_t23_upstream_anchors_cite_full_chain():
    stub = _load_stub()
    anchors = stub.get("upstream_anchors") or {}
    assert anchors.get("tag_70_hd_1_substrate_pr") == 446, (
        "tag_70_hd_1_substrate_pr must be 446"
    )
    assert anchors.get("tag_71_hd_2_substrate_pr") == 452, (
        "tag_71_hd_2_substrate_pr must be 452"
    )
    assert anchors.get("tag_69_deep_dive_pr") == 440, (
        "tag_69_deep_dive_pr must be 440"
    )
    assert anchors.get("tag_66_ots_probe_coverage_pr") == 421, (
        "tag_66_ots_probe_coverage_pr must be 421"
    )
    assert anchors.get("tag_60_pre_activation_stub_pr") == 382, (
        "tag_60_pre_activation_stub_pr must be 382"
    )
    assert "Tag-67" in str(
        anchors.get("tag_67_pre_mortem_anchor", "")
    ) or "§5.1" in str(
        anchors.get("tag_67_pre_mortem_anchor", "")
    ), "tag_67_pre_mortem_anchor must reference Tag-67 §5"
    assert "Tag-65" in str(
        anchors.get("tag_65_promotion_sequencing_anchor", "")
    ) or "§5.2" in str(
        anchors.get("tag_65_promotion_sequencing_anchor", "")
    ) or "§6.2" in str(
        anchors.get("tag_65_promotion_sequencing_anchor", "")
    ), (
        "tag_65_promotion_sequencing_anchor must reference Tag-65 "
        "acceptance criteria or rollback procedure"
    )
    assert "ADR-0014" in str(
        anchors.get("adr_0014_audit_sample_rotation", "")
    ) or "Risk-Weighted" in str(
        anchors.get("adr_0014_audit_sample_rotation", "")
    ), (
        "adr_0014_audit_sample_rotation must reference ADR-0014 "
        "or Risk-Weighted rotation"
    )
    assert "Drei-Achsen" in str(
        anchors.get("adr_0025_three_axis_audit_anchor", "")
    ) or "ADR-0025" in str(
        anchors.get("adr_0025_three_axis_audit_anchor", "")
    ), (
        "adr_0025_three_axis_audit_anchor must reference ADR-0025 "
        "or Drei-Achsen"
    )


def test_t24_helper_fails_when_audit_priority_owner_flipped(
    tmp_path,
):
    """Hand-boundary invariant: helper rejects a mutilated stub
    where audit_priority_owner is flipped to Reza-hand."""
    stub_copy = _hermetic_stub_copy(tmp_path)
    data = json.loads(stub_copy.read_text(encoding="utf-8"))
    data["strict_audit_coverage_invariant"][
        "audit_priority_owner"
    ] = "Reza-hand"
    stub_copy.write_text(json.dumps(data), encoding="utf-8")
    result = _run_helper_against(stub_copy)
    assert result.returncode != 0, (
        "helper must reject stub when audit_priority_owner is "
        "flipped from HR/Audit-hand to Reza-hand"
    )
    assert (
        "HR/Audit-hand" in result.stderr
        or "audit_priority_owner" in result.stderr
    ), (
        "diagnostic must mention the hand-boundary discipline"
    )
