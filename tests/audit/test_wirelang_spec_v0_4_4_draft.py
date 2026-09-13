# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-63 tests for the Wirelang Spec v0.4.4 Post-Cutover-Reserve-Draft
=============================================================================

Two-axis coverage:

  Axis A — Draft-shape invariants over the live
           ``wirelang/specs/wirelang-spec-v0-4-4-draft.md`` document
           (skip-if-absent for portability).
  Axis B — Helper extension (``audit_adr_errata_spec_drift.py``)
           draft-awareness logic, tested on hermetic fixtures.

Test inventory (>= 12 hermetic, all stdlib):

  T01  Spec file exists at the expected path.
  T02  Spec frontmatter declares ``version: 0.4.4-draft``.
  T03  Spec frontmatter declares ``status: post-cutover-reserve-draft``.
  T04  Spec frontmatter declares ``parent: wirelang-spec-v0-4-3``.
  T05  Spec frontmatter declares ``replaces: null`` and
       ``replaced-by: null`` (the draft-isolation invariant in the
       patch-trace chain).
  T06  Spec frontmatter declares ``freeze-marker: null`` and
       ``freeze-anchor: null`` (the draft is not a freeze-marker;
       the v0.4.3 seal MUST NOT pick this up as another freeze
       document).
  T07  Spec frontmatter declares ``activation-trigger:
       kw-24-cutover-T0-post-promotion`` and ``activation-policy:
       sequence-promotion-only`` (the post-cutover gate).
  T08  Spec body carries forward the v0.4.3 §4.1 ten-Pin-Pack-record
       table verbatim (Pin-Pack carry-forward invariant). Drift here
       means the draft has accidentally re-baselined the Pin-Pack —
       which is exactly what the draft promises NOT to do.
  T09  Spec body collects the five RES-Dn candidate items in §6 (one
       per reserve-substrate sub-section §6.1..§6.5).
  T10  Spec body mentions the draft-isolation invariant prominently
       (intro paragraph and §2 forbidance text both contain the
       string ``draft-isolation``).
  T11  Spec body does NOT mention ``status: pre-cutover-freeze`` in
       its own frontmatter (i.e. the freeze-seal probe MUST NOT
       confuse v0.4.4-draft for a second freeze-marker). The phrase
       MAY appear in the body as a cross-reference to v0.4.3, but
       not in the frontmatter.
  T12  The v0.4.3 freeze-seal file is unchanged: SHA-256 of
       ``wirelang/specs/wirelang-spec-v0-4-3.md`` matches the value
       in ``wirelang/specs/freeze-baseline.json``. (Tag-63 promise:
       the draft does NOT break the v0.4.3 seal.)
  T13  Helper extension: ``is_draft_spec`` returns True on a
       synthesised fixture carrying ``status: post-cutover-reserve-
       draft`` and False on a synthesised pre-cutover-freeze fixture.
  T14  Helper extension: ``detect_spec_status`` and
       ``detect_spec_version`` recover the frontmatter values on a
       hermetic fixture.
  T15  Helper extension: ``validate_draft_shape`` returns the six
       invariant pass-bits on a synthesised well-formed draft, and
       at least one fails on a synthesised malformed draft
       (e.g. missing ``parent:``).
  T16  Helper extension: ``run_audit`` on a synthesised draft spec
       skips drift-classification (every marker is ``drift-skipped``
       and ``draft_shape.is_draft`` is True). The summary counters
       ``markers_with_drift`` and ``markers_with_citation_ok`` are
       both zero.
  T17  Helper extension: ``run_audit`` on a synthesised non-draft
       spec still emits ``draft_shape`` populated with
       ``is_draft=False`` and the existing drift-classification
       contract (Tag-57 behaviour) is preserved.

All fixtures (except the live-document anchor tests T01..T12) are
synthesised in ``tmp_path``. No network, no real clone, no git.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import re
import sys

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-4-draft.md"
SPEC_V043 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"
FREEZE_BASELINE = REPO_ROOT / "wirelang" / "specs" / "freeze-baseline.json"
HELPER_PATH = (
    REPO_ROOT / "tooling" / "audit" / "audit_adr_errata_spec_drift.py"
)


# --------------------------------------------------------------- #
# Helper import (file-driven so tests work both from repo root    #
# and from a pytest invocation in tests/audit/)                   #
# --------------------------------------------------------------- #


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "audit_adr_errata_spec_drift_tag63", HELPER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------- #
# Synthetic fixture builders                                       #
# --------------------------------------------------------------- #


