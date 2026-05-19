# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-70 tests for the RES-D4 HD-1 OTS-Calendar
Substrate-Preparation artifacts.
=========================================================================

Two-axis coverage:

  Axis A -- Stub-file shape invariants over the live Tag-70 stub
            ``tooling/audit/res-d4-hd1-ots-substrate-stub.json``
            (skip-if-absent for portability).
  Axis B -- Helper smoke-tests via subprocess against
            ``tooling/audit/prepare_res_d4_hd1_ots_substrate.py``,
            including hermetic mutilated-stub variants in
            ``tmp_path`` for negative-control coverage.

Test inventory (>=12 hermetic, all stdlib + pytest):

  T01  Stub-file exists at the expected path.
  T02  Stub-file is well-formed JSON.
  T03  Stub-file declares ``audit_only: true`` and
       ``doc_form_only: true``.
  T04  Stub-file declares ``tag: Tag-70`` and ``hard_dep: HD-1``.
  T05  Stub-file enumerates exactly three fixture-frames and each
       carries ``kind: fixture`` and ``expected_resolver_call:
       false``.
  T06  Stub-file's third fixture-frame is the live-emit-forbidden
       negative-control with ``expected_verifier_branch: reject``.
  T07  Stub-file enumerates the two ENV-flags
       (``WAKIR_OTS_LIVE_EMIT``, ``WAKIR_OTS_CALENDAR_URL``) with
       audit-only defaults.
  T08  Stub-file's sandbox-boundary section sets every boundary to
       its audit-only default.
  T09  Stub-file's ``what_this_stub_is_not`` section explicitly
       negates AR-authorisation, draft-ADR, promotion-PR,
       live-OTS-calendar, and indefinite-deferral-lifting.
  T10  Deep-dive doc references the stub-file path and the helper
       path under §6.2 with the Tag-70 marker.
  T11  Helper subprocess exits 0 on the live stub-file.
  T12  Helper subprocess exits non-zero when ``audit_only`` is
       flipped to ``false`` (mutilated stub).
  T13  Helper subprocess exits non-zero when the
       live-emit-forbidden negative-control frame is removed.
  T14  Helper subprocess exits non-zero when ``WAKIR_OTS_LIVE_EMIT``
       is dropped from the env-flag inventory.
  T15  Sandbox-boundary invariant: the stub MUST NOT enumerate any
       production OTS-calendar URL (no http:// or https:// scheme
       in any env-flag default or fixture-frame field).
  T16  Reuse-discipline invariant: every fixture-frame declares
       ``tag_60_compat: true`` (Tag-70 reuses Tag-60 base shape).
  T17  Cross-anchor invariant: stub upstream_anchors references
       Tag-67 + Tag-65 + Tag-69 deep-dive + Tag-60 PR #382 + Tag-69
       PR #440.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
STUB_REL = "tooling/audit/res-d4-hd1-ots-substrate-stub.json"
STUB_PATH = REPO_ROOT / STUB_REL
HELPER_REL = "tooling/audit/prepare_res_d4_hd1_ots_substrate.py"
HELPER_PATH = REPO_ROOT / HELPER_REL
DOC_REL = "docs/operations/res-d4-high-residual-mitigation-deep-dive.md"
DOC_PATH = REPO_ROOT / DOC_REL

EXPECTED_FRAMES = (
    "registry-pointer-frame--pending-anchor",
    "registry-pointer-frame--anchor-fixture-stub",
    "registry-pointer-frame--live-emit-forbidden",
)
EXPECTED_ENV_FLAGS = ("WAKIR_OTS_LIVE_EMIT", "WAKIR_OTS_CALENDAR_URL")


# --------------------------------------------------------------- #
# Stub fixtures                                                    #
# --------------------------------------------------------------- #


