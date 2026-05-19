# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-64 tests for the Wirelang Spec v0.4.4 Post-Cutover-Reserve-Draft
=============================================================================
Coverage-Extension over Tag-63 draft-shape invariants.

Tag-63 pinned the draft-isolation invariant (§2), the
frontmatter shape (status / parent / activation-trigger),
and the §6.1..§6.5 RES-Dn sub-section presence.

Tag-64 extends that pin-set with per-RES-Dn **sample-block**
pins: each of the five reserve items carries a §6.n.1
canonical-form sample inside the spec body. The Tag-64 suite
verifies:

  Axis A — Sample-Block Existence
           For each RES-Dn (n=1..5), the spec body MUST carry
           a §6.n.1 sub-heading and a fenced ``yaml`` code block
           that follows that heading.

  Axis B — Canonical-Form Validity (shape-only)
           For each sample block, the body MUST contain the
           RES-Dn marker string inside the block, MUST declare
           a candidate-version anchor (``0.4.4-draft-RES-Dn``),
           and MUST be a textually-balanced fenced block (open
           and close fence balance).

  Axis C — Reference-Integrity to v0.4.3 (Parent-Anchor)
           The sample blocks MUST NOT alter the v0.4.3 spec
           (freeze-seal SHA-256 unchanged) and MUST NOT carry
           the string ``status: pre-cutover-freeze`` in the
           draft frontmatter. The samples MUST cite the parent
           contracts they extend (Pin-Pack record #10 for
           RES-D3; ``recovery-drill-leaf-projection.md`` for
           RES-D5; ``schema-registry-spec.md`` for RES-D4).

Test inventory (>= 15 hermetic, all stdlib):

  T01  Spec file exists at the expected path.
  T02  Each RES-Dn (n=1..5) carries a §6.n.1 sub-heading.
  T03  RES-D1 sample block: fenced yaml block exists and
       contains 'identity-substrate-version' and
       '0.4.4-draft-RES-D1'.
  T04  RES-D2 sample block: fenced yaml block exists and
       contains 'min-attenuation-depth' and '0.4.4-draft-RES-D2'.
  T05  RES-D3 sample block: fenced yaml block exists and
       contains 'WAKIR_BRIDGE_AUDIT_WRITER_BACKEND' and
       '0.4.4-draft-RES-D3'.
  T06  RES-D4 sample block: fenced yaml block exists and
       contains 'registry-pointer-frame' and '0.4.4-draft-RES-D4'.
  T07  RES-D5 sample block: fenced yaml block exists and
       contains 'shard-count' and '0.4.4-draft-RES-D5'.
  T08  Fence-balance per RES-Dn sample block: every '```yaml'
       opener has a matching '```' closer inside the §6.n
       sub-section.
  T09  Each sample block carries the RES-Dn anchor string
       at least twice (heading + in-block anchor) — the per-block
       coverage discipline pin.
  T10  RES-D3 sample block cites Pin-Pack record #10 anchor
       ('pin-pack-record-number: 10').
  T11  RES-D4 sample block cites the schema-registry-spec target
       ('schema-registry') and the federation backend
       ('route_registry').
  T12  RES-D5 sample block cites the v1 leaf-projection contract
       ('recovery-drill') and the back-compat verdict
       ('incomplete-projection').
  T13  Draft frontmatter still declares 'status:
       post-cutover-reserve-draft' (Tag-63 invariant preserved).
  T14  Draft frontmatter does NOT declare 'status:
       pre-cutover-freeze' (the freeze-seal MUST NOT pick the
       draft up as a second freeze-marker).
  T15  Source-of-truth direction §1 mentions Tag-64 coverage
       extension ('Tag-64 coverage extension').
  T16  §8 audit-conformance mentions the Tag-64 coverage suite
       ('test_wirelang_spec_v0_4_4_coverage_tag64').
  T17  v0.4.3 freeze-seal intact: SHA-256 of
       'wirelang-spec-v0-4-3.md' matches the value in
       'freeze-baseline.json'. Tag-64 promise: the coverage
       extension MUST NOT alter v0.4.3.
  T18  Tag-63 §6.n sub-sections (n=1..5) for RES-Dn are
       preserved verbatim at the heading level (the coverage
       extension is additive, not destructive).
  T19  Sample blocks are confined to §6 (non-normative scope):
       no §6.n.1 heading or RES-Dn-sample-anchor appears outside
       §6.