def _make_draft_fixture(
    *,
    status: str = "post-cutover-reserve-draft",
    version: str = "0.4.4-draft",
    parent: str = "wirelang-spec-v0-4-3",
    replaces: str = "null",
    replaced_by: str = "null",
    activation_trigger: str = "kw-24-cutover-T0-post-promotion",
    include_isolation_phrase: bool = True,
) -> str:
    iso = "draft-isolation invariant" if include_isolation_phrase else ""
    return (
        "---\n"
        f"spec: wirelang\n"
        f"version: {version}\n"
        f"status: {status}\n"
        f"parent: {parent}\n"
        f"replaces: {replaces}\n"
        f"replaced-by: {replaced_by}\n"
        f"activation-trigger: {activation_trigger}\n"
        f"activation-policy: sequence-promotion-only\n"
        "---\n"
        "\n"
        f"# Draft fixture\n"
        f"\nReserve substrate. {iso}\n"
        "## 2. Conformance keywords\n"
        f"\nThis is the {iso}.\n"
    )


def _make_pre_cutover_freeze_fixture() -> str:
    return (
        "---\n"
        "spec: wirelang\n"
        "version: 0.4.3\n"
        "status: pre-cutover-freeze\n"
        "extends: 0.4.2\n"
        "freeze-marker: kw-24-cutover-gate\n"
        "freeze-anchor: persona-engine-0.5.2-final-pre-cutover\n"
        "---\n"
        "\n# Frozen spec\nThis is a pre-cutover-freeze document.\n"
    )


# --------------------------------------------------------------- #
# Axis A — Live spec invariants (skip-if-absent)                  #
# --------------------------------------------------------------- #


@pytest.fixture(scope="module")
def live_spec_text() -> str:
    if not SPEC_PATH.exists():
        pytest.skip(f"Live spec not present at {SPEC_PATH}; skipping Axis-A.")
    return SPEC_PATH.read_text(encoding="utf-8")


def _extract_frontmatter_block(spec_text: str) -> str:
    fences = [m.start() for m in re.finditer(r"^---\s*$", spec_text, re.MULTILINE)]
    assert len(fences) >= 2, "spec does not carry a frontmatter block"
    # The frontmatter is between the first fence's line-end and the second fence.
    first_end = spec_text.find("\n", fences[0]) + 1
    return spec_text[first_end:fences[1]]


def test_T01_spec_file_exists():
    assert SPEC_PATH.exists(), f"Missing v0.4.4-draft at {SPEC_PATH}"


def test_T02_frontmatter_version(live_spec_text: str):
    fm = _extract_frontmatter_block(live_spec_text)
    assert re.search(r"^version:\s*0\.4\.4-draft\s*$", fm, re.MULTILINE), fm


def test_T03_frontmatter_status(live_spec_text: str):
    fm = _extract_frontmatter_block(live_spec_text)
    assert re.search(
        r"^status:\s*post-cutover-reserve-draft\s*$", fm, re.MULTILINE
    ), fm


def test_T04_frontmatter_parent(live_spec_text: str):
    fm = _extract_frontmatter_block(live_spec_text)
    assert re.search(
        r"^parent:\s*wirelang-spec-v0-4-3\s*$", fm, re.MULTILINE
    ), fm


def test_T05_frontmatter_replaces_and_replaced_by_null(live_spec_text: str):
    fm = _extract_frontmatter_block(live_spec_text)
    assert re.search(r"^replaces:\s*null\s*$", fm, re.MULTILINE), fm
    assert re.search(r"^replaced-by:\s*null\s*$", fm, re.MULTILINE), fm


def test_T06_frontmatter_freeze_marker_and_anchor_null(live_spec_text: str):
    fm = _extract_frontmatter_block(live_spec_text)
    assert re.search(r"^freeze-marker:\s*null\s*$", fm, re.MULTILINE), fm
    assert re.search(r"^freeze-anchor:\s*null\s*$", fm, re.MULTILINE), fm


def test_T07_frontmatter_activation_trigger_and_policy(live_spec_text: str):
    fm = _extract_frontmatter_block(live_spec_text)
    assert re.search(
        r"^activation-trigger:\s*kw-24-cutover-T0-post-promotion\s*$",
        fm,
        re.MULTILINE,
    ), fm
    assert re.search(
        r"^activation-policy:\s*sequence-promotion-only\s*$",
        fm,
        re.MULTILINE,
    ), fm


