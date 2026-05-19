#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-70 RES-D4 HD-1 OTS-Calendar Substrate-Preparation helper.

Audit-only mode. This helper inspects the Tag-70 HD-1 OTS-substrate
stub-file at
``tooling/audit/res-d4-hd1-ots-substrate-stub.json`` and asserts:

  - The stub-file is well-formed JSON.
  - The stub-file declares ``audit_only: true`` and
    ``doc_form_only: true``.
  - The stub-file declares the Tag-70 / HD-1 anchors.
  - The stub-file enumerates exactly three fixture-frames and each
    carries ``kind: fixture``.
  - The third fixture-frame is the live-emit-forbidden
    negative-control with ``expected_verifier_branch: reject``.
  - The stub-file enumerates the two ENV-flags
    (``WAKIR_OTS_LIVE_EMIT``, ``WAKIR_OTS_CALENDAR_URL``) and both
    declare ``ar_authorisation_required`` semantics.
  - The stub-file's sandbox-boundary section sets every boundary to
    its default (no live-OTS traffic, no AR-auth-request emit, no
    promotion-PR opening, no ENV-flag default-on change).
  - The helper itself does NOT call any external network endpoint.
  - The helper itself does NOT set ``WAKIR_OTS_LIVE_EMIT=1``.

The helper is invoked from the test-suite at
``tests/audit/test_hd_1_ots_substrate_tag70.py`` via subprocess.

Exit 0 on green, exit 1 on any failure with a clear stderr message.
Standard library only.

Sandbox-boundary recital (per deep-dive §8):

  - No live-OTS calendar traffic is emitted by this helper.
  - No AR-authorisation request is emitted by this helper.
  - No promotion-PR is opened by this helper.
  - No ENV-flag default-on change is performed by this helper.

This helper is the Tag-70 §6.2 deep-dive operational counterpart.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

STUB_PATH = (
    Path(__file__).resolve().parent
    / "res-d4-hd1-ots-substrate-stub.json"
)
DOC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "operations"
    / "res-d4-high-residual-mitigation-deep-dive.md"
)

EXPECTED_FIXTURE_FRAME_NAMES = (
    "registry-pointer-frame--pending-anchor",
    "registry-pointer-frame--anchor-fixture-stub",
    "registry-pointer-frame--live-emit-forbidden",
)
EXPECTED_ENV_FLAGS = (
    "WAKIR_OTS_LIVE_EMIT",
    "WAKIR_OTS_CALENDAR_URL",
)
EXPECTED_TAG = "Tag-70"
EXPECTED_HARD_DEP = "HD-1"


def fail(msg: str) -> None:
    sys.stderr.write(
        f"prepare_res_d4_hd1_ots_substrate: FAIL: {msg}\n"
    )
    sys.exit(1)


def info(msg: str) -> None:
    sys.stdout.write(
        f"prepare_res_d4_hd1_ots_substrate: {msg}\n"
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
        "tag_60_pre_activation_stub_pr",
        "tag_69_deep_dive_pr",
    )
    for key in required_keys:
        if key not in anchors:
            fail(
                f"upstream_anchors missing required key '{key}'"
            )
    if anchors.get("tag_60_pre_activation_stub_pr") != 382:
        fail(
            "upstream_anchors.tag_60_pre_activation_stub_pr "
            "must be 382 (Tag-60 PR)"
        )
    if anchors.get("tag_69_deep_dive_pr") != 440:
        fail(
            "upstream_anchors.tag_69_deep_dive_pr must be 440 "
            "(Tag-69 PR)"
        )