All tests are skip-if-absent for portability across worktrees.
No network, no real clone, no engine boot.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-4-draft.md"
SPEC_V043 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"
FREEZE_BASELINE = REPO_ROOT / "wirelang" / "specs" / "freeze-baseline.json"


# --------------------------------------------------------------- #
# Module-scope fixture: load the live draft text once.            #
# --------------------------------------------------------------- #


@pytest.fixture(scope="module")
def spec_text() -> str:
    if not SPEC_PATH.exists():
        pytest.skip(f"v0.4.4-draft not present at {SPEC_PATH}")
    return SPEC_PATH.read_text(encoding="utf-8")


def _extract_section_body(spec_text: str, section_anchor: str) -> str:
    """
    Slice ``spec_text`` from ``section_anchor`` (a substring that
    starts a heading line) until the next top-level heading at the
    same or higher depth, or EOF.

    Code-fence-aware: lines inside a fenced ```yaml block are
    ignored for heading-detection purposes (YAML comments starting
    with '# ' would otherwise be misread as Markdown headings).

    Stdlib-only; sufficient for the Tag-64 sample-block scope
    checks because §6.n.1 sub-headings live inside §6.n and §6.n
    lives inside §6.
    """
    idx = spec_text.find(section_anchor)
    if idx < 0:
        return ""
    # Determine the heading depth of section_anchor (count leading '#').
    line_start = spec_text.rfind("\n", 0, idx) + 1
    line = spec_text[line_start:spec_text.find("\n", line_start)]
    m = re.match(r"^(#+)\s", line)
    depth = len(m.group(1)) if m else 0
    if depth == 0:
        return ""
    # Walk forward to the next heading with depth <= this one
    # (closing the section). Track fenced-block state.
    end = len(spec_text)
    cursor = spec_text.find("\n", idx) + 1
    in_fence = False
    while cursor < len(spec_text):
        nl = spec_text.find("\n", cursor)
        ln = spec_text[cursor:nl] if nl >= 0 else spec_text[cursor:]
        # Toggle fence-state on lines starting with ``` (open or close).
        if ln.startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            m2 = re.match(r"^(#+)\s", ln)
            if m2 and len(m2.group(1)) <= depth:
                end = cursor
                break
        if nl < 0:
            break
        cursor = nl + 1
    return spec_text[line_start:end]


def _extract_frontmatter_block(spec_text: str) -> str:
    fences = [m.start() for m in re.finditer(r"^---\s*$", spec_text, re.MULTILINE)]
    assert len(fences) >= 2, "spec does not carry a frontmatter block"
    first_end = spec_text.find("\n", fences[0]) + 1
    return spec_text[first_end:fences[1]]


# --------------------------------------------------------------- #
# Axis A — Sample-Block Existence                                  #
# --------------------------------------------------------------- #


def test_T01_spec_file_exists():
    assert SPEC_PATH.exists(), f"Missing v0.4.4-draft at {SPEC_PATH}"


def test_T02_each_res_dn_carries_sub_sample_heading(spec_text: str):
    """RES-D1..RES-D5 each have a §6.n.1 sub-heading."""
    for n in range(1, 6):
        pat = rf"^####\s+6\.{n}\.1\s+Sample.*RES-D{n}"
        assert re.search(pat, spec_text, re.MULTILINE), (
            f"missing §6.{n}.1 sample heading for RES-D{n}"
        )


def _block_for_res_dn(spec_text: str, n: int) -> str:
    body = _extract_section_body(spec_text, f"#### 6.{n}.1 Sample")
    # Pull the first fenced yaml block.
    m = re.search(r"```yaml(.*?)```", body, re.DOTALL)
    if not m:
        return ""
    return m.group(1)


def test_T03_res_d1_sample_block(spec_text: str):
    blk = _block_for_res_dn(spec_text, 1)
    assert blk, "RES-D1 fenced yaml block missing"
    assert "identity-substrate-version" in blk
    assert "0.4.4-draft-RES-D1" in blk


def test_T04_res_d2_sample_block(spec_text: str):
    blk = _block_for_res_dn(spec_text, 2)
    assert blk, "RES-D2 fenced yaml block missing"
    assert "min-attenuation-depth" in blk
    assert "0.4.4-draft-RES-D2" in blk