def test_T08_carry_forward_pin_pack_ten_records(live_spec_text: str):
    """
    The v0.4.4-draft restates the v0.4.3 §4.1 ten-Pin-Pack-record table
    verbatim. We pin every component name and selector ENV so a drift
    in either direction is caught.
    """
    expected = [
        ("persona-engine-recovery", "WAKIR_RECOVERY_BACKEND"),
        ("persona-engine-state-backing", "WAKIR_STATE_BACKING_BACKEND"),
        ("persona-engine-fsm", "WAKIR_FSM_BACKEND"),
        ("persona-engine-v907-verify", "WAKIR_V907_VERIFY_BACKEND"),
        ("persona-engine-bridge-diff", "WAKIR_BRIDGE_DIFF_BACKEND"),
        ("persona-engine-subscribe-loop", "WAKIR_SUBSCRIBE_LOOP_BACKEND"),
        ("persona-engine-anchor-emitter", "WAKIR_ANCHOR_EMITTER_BACKEND"),
        (
            "persona-engine-svid-workload-identity",
            "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND",
        ),
        (
            "persona-engine-federation-resolver",
            "WAKIR_FEDERATION_RESOLVER_BACKEND",
        ),
        (
            "persona-engine-bridge-audit-writer",
            "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND",
        ),
    ]
    for component, env in expected:
        assert component in live_spec_text, f"missing component: {component}"
        assert env in live_spec_text, f"missing selector ENV: {env}"


def test_T09_collects_five_reserve_substrate_items(live_spec_text: str):
    """
    The draft enumerates RES-D1..RES-D5 in §1 (reserve summary table)
    and provides candidate text in §6.1..§6.5. Pin the five marker
    ids and the five sub-section headings.
    """
    for i in range(1, 6):
        assert f"RES-D{i}" in live_spec_text, f"missing reserve marker RES-D{i}"
    for i in range(1, 6):
        assert re.search(
            rf"^###\s+6\.{i}\s+RES-D{i}:",
            live_spec_text,
            re.MULTILINE,
        ), f"missing §6.{i} RES-D{i} heading"


def test_T10_draft_isolation_invariant_mentioned(live_spec_text: str):
    # The draft must mention "draft-isolation invariant" in both the
    # intro paragraph and §2. We accept any count >= 2.
    count = live_spec_text.count("draft-isolation invariant")
    assert count >= 2, f"expected >=2 mentions of 'draft-isolation invariant', got {count}"


def test_T11_frontmatter_does_not_carry_pre_cutover_freeze(live_spec_text: str):
    fm = _extract_frontmatter_block(live_spec_text)
    # Frontmatter MUST NOT declare pre-cutover-freeze itself. The phrase
    # MAY appear in the body as a cross-reference (it does, talking about
    # v0.4.3) but the draft's own status MUST be post-cutover-reserve-draft.
    assert "status: pre-cutover-freeze" not in fm, fm
    # Sanity: the draft's own status IS in the frontmatter.
    assert "status: post-cutover-reserve-draft" in fm, fm


def test_T12_v0_4_3_freeze_seal_intact():
    """
    The Tag-63 draft promise: v0.4.3 seal is NOT broken. We verify by
    re-hashing the v0.4.3 spec file and comparing against the value in
    freeze-baseline.json. Skip-if-absent for portability across worktrees
    that may not carry the baseline.
    """
    if not SPEC_V043.exists():
        pytest.skip(f"v0.4.3 spec not present at {SPEC_V043}")
    if not FREEZE_BASELINE.exists():
        pytest.skip(f"freeze-baseline.json not present at {FREEZE_BASELINE}")
    baseline = json.loads(FREEZE_BASELINE.read_text(encoding="utf-8"))
    # The baseline JSON nests the sha256 under "baseline" in the
    # Tag-58 schema; fall back to top-level for older shapes.
    expected_sha = baseline.get("baseline", {}).get("sha256") or baseline.get("sha256")
    if not expected_sha:
        pytest.skip("freeze-baseline.json carries no sha256 field")
    actual = hashlib.sha256(SPEC_V043.read_bytes()).hexdigest()
    assert actual == expected_sha, (
        f"v0.4.3 SHA-256 drift detected: expected {expected_sha}, got {actual}. "
        "The Tag-63 draft work MUST NOT alter v0.4.3."
    )


# --------------------------------------------------------------- #
# Axis B — Helper extension on synthetic fixtures                 #
# --------------------------------------------------------------- #


def test_T13_is_draft_spec_true_on_draft_false_on_freeze():
    mod = _load_helper()
    draft = _make_draft_fixture()
    frozen = _make_pre_cutover_freeze_fixture()
    assert mod.is_draft_spec(draft) is True
    assert mod.is_draft_spec(frozen) is False