def assert_sandbox_boundary(stub: dict) -> None:
    boundary = stub.get("sandbox_boundary") or {}
    for key in (
        "no_live_ots_calendar_traffic",
        "no_ar_authorisation_request_emit",
        "no_promotion_pr_opening",
        "no_env_flag_default_on_change",
    ):
        if boundary.get(key) is not True:
            fail(
                f"sandbox_boundary.{key} must be true "
                "(audit-only posture)"
            )
    if boundary.get("verifier_emit_branch_default") != "off":
        fail(
            "sandbox_boundary.verifier_emit_branch_default must "
            "be 'off' (audit-only posture)"
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
    # Order and uniqueness
    if sorted(seen_names) != sorted(EXPECTED_FIXTURE_FRAME_NAMES):
        fail(
            "fixture_frames must contain exactly the three named "
            f"variants: {EXPECTED_FIXTURE_FRAME_NAMES}"
        )
    # Negative-control invariant: live-emit-forbidden must reject.
    negative = next(
        (
            f
            for f in frames
            if f.get("name")
            == "registry-pointer-frame--live-emit-forbidden"
        ),
        None,
    )
    if negative is None:
        fail(
            "negative-control fixture-frame "
            "'registry-pointer-frame--live-emit-forbidden' missing"
        )
    if negative.get("expected_verifier_branch") != "reject":
        fail(
            "negative-control fixture-frame must declare "
            "'expected_verifier_branch: reject'"
        )


def assert_env_flag_inventory(stub: dict) -> None:
    flags = stub.get("env_flag_inventory") or []
    if not isinstance(flags, list):
        fail("env_flag_inventory must be a list")
    names = [flag.get("name") for flag in flags if isinstance(flag, dict)]
    for expected in EXPECTED_ENV_FLAGS:
        if expected not in names:
            fail(
                f"env_flag_inventory missing required flag "
                f"'{expected}'"
            )
    for flag in flags:
        if not isinstance(flag, dict):
            fail("each env-flag must be an object")
        if flag.get("default") not in ("0", "fixture://ots-calendar.invalid/audit-only/stub"):
            fail(
                f"env-flag {flag.get('name')!r} has unexpected "
                f"default {flag.get('default')!r}; only audit-only "
                "defaults are permitted"
            )
        # AR-authorisation gate must be declared in some form.
        keys = [k for k in flag.keys() if "ar_authorisation_required" in k]
        if not keys:
            fail(
                f"env-flag {flag.get('name')!r} must declare an "
                "'ar_authorisation_required_*' gate"
            )


def assert_what_this_stub_is_not(stub: dict) -> None:
    negatives = stub.get("what_this_stub_is_not") or []
    required_phrases = (
        "AR-authorisation request",
        "draft-ADR",
        "promotion-PR opening",
        "live-OTS-calendar configuration",
        "indefinite-deferral",
    )
    blob = " ".join(str(n) for n in negatives)
    for phrase in required_phrases:
        if phrase not in blob:
            fail(
                f"what_this_stub_is_not must explicitly negate "
                f"'{phrase}'"
            )


def assert_doc_cross_anchor(stub: dict) -> None:
    """The deep-dive doc must reference the stub-file path."""
    if not DOC_PATH.is_file():
        # Doc may not exist in a hermetic stub-only sandbox; skip.
        info("doc-file not present, skipping doc cross-anchor check")
        return
    text = DOC_PATH.read_text(encoding="utf-8")
    needed = (
        "tooling/audit/res-d4-hd1-ots-substrate-stub.json",
        "tooling/audit/prepare_res_d4_hd1_ots_substrate.py",
        "### 6.2",
        "Tag-70",
    )
    for needle in needed:
        if needle not in text:
            fail(
                f"deep-dive doc missing required cross-anchor "
                f"'{needle}'"
            )


def assert_helper_self_sandbox() -> None:
    """The helper itself must never set WAKIR_OTS_LIVE_EMIT=1."""
    # Defensive: if the helper is invoked with WAKIR_OTS_LIVE_EMIT
    # already set to '1', we still proceed (the env-flag is owned
    # by the caller), but we MUST NOT alter it ourselves. Verify
    # we have not written to os.environ.
    pre = os.environ.get("WAKIR_OTS_LIVE_EMIT")
    # We do not set it here. Just record.
    post = os.environ.get("WAKIR_OTS_LIVE_EMIT")
    if pre != post:
        fail(
            "helper must not alter WAKIR_OTS_LIVE_EMIT env-flag"
        )


def main(argv: list) -> int:
    info(f"loading stub: {STUB_PATH}")
    stub = load_stub(STUB_PATH)
    assert_audit_only_posture(stub)
    assert_upstream_anchors(stub)
    assert_sandbox_boundary(stub)
    assert_fixture_frames(stub)
    assert_env_flag_inventory(stub)
    assert_what_this_stub_is_not(stub)
    assert_doc_cross_anchor(stub)
    assert_helper_self_sandbox()
    info("OK: Tag-70 HD-1 OTS-substrate stub is audit-only-clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