def test_T05_res_d3_sample_block(spec_text: str):
    blk = _block_for_res_dn(spec_text, 3)
    assert blk, "RES-D3 fenced yaml block missing"
    assert "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND" in blk
    assert "0.4.4-draft-RES-D3" in blk


def test_T06_res_d4_sample_block(spec_text: str):
    blk = _block_for_res_dn(spec_text, 4)
    assert blk, "RES-D4 fenced yaml block missing"
    assert "registry-pointer-frame" in blk
    assert "0.4.4-draft-RES-D4" in blk


def test_T07_res_d5_sample_block(spec_text: str):
    blk = _block_for_res_dn(spec_text, 5)
    assert blk, "RES-D5 fenced yaml block missing"
    assert "shard-count" in blk
    assert "0.4.4-draft-RES-D5" in blk


# --------------------------------------------------------------- #
# Axis B — Canonical-Form Validity (shape-only)                   #
# --------------------------------------------------------------- #


def test_T08_fence_balance_per_res_dn_sub_section(spec_text: str):
    """
    Each §6.n sub-section must carry exactly one '```yaml' opener
    and one matching '```' closer for the §6.n.1 sample block.
    The RES-Dn parent §6.n itself contains no other code fences in
    the Tag-64 layout, so opener_count == closer_count - opener_count
    holds and both equal 1.
    """
    for n in range(1, 6):
        # Use the §6.n.1 sample sub-section explicitly so we count
        # fences only inside that scope.
        body = _extract_section_body(spec_text, f"#### 6.{n}.1 Sample")
        opener_count = len(re.findall(r"```yaml", body))
        all_fences = len(re.findall(r"```", body))
        assert opener_count == 1, (
            f"RES-D{n} §6.{n}.1 expects exactly one ```yaml fence; got {opener_count}"
        )
        # all_fences counts both '```yaml' and the closing '```'; 2 fence
        # marks total per balanced block.
        assert all_fences == 2, (
            f"RES-D{n} §6.{n}.1 expects exactly two fence marks (open+close); got {all_fences}"
        )


def test_T09_res_dn_anchor_at_least_twice(spec_text: str):
    """
    Per-block coverage discipline: each RES-Dn anchor MUST appear
    inside the §6.n.1 sub-section at least twice (heading mention +
    in-block 'X.X.X-draft-RES-Dn' candidate version anchor).
    """
    for n in range(1, 6):
        body = _extract_section_body(spec_text, f"#### 6.{n}.1 Sample")
        count = body.count(f"RES-D{n}")
        assert count >= 2, (
            f"RES-D{n} §6.{n}.1 expects >= 2 anchor mentions; got {count}"
        )


# --------------------------------------------------------------- #
# Axis C — Reference-Integrity to v0.4.3 (Parent-Anchor)          #
# --------------------------------------------------------------- #


def test_T10_res_d3_cites_pin_pack_record_10(spec_text: str):
    blk = _block_for_res_dn(spec_text, 3)
    assert blk, "RES-D3 sample block missing"
    assert "pin-pack-record-number: 10" in blk, (
        "RES-D3 sample MUST cite Pin-Pack record #10 anchor"
    )


def test_T11_res_d4_cites_schema_registry_targets(spec_text: str):
    blk = _block_for_res_dn(spec_text, 4)
    assert blk, "RES-D4 sample block missing"
    assert "schema-registry" in blk, (
        "RES-D4 sample MUST cite schema-registry target"
    )
    assert "route_registry" in blk, (
        "RES-D4 sample MUST cite route_registry federation backend"
    )


def test_T12_res_d5_cites_leaf_projection_and_back_compat(spec_text: str):
    blk = _block_for_res_dn(spec_text, 5)
    assert blk, "RES-D5 sample block missing"
    assert "recovery-drill" in blk, (
        "RES-D5 sample MUST cite recovery-drill leaf-projection contract"
    )
    assert "incomplete-projection" in blk, (
        "RES-D5 sample MUST pin the back-compat verdict"
    )


def test_T13_frontmatter_still_post_cutover_reserve_draft(spec_text: str):
    fm = _extract_frontmatter_block(spec_text)
    assert re.search(
        r"^status:\s*post-cutover-reserve-draft\s*$", fm, re.MULTILINE
    ), "Tag-63 status invariant must be preserved"


def test_T14_frontmatter_does_not_carry_pre_cutover_freeze(spec_text: str):
    fm = _extract_frontmatter_block(spec_text)
    assert "status: pre-cutover-freeze" not in fm, (
        "Tag-64 extension MUST NOT add a freeze-marker status"
    )