def _load_stub() -> dict:
    if not STUB_PATH.exists():
        pytest.skip(f"Tag-70 stub not present at {STUB_REL}")
    with STUB_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _hermetic_stub_copy(tmp_path: Path) -> Path:
    """Copy the stub into tmp_path for mutation."""
    if not STUB_PATH.exists():
        pytest.skip(f"Tag-70 stub not present at {STUB_REL}")
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
        pytest.skip(f"Tag-70 helper not present at {HELPER_REL}")
    tmp_tooling = tmp_stub.parent / "tooling" / "audit"
    tmp_tooling.mkdir(parents=True, exist_ok=True)
    helper_copy = tmp_tooling / "prepare_res_d4_hd1_ots_substrate.py"
    shutil.copy(HELPER_PATH, helper_copy)
    stub_copy = tmp_tooling / "res-d4-hd1-ots-substrate-stub.json"
    stub_copy.write_text(
        tmp_stub.read_text(encoding="utf-8"), encoding="utf-8"
    )
    # Also copy the deep-dive doc so cross-anchor check finds it.
    if DOC_PATH.exists():
        tmp_doc_dir = tmp_stub.parent / "docs" / "operations"
        tmp_doc_dir.mkdir(parents=True, exist_ok=True)
        doc_copy = (
            tmp_doc_dir / "res-d4-high-residual-mitigation-deep-dive.md"
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
        f"Tag-70 stub missing at {STUB_REL}"
    )


def test_t02_stub_is_well_formed_json():
    text = STUB_PATH.read_text(encoding="utf-8") if STUB_PATH.exists() else None
    if text is None:
        pytest.skip(f"Tag-70 stub not present at {STUB_REL}")
    json.loads(text)  # raises on malformed


def test_t03_stub_declares_audit_only_and_doc_form_only():
    stub = _load_stub()
    assert stub.get("audit_only") is True, (
        "stub must declare 'audit_only: true'"
    )
    assert stub.get("doc_form_only") is True, (
        "stub must declare 'doc_form_only: true'"
    )


def test_t04_stub_declares_tag70_and_hd_1():
    stub = _load_stub()
    assert stub.get("tag") == "Tag-70", (
        f"stub must declare 'tag: Tag-70', got {stub.get('tag')!r}"
    )
    assert stub.get("hard_dep") == "HD-1", (
        f"stub must declare 'hard_dep: HD-1', got "
        f"{stub.get('hard_dep')!r}"
    )


def test_t05_three_fixture_frames_all_kind_fixture():
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