def test_T14_detect_spec_status_and_version():
    mod = _load_helper()
    draft = _make_draft_fixture(status="post-cutover-reserve-draft", version="0.4.4-draft")
    assert mod.detect_spec_status(draft) == "post-cutover-reserve-draft"
    assert mod.detect_spec_version(draft) == "0.4.4-draft"
    frozen = _make_pre_cutover_freeze_fixture()
    assert mod.detect_spec_status(frozen) == "pre-cutover-freeze"
    assert mod.detect_spec_version(frozen) == "0.4.3"


def test_T15_validate_draft_shape_well_and_malformed():
    mod = _load_helper()
    well = _make_draft_fixture()
    shape = mod.validate_draft_shape(well)
    # All six invariants pass on a well-formed draft fixture.
    expected_keys = {
        "has_frontmatter_status_marker",
        "has_parent_pointer",
        "has_replaces_null",
        "has_replaced_by_null",
        "has_activation_trigger",
        "mentions_draft_isolation",
    }
    assert set(shape.keys()) == expected_keys
    assert all(shape.values()), f"well-formed draft failed an invariant: {shape}"

    # Malformed: drop the parent: pointer (replace with empty value).
    malformed = well.replace("parent: wirelang-spec-v0-4-3\n", "")
    bad = mod.validate_draft_shape(malformed)
    assert bad["has_parent_pointer"] is False
    # The other invariants stay green; we only broke one.
    assert bad["has_frontmatter_status_marker"] is True
    assert bad["mentions_draft_isolation"] is True

    # Malformed: drop the isolation phrase. Both occurrences (intro + §2).
    no_iso = _make_draft_fixture(include_isolation_phrase=False)
    bad2 = mod.validate_draft_shape(no_iso)
    assert bad2["mentions_draft_isolation"] is False


def test_T16_run_audit_skips_drift_on_draft(tmp_path: pathlib.Path):
    mod = _load_helper()
    # Synthesise a hermetic environment: an empty decisions_dir
    # (helper will report all four ADR heads as found=False) and a
    # draft spec at a tmp path.
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    spec_path = tmp_path / "wirelang-spec-v0-4-4-draft-fixture.md"
    spec_path.write_text(_make_draft_fixture(), encoding="utf-8")

    envelope = mod.run_audit(decisions_dir=decisions_dir, spec_path=spec_path)

    # Draft-shape envelope is populated.
    assert envelope.draft_shape is not None
    assert envelope.draft_shape.is_draft is True
    assert envelope.draft_shape.spec_status == "post-cutover-reserve-draft"
    assert envelope.draft_shape.spec_version == "0.4.4-draft"
    assert envelope.draft_shape.shape_all_pass is True

    # Drift-classification was skipped: every marker is "draft-skipped".
    assert len(envelope.err_markers) == 6
    for mr in envelope.err_markers:
        assert mr.drift_class == "draft-skipped"
        assert mr.mentions_canonical_form_in_spec == 0
        assert mr.mentions_legacy_form_in_spec == 0
        assert mr.legacy_form_citation_pointer is False

    # Summary counters are both zero on a draft.
    assert envelope.summary.markers_total == 6
    assert envelope.summary.markers_with_drift == 0
    assert envelope.summary.markers_with_citation_ok == 0

    # Sanity: spec_freeze_marker is None on a draft (the draft does
    # not carry "pre-cutover-freeze" in its frontmatter).
    assert envelope.spec_freeze_marker is None


def test_T17_run_audit_preserves_tag57_behaviour_on_non_draft(tmp_path: pathlib.Path):
    mod = _load_helper()
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    spec_path = tmp_path / "wirelang-spec-v0-4-3-fixture.md"
    spec_path.write_text(_make_pre_cutover_freeze_fixture(), encoding="utf-8")

    envelope = mod.run_audit(decisions_dir=decisions_dir, spec_path=spec_path)

    # Non-draft envelope: draft_shape exists but is_draft=False.
    assert envelope.draft_shape is not None
    assert envelope.draft_shape.is_draft is False
    assert envelope.draft_shape.spec_status == "pre-cutover-freeze"

    # Tag-57 behaviour preserved: spec_freeze_marker resolves on a
    # pre-cutover-freeze document; markers run through the canonical/
    # legacy form classifier; on this minimal fixture, no canonical
    # form is mentioned (no back-tick spans) so every marker reports
    # "no-drift" and citation_ok_count == markers_total.
    assert envelope.spec_freeze_marker == "pre-cutover-freeze"
    assert envelope.summary.markers_total == 6
    assert envelope.summary.markers_with_drift == 0
    assert envelope.summary.markers_with_citation_ok == 6
    for mr in envelope.err_markers:
        assert mr.drift_class == "no-drift"