def test_T15_source_of_truth_mentions_tag_64_coverage(spec_text: str):
    assert "Tag-64 coverage extension" in spec_text, (
        "§1 source-of-truth direction MUST mention Tag-64 coverage extension"
    )


def test_T16_audit_conformance_mentions_tag_64_suite(spec_text: str):
    assert "test_wirelang_spec_v0_4_4_coverage_tag64" in spec_text, (
        "§8 audit-conformance MUST reference the Tag-64 coverage suite"
    )


def test_T17_v0_4_3_freeze_seal_intact():
    """
    The Tag-64 coverage extension touches v0.4.4-draft ONLY. The
    v0.4.3 freeze-seal MUST remain intact. Skip-if-absent for
    worktrees that don't carry the baseline.
    """
    if not SPEC_V043.exists():
        pytest.skip(f"v0.4.3 spec not present at {SPEC_V043}")
    if not FREEZE_BASELINE.exists():
        pytest.skip(f"freeze-baseline.json not present at {FREEZE_BASELINE}")
    baseline = json.loads(FREEZE_BASELINE.read_text(encoding="utf-8"))
    expected_sha = (
        baseline.get("baseline", {}).get("sha256")
        or baseline.get("sha256")
    )
    if not expected_sha:
        pytest.skip("freeze-baseline.json carries no sha256 field")
    actual = hashlib.sha256(SPEC_V043.read_bytes()).hexdigest()
    assert actual == expected_sha, (
        f"v0.4.3 SHA-256 drift detected: expected {expected_sha}, "
        f"got {actual}. Tag-64 MUST NOT alter v0.4.3."
    )


def test_T18_tag63_res_dn_sub_sections_preserved(spec_text: str):
    """
    The Tag-64 extension is ADDITIVE: it adds §6.n.1 sub-headings
    under each §6.n RES-Dn sub-section. The §6.n RES-Dn headings
    themselves MUST remain verbatim (Tag-63 invariant preserved).
    """
    for n in range(1, 6):
        pat = rf"^###\s+6\.{n}\s+RES-D{n}:"
        assert re.search(pat, spec_text, re.MULTILINE), (
            f"§6.{n} RES-D{n} parent heading missing (Tag-63 invariant)"
        )


def test_T19_sample_anchors_confined_to_section_6(spec_text: str):
    """
    Per draft-isolation invariant §2: §6 is the non-normative
    reserve-substrate scope. The Tag-64 sample blocks MUST live
    inside §6. We pin this by checking that no §6.n.1 heading and
    no '0.4.4-draft-RES-Dn' anchor appears outside §6.
    """
    # Slice §6 body.
    idx_sec6 = spec_text.find("## 6. Reserve-substrate")
    idx_sec7 = spec_text.find("## 7. Backward compatibility")
    assert idx_sec6 > 0, "§6 header not found"
    assert idx_sec7 > idx_sec6, "§7 header not after §6"
    sec6 = spec_text[idx_sec6:idx_sec7]
    outside_sec6 = spec_text[:idx_sec6] + spec_text[idx_sec7:]

    # All §6.n.1 sub-headings live inside §6.
    for n in range(1, 6):
        sub_pat = rf"^####\s+6\.{n}\.1\s+Sample"
        in_sec6 = re.search(sub_pat, sec6, re.MULTILINE)
        out_sec6 = re.search(sub_pat, outside_sec6, re.MULTILINE)
        assert in_sec6, f"§6.{n}.1 heading not found inside §6"
        assert not out_sec6, (
            f"§6.{n}.1 heading leaked outside §6 — sample-block scope violated"
        )

    # All candidate-version anchors live inside §6 (excluding §1 reference
    # to the suite — the §1 text talks ABOUT the samples but does not carry
    # them). §8 may reference the suite filename; that is not a candidate
    # anchor (no 'RES-Dn' suffix on its own line).
    for n in range(1, 6):
        anchor = f"0.4.4-draft-RES-D{n}"
        assert anchor in sec6, f"candidate-anchor {anchor} missing in §6"
        # The candidate-anchor MUST NOT appear in §7..§9 (the
        # carry-forward / backward-compat / audit sections).
        # Sections after §6:
        sec_after = spec_text[idx_sec7:]
        assert anchor not in sec_after, (
            f"candidate-anchor {anchor} leaked into post-§6 sections"
        )