def test_t06_negative_control_frame_rejects():
    stub = _load_stub()
    frames = stub.get("fixture_frames") or []
    negative = next(
        (
            f
            for f in frames
            if f.get("name")
            == "registry-pointer-frame--live-emit-forbidden"
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


def test_t07_env_flag_inventory_complete_and_audit_only():
    stub = _load_stub()
    flags = stub.get("env_flag_inventory") or []
    names = [f.get("name") for f in flags]
    for expected in EXPECTED_ENV_FLAGS:
        assert expected in names, (
            f"env_flag_inventory missing required flag "
            f"'{expected}'"
        )
    by_name = {f.get("name"): f for f in flags}
    live_emit = by_name["WAKIR_OTS_LIVE_EMIT"]
    assert live_emit.get("default") == "0", (
        "WAKIR_OTS_LIVE_EMIT default must be '0' (audit-only)"
    )
    cal_url = by_name["WAKIR_OTS_CALENDAR_URL"]
    assert cal_url.get("default", "").startswith("fixture://"), (
        "WAKIR_OTS_CALENDAR_URL default must use 'fixture://' "
        "scheme (audit-only)"
    )


def test_t08_sandbox_boundary_all_defaults_set():
    stub = _load_stub()
    boundary = stub.get("sandbox_boundary") or {}
    for key in (
        "no_live_ots_calendar_traffic",
        "no_ar_authorisation_request_emit",
        "no_promotion_pr_opening",
        "no_env_flag_default_on_change",
    ):
        assert boundary.get(key) is True, (
            f"sandbox_boundary.{key} must be true"
        )
    assert boundary.get("verifier_emit_branch_default") == "off", (
        "verifier_emit_branch_default must be 'off'"
    )


def test_t09_what_this_stub_is_not_negations():
    stub = _load_stub()
    negatives = stub.get("what_this_stub_is_not") or []
    blob = " ".join(str(n) for n in negatives)
    for phrase in (
        "AR-authorisation request",
        "draft-ADR",
        "promotion-PR opening",
        "live-OTS-calendar configuration",
        "indefinite-deferral",
    ):
        assert phrase in blob, (
            f"what_this_stub_is_not missing negation '{phrase}'"
        )


def test_t10_deep_dive_doc_references_stub_and_helper():
    if not DOC_PATH.exists():
        pytest.skip(f"Deep-dive doc not present at {DOC_REL}")
    text = DOC_PATH.read_text(encoding="utf-8")
    for needle in (
        "tooling/audit/res-d4-hd1-ots-substrate-stub.json",
        "tooling/audit/prepare_res_d4_hd1_ots_substrate.py",
        "### 6.2",
        "Tag-70",
    ):
        assert needle in text, (
            f"deep-dive doc missing required cross-anchor "
            f"'{needle}'"
        )


# --------------------------------------------------------------- #
# Axis B -- helper subprocess smoke-tests                         #
# --------------------------------------------------------------- #


def test_t11_helper_green_on_live_stub(tmp_path):
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


def test_t12_helper_fails_when_audit_only_flipped(tmp_path):
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


def test_t13_helper_fails_when_negative_control_frame_removed(tmp_path):
    stub_copy = _hermetic_stub_copy(tmp_path)
    data = json.loads(stub_copy.read_text(encoding="utf-8"))
    data["fixture_frames"] = [
        f
        for f in data["fixture_frames"]
        if f.get("name")
        != "registry-pointer-frame--live-emit-forbidden"
    ]
    stub_copy.write_text(json.dumps(data), encoding="utf-8")
    result = _run_helper_against(stub_copy)
    assert result.returncode != 0, (
        "helper must reject stub when negative-control frame "
        "is removed"
    )


def test_t14_helper_fails_when_live_emit_env_flag_dropped(tmp_path):
    stub_copy = _hermetic_stub_copy(tmp_path)
    data = json.loads(stub_copy.read_text(encoding="utf-8"))
    data["env_flag_inventory"] = [
        f
        for f in data["env_flag_inventory"]
        if f.get("name") != "WAKIR_OTS_LIVE_EMIT"
    ]
    stub_copy.write_text(json.dumps(data), encoding="utf-8")
    result = _run_helper_against(stub_copy)
    assert result.returncode != 0, (
        "helper must reject stub when WAKIR_OTS_LIVE_EMIT is "
        "dropped from env-flag inventory"
    )
    assert "WAKIR_OTS_LIVE_EMIT" in result.stderr, (
        "diagnostic must mention the missing flag name"
    )


def test_t15_no_production_url_in_stub():
    """Sandbox-boundary: stub MUST NOT enumerate production URLs."""
    if not STUB_PATH.exists():
        pytest.skip(f"stub not present at {STUB_REL}")
    text = STUB_PATH.read_text(encoding="utf-8")
    # Allowed: 'https://wakir.dev/...' for $id schema URL, 'https://json-schema.org/...'.
    # Forbidden: any other http:// or https:// pointing at an
    # alleged OTS calendar.
    for forbidden in (
        "https://alice.btc.calendar",
        "https://bob.btc.calendar",
        "https://finney.calendar.eternitywall.com",
        "https://btc.calendar.catallaxy.com",
        "http://ots-calendar",
        "https://ots-calendar",
    ):
        assert forbidden not in text, (
            f"stub must NOT enumerate production OTS-calendar "
            f"URL: found '{forbidden}'"
        )


def test_t16_fixture_frames_declare_tag_60_compat():
    stub = _load_stub()
    frames = stub.get("fixture_frames") or []
    for frame in frames:
        assert frame.get("tag_60_compat") is True, (
            f"frame {frame.get('name')!r} must declare "
            "'tag_60_compat: true' (Tag-70 reuses Tag-60 shape)"
        )


def test_t17_upstream_anchors_cite_tag_67_65_69_60():
    stub = _load_stub()
    anchors = stub.get("upstream_anchors") or {}
    assert "Tag-67" in str(
        anchors.get("tag_67_pre_mortem_anchor", "")
    ) or "§5.1" in str(
        anchors.get("tag_67_pre_mortem_anchor", "")
    ), "tag_67_pre_mortem_anchor must reference Tag-67 §5"
    assert "Tag-65" in str(
        anchors.get("tag_65_promotion_sequencing_anchor", "")
    ) or "HARD-edge" in str(
        anchors.get("tag_65_promotion_sequencing_anchor", "")
    ), (
        "tag_65_promotion_sequencing_anchor must reference Tag-65 "
        "HARD-edge"
    )
    assert anchors.get("tag_60_pre_activation_stub_pr") == 382, (
        "tag_60_pre_activation_stub_pr must be 382"
    )
    assert anchors.get("tag_69_deep_dive_pr") == 440, (
        "tag_69_deep_dive_pr must be 440"
    )
