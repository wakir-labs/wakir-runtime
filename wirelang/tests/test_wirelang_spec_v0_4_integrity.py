# SPDX-License-Identifier: Apache-2.0
"""Hermetic spec-integrity tests for ``wirelang/specs/wirelang-spec-v0-4.md``.

Phase: Phase-3-trigger-window (Tag-45)
Owner: role: wirelang-spec-owner (Dev-Engineering-2 / Wirelang)

These tests are **stdlib-only**, do **not** import the Wirelang runtime,
do **not** parse YAML frontmatter via a library, and do **not** depend
on network or filesystem state outside the repo. They verify structural
invariants of the v0.4 consolidation refresh:

- Frontmatter pins (version, supersedes, status, license).
- Section heading inventory (sections 1 through 13).
- Phase-3a foundation Rust-crate count (15 crates, §3.1).
- Phase-3b ENV-flag-schema component count (9 components, §4.1).
- Phase-3c welle count (7 wellen, §5.1).
- Bug-42-fix-anchor cross-reference (§6 anchors v0.2.1 §13).
- Backward-compatibility statement v0.3 → v0.4 (§9.2 normative).
- NATS-JetStream-subjects-audit baseline cross-reference (§8).
- Brand-Guide §9 compliance check (role-strings only, allow-listed
  clear-name appearances only in §11 historical-attribution context).
- License + SPDX header (CC-BY-4.0).

A test breaking is a spec-integrity-regression signal, not a runtime
regression. Fix the spec, not the test, unless the test itself is wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


SPEC_PATH = (
    Path(__file__).resolve().parents[1] / "specs" / "wirelang-spec-v0-4.md"
)


@pytest.fixture(scope="module")
def spec_text() -> str:
    assert SPEC_PATH.exists(), f"spec not found at {SPEC_PATH}"
    return SPEC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def spec_lines(spec_text: str) -> list[str]:
    return spec_text.splitlines()


def _frontmatter_block(spec_text: str) -> dict[str, str]:
    """Extract the YAML-frontmatter key/value pairs without a YAML library."""
    # The spec opens with an HTML comment (license) then a YAML
    # frontmatter block delimited by '---' on its own line.
    lines = spec_text.splitlines()
    start = None
    end = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if start is None:
                start = i
            else:
                end = i
                break
    assert start is not None and end is not None, "frontmatter delimiters missing"
    fm: dict[str, str] = {}
    for raw in lines[start + 1 : end]:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        key, _, value = raw.partition(":")
        fm[key.strip()] = value.strip()
    return fm


# -------------------------------------------------------------------------
# T-1 / frontmatter pins
# -------------------------------------------------------------------------
# REUSE-IgnoreStart
def test_t1_frontmatter_pins(spec_text: str) -> None:
    fm = _frontmatter_block(spec_text)
    assert fm.get("spec") == "wirelang"
    assert fm.get("version") == "0.4.0"
    assert fm.get("supersedes") == "0.3.0"
    assert fm.get("status") == "draft"
    assert fm.get("license") == "CC-BY-4.0"
    assert fm.get("replaced-by") == "null"
# REUSE-IgnoreEnd


# -------------------------------------------------------------------------
# T-2 / SPDX + license header
# -------------------------------------------------------------------------
# REUSE-IgnoreStart
def test_t2_spdx_license_header(spec_text: str) -> None:
    assert "SPDX-License-Identifier: CC-BY-4.0" in spec_text
    assert "Creative Commons Attribution" in spec_text
    assert "creativecommons.org/licenses/by/4.0" in spec_text
# REUSE-IgnoreEnd


# -------------------------------------------------------------------------
# T-3 / section heading inventory
# -------------------------------------------------------------------------
def test_t3_section_heading_inventory(spec_lines: list[str]) -> None:
    headings = [ln for ln in spec_lines if ln.startswith("## ")]
    # Expected sections 1..13 plus their titles. We do not require exact
    # title strings but we do require the numbering 1..13 to appear in
    # order with no gaps.
    section_numbers = []
    for h in headings:
        match = re.match(r"^## (\d+)\.\s", h)
        if match:
            section_numbers.append(int(match.group(1)))
    assert section_numbers == list(range(1, 14)), (
        f"expected sections 1..13 in order, got {section_numbers}"
    )


# -------------------------------------------------------------------------
# T-4 / Phase-3a foundation: 15 Rust-crate rows
# -------------------------------------------------------------------------
def test_t4_phase_3a_fifteen_crates(spec_text: str) -> None:
    # The §3.1 table has rows numbered 1..15. We count rows that begin
    # with "| <digits> |" inside §3.1 (between "### 3.1 Catalogue" and
    # the next "### " heading).
    catalog_marker = "### 3.1 Catalogue"
    assert catalog_marker in spec_text
    after = spec_text.split(catalog_marker, 1)[1]
    next_heading = after.find("### ")
    assert next_heading > 0, "section 3.1 missing a sibling sub-heading"
    block = after[:next_heading]
    rows = re.findall(r"^\|\s*(\d+)\s*\|", block, flags=re.MULTILINE)
    nums = [int(r) for r in rows]
    assert nums == list(range(1, 16)), (
        f"expected 15 numbered crate rows 1..15 in §3.1, got {nums}"
    )


# -------------------------------------------------------------------------
# T-5 / Phase-3b ENV-flag schema: 9 component rows
# -------------------------------------------------------------------------
def test_t5_phase_3b_nine_components(spec_text: str) -> None:
    nine_marker = "### 4.1 The nine components"
    assert nine_marker in spec_text
    after = spec_text.split(nine_marker, 1)[1]
    next_heading = after.find("### ")
    assert next_heading > 0
    block = after[:next_heading]
    rows = re.findall(r"^\|\s*(\d+)\s*\|", block, flags=re.MULTILINE)
    nums = [int(r) for r in rows]
    assert nums == list(range(1, 10)), (
        f"expected 9 numbered component rows 1..9 in §4.1, got {nums}"
    )
    # Spot-check: foundation rows 8 and 9 are marked "(not switchable)"
    foundation_segment = "\n".join(
        line for line in block.splitlines() if line.startswith("| 8 |") or line.startswith("| 9 |")
    )
    assert foundation_segment.count("(not switchable)") == 2


# -------------------------------------------------------------------------
# T-6 / Phase-3c welle inventory: 7 wellen
# -------------------------------------------------------------------------
def test_t6_phase_3c_seven_wellen(spec_text: str) -> None:
    welle_marker = "### 5.1 Welle inventory"
    assert welle_marker in spec_text
    after = spec_text.split(welle_marker, 1)[1]
    next_heading = after.find("### ")
    assert next_heading > 0
    block = after[:next_heading]
    rows = re.findall(r"^\|\s*(\d+)\s*\|", block, flags=re.MULTILINE)
    nums = [int(r) for r in rows]
    assert nums == list(range(1, 8)), (
        f"expected 7 numbered welle rows 1..7 in §5.1, got {nums}"
    )


# -------------------------------------------------------------------------
# T-7 / Bug-42-fix-anchor: publish-mode-contract + Adapter-B reference
# -------------------------------------------------------------------------
def test_t7_bug_42_anchor_present(spec_text: str) -> None:
    # The §6 title must reference both the publish-mode-contract and
    # Adapter-B, and the section must cross-reference v0.2.1 §13.
    title_present = re.search(
        r"^## 6\.\s+Bug-42 fix anchor: publish-mode-contract \+ Adapter-B",
        spec_text,
        flags=re.MULTILINE,
    )
    assert title_present, "missing §6 Bug-42 anchor title"
    assert "v0.2.1 §13" in spec_text
    # The three named adapters must each appear at least once.
    for adapter in ("Adapter A.", "Adapter B.", "Adapter C."):
        assert adapter in spec_text, f"missing adapter declaration: {adapter}"
    # The publish-mode CLI flag must be referenced.
    assert "--publish-mode" in spec_text
    # The Tag-41 PR #265 anchor is referenced (closure stamp).
    assert "PR #265" in spec_text


# -------------------------------------------------------------------------
# T-8 / Backward-compatibility v0.3 → v0.4 normative statement
# -------------------------------------------------------------------------
def test_t8_backcompat_v03_to_v04(spec_text: str) -> None:
    assert "v0.3 → v0.4" in spec_text
    backcompat_marker = "### 9.2 Backward-compatibility note v0.3 → v0.4"
    assert backcompat_marker in spec_text
    after = spec_text.split(backcompat_marker, 1)[1]
    next_heading_idx = after.find("### ")
    assert next_heading_idx > 0
    block = after[:next_heading_idx]
    # MUST/SHOULD/MAY conformance keyword presence.
    assert "MUST accept" in block, "missing normative MUST in §9.2"
    # All historical versions accepted (the rule from §1.1).
    for version in ("0.4.0", "0.3", "0.2.1", "0.2.0", "0.1.0"):
        assert version in spec_text, f"version {version!r} not referenced anywhere"


# -------------------------------------------------------------------------
# T-9 / NATS-JetStream-subjects-audit baseline cross-reference (§8)
# -------------------------------------------------------------------------
def test_t9_nats_subjects_audit_baseline(spec_text: str) -> None:
    section_title = "## 8. NATS-JetStream subjects audit baseline"
    assert section_title in spec_text
    # Substrate elements must all be referenced.
    expected_refs = [
        "scripts/audit/nats-jetstream-subjects-audit.py",
        "tests/audit/test_nats_jetstream_subjects_audit.py",
        "reports/audit/2026-05-18-nats-jetstream-subjects-audit.md",
        ".github/workflows/nats-jetstream-subjects-audit.yml",
    ]
    for ref in expected_refs:
        assert ref in spec_text, f"missing audit substrate reference: {ref}"
    # Classification vocabulary
    for token in (
        "PUB_CORE",
        "PUB_JS",
        "SUB_CORE",
        "SUB_JS_PULL",
        "SUB_JS_PUSH",
        "UNCLASSIFIED",
    ):
        assert token in spec_text, f"missing audit classification token: {token}"


# -------------------------------------------------------------------------
# T-10 / Brand-Guide §9 compliance: no unauthorised clear-name mentions
# -------------------------------------------------------------------------
def test_t10_brand_guide_section_9(spec_text: str) -> None:
    # Clear-name appearances are only allowed in §11 historical-author
    # attribution context. The two allow-listed names are "Reza Tehrani"
    # and "Selin Çelik" (file-author metadata for ADR-prep docs).
    # No other clear-name strings should appear in the spec body.
    allow_list = {"Reza Tehrani", "Selin Çelik"}
    # Common Wakir clear-name patterns we explicitly check are absent.
    forbidden_examples = [
        "Mira Kessler",
        "Tomás Reinhart",
        "Aisha Rahman",
        "Henrik Voss",
        "Priya Nakamura",
        "Amara Osei",
        "Kai Nakamura",
        "Noa",
    ]
    for name in forbidden_examples:
        assert name not in spec_text, (
            f"Brand-Guide §9 violation: forbidden clear-name {name!r} in spec body"
        )
    # The allow-listed names must appear only inside §11 (Brand-Guide
    # compliance section). We split the spec at the §11 heading and
    # verify the body-before-§11 has no allow-list occurrences either.
    section_11_heading = "## 11. Brand-Guide §9 compliance"
    assert section_11_heading in spec_text
    pre_11 = spec_text.split(section_11_heading, 1)[0]
    for name in allow_list:
        assert name not in pre_11, (
            f"clear-name {name!r} appears outside §11 historical-attribution context"
        )


# -------------------------------------------------------------------------
# T-11 / Reference inventory: required Phase-3 references resolve to
# existing repo paths (filesystem hermetic check).
# -------------------------------------------------------------------------
def test_t11_phase_3_references_exist(spec_text: str) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    # Pairs of (filesystem-rel-from-repo-root, spec-cite-form). The spec
    # cites Wirelang-internal specs by ``specs/<name>.md`` (i.e., relative
    # to the wirelang module) and out-of-module artefacts by the
    # ``docs/...`` path from repo root.
    required: list[tuple[str, str]] = [
        ("wirelang/specs/wirelang-spec-v0-2.md", "specs/wirelang-spec-v0-2.md"),
        ("wirelang/specs/identity-substrate.md", "specs/identity-substrate.md"),
        ("wirelang/specs/nats-subject-mapping-v1.md", "specs/nats-subject-mapping-v1.md"),
        ("wirelang/specs/schema-registry-spec.md", "specs/schema-registry-spec.md"),
        ("wirelang/specs/datalog-caveat-vocabulary.md", "specs/datalog-caveat-vocabulary.md"),
        ("wirelang/specs/datalog-caveat-vocabulary-phase-2.md", "specs/datalog-caveat-vocabulary-phase-2.md"),
        ("docs/decisions/persona-engine-rust-rewrite-roadmap.md", "docs/decisions/persona-engine-rust-rewrite-roadmap.md"),
        ("docs/decisions/rust-rewrite-crate-wahlen.md", "docs/decisions/rust-rewrite-crate-wahlen.md"),
        ("docs/quality-gates/phase-3c-acceptance-criteria.md", "docs/quality-gates/phase-3c-acceptance-criteria.md"),
        ("docs/audit/nats-jetstream-subjects-audit.md", "docs/audit/nats-jetstream-subjects-audit.md"),
    ]
    for fs_rel, cite_form in required:
        assert (repo_root / fs_rel).exists(), (
            f"spec references {fs_rel} which does not exist in the repo"
        )
        assert cite_form in spec_text, (
            f"spec body does not cite {cite_form} (filesystem path {fs_rel})"
        )


# -------------------------------------------------------------------------
# T-12 / Foundation crate Rust-only contract (§3.3): #1, #2, #15 are
# the three named foundation crates.
# -------------------------------------------------------------------------
def test_t12_foundation_crates_rust_only(spec_text: str) -> None:
    section_marker = "### 3.3 Foundation crates: pre-cutover Rust-only"
    assert section_marker in spec_text
    after = spec_text.split(section_marker, 1)[1]
    next_heading_idx = after.find("### ")
    assert next_heading_idx > 0
    block = after[:next_heading_idx]
    # Three named foundation crates must each appear in §3.3.
    foundation_crates = [
        "persona-canonical-form",
        "persona-canonical-form-yaml",
        "persona-engine-anchor-emitter",
    ]
    for crate in foundation_crates:
        assert crate in block, f"foundation crate {crate} not declared in §3.3"


# -------------------------------------------------------------------------
# T-13 / ENV-flag value-space declaration (§4.2): the three values
# python / rust / parity must all appear.
# -------------------------------------------------------------------------
def test_t13_env_flag_value_space(spec_text: str) -> None:
    section_marker = "### 4.2 ENV-flag value space"
    assert section_marker in spec_text
    after = spec_text.split(section_marker, 1)[1]
    next_heading_idx = after.find("### ")
    assert next_heading_idx > 0
    block = after[:next_heading_idx]
    # Each value must be listed at the start of a bullet in §4.2.
    for value in ("`python`", "`rust`", "`parity`"):
        assert value in block, f"ENV-flag value {value} missing in §4.2"
    # The default-by-welle-state rule is the explicit closure.
    assert "default-by-welle-state" in spec_text


# -------------------------------------------------------------------------
# T-14 / Welle-substrate heptad (§5.2): exactly seven elements per welle.
# -------------------------------------------------------------------------
def test_t14_welle_substrate_heptad(spec_text: str) -> None:
    section_marker = "### 5.2 Per-welle substrate elements"
    assert section_marker in spec_text
    after = spec_text.split(section_marker, 1)[1]
    next_heading_idx = after.find("### ")
    assert next_heading_idx > 0
    block = after[:next_heading_idx]
    # Numbered list 1..7
    nums = re.findall(r"^(\d+)\.\s+\*\*", block, flags=re.MULTILINE)
    assert [int(n) for n in nums] == list(range(1, 8)), (
        f"expected 7 numbered heptad elements, got {nums}"
    )


# -------------------------------------------------------------------------
# T-15 / Asymmetric per-component rollback path (§9.4) normative
# commitment is present.
# -------------------------------------------------------------------------
def test_t15_asymmetric_rollback_path(spec_text: str) -> None:
    section_marker = "### 9.4 Asymmetric per-component rollback path"
    assert section_marker in spec_text
    after = spec_text.split(section_marker, 1)[1]
    next_heading_idx_h2 = after.find("\n## ")
    next_heading_idx_h3 = after.find("\n### ")
    candidates = [
        idx for idx in (next_heading_idx_h2, next_heading_idx_h3) if idx > 0
    ]
    assert candidates, "section 9.4 missing a successor heading"
    block = after[: min(candidates)]
    # The spec must commit to "spec is not re-issued" under rollback.
    assert "not** re-issued" in block or "not re-issued" in block, (
        "§9.4 missing normative no-spec-reissue-under-rollback commitment"
    )
    assert "mixed-backend" in block or "mixed-\nbackend" in block, (
        "§9.4 missing mixed-backend conformance allowance"
    )
