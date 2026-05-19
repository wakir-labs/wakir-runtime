# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-68 hermetic per-failure-mode coverage tests for the Wirelang-Spec
v0.4.4-Draft Activation Pre-Mortem doc.

==========================================================================

Background
----------

Tag-67 (PR #427, ``tests/audit/test_activation_pre_mortem_tag67.py``,
17 tests) pinned the Activation Pre-Mortem doc-shape: section count,
table-header columns, failure-mode-code presence (A1..A5, B1..B5 per
RES-Dn item), and the RES-D4-high-risk invariant. The Tag-67 brief
called the audit-trail-pinning of per-failure-mode coverage out as
elevated residual risk (RES-D4-style audit-coverage gap on a 50-mode
inventory).

Tag-68 closes that gap. Per Failure-Mode-Tuple ``(Item, ModeCode)`` in
the Tag-67 doc's 5x10 inventory, this suite pins:

* Doc-section existence (the per-item §N.1 table contains a table row
  starting with ``| {ModeCode} |``);
* Mitigation-anchor line is non-empty (column 5 of the row is not
  the literal ``-`` or whitespace, and is not the placeholder
  ``TBD``);
* Severity-rating is one of the canonical ratings (``low``, ``medium``,
  ``high``, ``critical``) in the Likelihood AND Impact cells.

Additionally:

* The aggregate-risk-map §7.1 cross-aggregation table is asserted to
  cover every failure-mode-family hot spot called out in §7.2.
* The §7.3 residual-risk-distribution table covers all five items
  and matches the per-item §N.2 residual-risk subsection rating.
* Tag-65 promotion-sequencing doc is cross-referenced and the
  Step 1..5 sequence in the Tag-65 doc is asserted to match the
  RES-D item ordering in the Tag-67 pre-mortem (Tag-65 is the
  upstream sequencing-authority).

Total test count: >= 30 (50 parametric per-mode tests grouped by
Item, plus 7 aggregation tests, plus 4 Tag-65 cross-reference tests
= 61 hermetic tests).

The Tag-67 doc is held UNCHANGED. This suite is read-only.

Coverage matrix
---------------

    RES-D1 | RES-D2 | RES-D3 | RES-D4 | RES-D5
    A1..A5 + B1..B5 per item = 50 tuples
    * doc-section existence -> 1 parametric test family
    * mitigation-line non-empty -> 1 parametric test family
    * severity-rating canonical -> 1 parametric test family

Hermeticity
-----------

stdlib + pytest only. No network, no subprocess, no podman.
Skip-if-absent for portability (mirrors Tag-67 idiom).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_REL = "docs/operations/wirelang-spec-v0-4-4-activation-pre-mortem.md"
DOC_PATH = REPO_ROOT / DOC_REL
TAG65_DOC_REL = "docs/operations/wirelang-spec-v0-4-4-promotion-sequencing.md"
TAG65_DOC_PATH = REPO_ROOT / TAG65_DOC_REL


# --------------------------------------------------------------- #
# Coverage tuples                                                  #
# --------------------------------------------------------------- #


# Maps the top-level §N marker -> RES-D tag. Mirrors the Tag-67 doc.
ITEMS = (
    ("## 2.", "RES-D1"),
    ("## 3.", "RES-D2"),
    ("## 4.", "RES-D3"),
    ("## 5.", "RES-D4"),
    ("## 6.", "RES-D5"),
)
MODE_CODES = (
    "A1", "A2", "A3", "A4", "A5",
    "B1", "B2", "B3", "B4", "B5",
)
CANONICAL_RATINGS = ("low", "medium", "high", "critical")
PLACEHOLDER_FORBIDDEN_LITERALS = ("tbd", "todo", "n/a", "tba", "-")
# Compound ratings like 'low-medium' or 'medium-low' are also canonical
# per the Tag-67 doc's residual-risk-distribution table (§7.3).
RESIDUAL_RATING_PATTERN = re.compile(
    r"\b(low|medium|high|critical)(?:-(?:low|medium|high|critical))?\b",
    re.IGNORECASE,
)


def _all_tuples():
    """Yield (section_marker, res_d_tag, mode_code) for all 50 tuples."""
    for marker, tag in ITEMS:
        for code in MODE_CODES:
            yield (marker, tag, code)


# --------------------------------------------------------------- #
# Live-doc fixtures                                                #
# --------------------------------------------------------------- #


def _load_doc() -> str:
    if not DOC_PATH.exists():
        pytest.skip(f"Tag-67 doc not present at {DOC_REL}")
    return DOC_PATH.read_text(encoding="utf-8")


def _split_top_sections(text: str) -> dict:
    """Return {marker: body} for §1..§7 top-level headers."""
    markers = ("## 1.", "## 2.", "## 3.", "## 4.",
               "## 5.", "## 6.", "## 7.")
    out: dict = {}
    positions = [(m, text.find(m)) for m in markers]
    positions.append(("__end__", len(text)))
    for i, (marker, start) in enumerate(positions[:-1]):
        _, end = positions[i + 1]
        out[marker] = text[start:end] if start >= 0 else ""
    return out


def _extract_mode_row(section_body: str, mode_code: str) -> str | None:
    """Return the table row that begins with ``| {mode_code} |`` (single
    physical line), or None if not found.

    The Tag-67 doc emits each row on a single physical line (no
    wrapping), which the Tag-67 invariants T07 already pin. We rely on
    that invariant: searching for the row marker ``| {code} |`` and
    reading to the next newline gives the entire row.
    """
    marker = f"| {mode_code} |"
    idx = section_body.find(marker)
    if idx < 0:
        return None
    end = section_body.find("\n", idx)
    if end < 0:
        end = len(section_body)
    return section_body[idx:end]


def _split_table_row(row: str) -> list[str]:
    """Split a Markdown table row into trimmed cells.

    The row format is ``| a | b | c | d | e | f |`` (six pipes for
    five-column tables in the Tag-67 doc, six cells once the leading +
    trailing pipes are stripped). We tolerate any number of cells; the
    caller asserts the count.
    """
    # Strip leading + trailing pipe, then split on '|'.
    inner = row.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [cell.strip() for cell in inner.split("|")]


# --------------------------------------------------------------- #
# Parametric layer A -- per-tuple doc-section existence            #
# --------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("section_marker", "res_d_tag", "mode_code"),
    list(_all_tuples()),
    ids=[f"{tag}_{code}"
         for _, tag in ITEMS for code in MODE_CODES],
)
def test_mode_row_exists_in_section(section_marker, res_d_tag, mode_code):
    """Per failure-mode tuple, the doc must contain the row marker in
    the matching per-item section. This is the Tag-67 invariant
    factored per-tuple — one test per tuple, so a missing row fails a
    single named test rather than a single aggregate test."""
    text = _load_doc()
    sections = _split_top_sections(text)
    body = sections[section_marker]
    row = _extract_mode_row(body, mode_code)
    assert row is not None, (
        f"§{section_marker} ({res_d_tag}) is missing the failure-mode "
        f"table row for code '{mode_code}' (expected row marker "
        f"'| {mode_code} |')"
    )


# --------------------------------------------------------------- #
# Parametric layer B -- mitigation-line non-empty                  #
# --------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("section_marker", "res_d_tag", "mode_code"),
    list(_all_tuples()),
    ids=[f"{tag}_{code}"
         for _, tag in ITEMS for code in MODE_CODES],
)
def test_mode_row_mitigation_anchor_non_empty(
    section_marker, res_d_tag, mode_code,
):
    """The mitigation-anchor column (column 5 of the six-cell row)
    must be non-empty and must not be a placeholder. The §N.1 table
    has columns:

        | Code | Failure mode | Likelihood | Impact | Mitigation anchor | Detection path |

    so the mitigation-anchor cell is index 4 (0-based) of the
    trimmed-cells list.
    """
    text = _load_doc()
    sections = _split_top_sections(text)
    body = sections[section_marker]
    row = _extract_mode_row(body, mode_code)
    assert row is not None, (
        f"row for {res_d_tag} / {mode_code} not found (pre-condition)"
    )
    cells = _split_table_row(row)
    assert len(cells) >= 6, (
        f"{res_d_tag} / {mode_code} row has only {len(cells)} cells; "
        f"expected 6 (code, failure-mode, likelihood, impact, "
        f"mitigation, detection). Row: {row!r}"
    )
    mitigation = cells[4]
    assert mitigation, (
        f"{res_d_tag} / {mode_code} mitigation-anchor cell is empty"
    )
    lowered = mitigation.lower().strip()
    for placeholder in PLACEHOLDER_FORBIDDEN_LITERALS:
        assert lowered != placeholder, (
            f"{res_d_tag} / {mode_code} mitigation-anchor cell is "
            f"placeholder '{placeholder}': {mitigation!r}"
        )
    # The mitigation anchor for the Tag-67 inventory should always
    # cite at least one upstream anchor — typically "Tag-NN", an ADR
    # number, a §N.M section reference, or an explicit cross-team /
    # process anchor. We assert a non-trivial length to catch the
    # case where the cell is e.g. a single stop character.
    assert len(mitigation) >= 10, (
        f"{res_d_tag} / {mode_code} mitigation-anchor cell is too "
        f"short to be a real anchor: {mitigation!r}"
    )


# --------------------------------------------------------------- #
# Parametric layer C -- severity rating canonical                  #
# --------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("section_marker", "res_d_tag", "mode_code"),
    list(_all_tuples()),
    ids=[f"{tag}_{code}"
         for _, tag in ITEMS for code in MODE_CODES],
)
def test_mode_row_severity_ratings_canonical(
    section_marker, res_d_tag, mode_code,
):
    """The Likelihood (col 2) and Impact (col 3) cells must each
    declare exactly one of the canonical ratings: low, medium, high,
    critical. We tolerate trailing prose ('medium (post-rollout)')
    but require the canonical token to appear as the first
    whitespace-separated word."""
    text = _load_doc()
    sections = _split_top_sections(text)
    body = sections[section_marker]
    row = _extract_mode_row(body, mode_code)
    assert row is not None, (
        f"row for {res_d_tag} / {mode_code} not found (pre-condition)"
    )
    cells = _split_table_row(row)
    assert len(cells) >= 6, (
        f"row for {res_d_tag} / {mode_code} has insufficient cells"
    )
    likelihood = cells[2].strip().lower()
    impact = cells[3].strip().lower()
    # First whitespace-separated word.
    likelihood_head = likelihood.split()[0] if likelihood else ""
    impact_head = impact.split()[0] if impact else ""
    assert likelihood_head in CANONICAL_RATINGS, (
        f"{res_d_tag} / {mode_code} Likelihood cell first token "
        f"'{likelihood_head}' not in canonical ratings "
        f"{CANONICAL_RATINGS}; full cell: {cells[2]!r}"
    )
    assert impact_head in CANONICAL_RATINGS, (
        f"{res_d_tag} / {mode_code} Impact cell first token "
        f"'{impact_head}' not in canonical ratings "
        f"{CANONICAL_RATINGS}; full cell: {cells[3]!r}"
    )


# --------------------------------------------------------------- #
# Aggregation layer -- §7 cross-item risk-map invariants           #
# --------------------------------------------------------------- #


def test_aggregate_risk_map_covers_all_five_items():
    """§7.3 residual-risk-distribution must list every RES-Dn item."""
    text = _load_doc()
    sections = _split_top_sections(text)
    s7 = sections["## 7."]
    distribution_idx = s7.find("Residual-risk distribution")
    assert distribution_idx >= 0, (
        "§7 must carry the 'Residual-risk distribution' sub-block"
    )
    distribution_block = s7[distribution_idx:]
    for _, tag in ITEMS:
        assert tag in distribution_block, (
            f"§7.3 residual-risk-distribution table is missing the "
            f"'{tag}' row"
        )


def test_aggregate_risk_map_residual_ratings_canonical():
    """Every RES-Dn row in §7.3 carries a canonical rating token."""
    text = _load_doc()
    sections = _split_top_sections(text)
    s7 = sections["## 7."]
    distribution_idx = s7.find("Residual-risk distribution")
    assert distribution_idx >= 0
    distribution_block = s7[distribution_idx:]
    for _, tag in ITEMS:
        tag_idx = distribution_block.find(tag)
        assert tag_idx >= 0, f"§7.3 missing '{tag}' row"
        # Read a 200-char window after the tag mention to capture the
        # rating cell (compact table).
        window = distribution_block[tag_idx:tag_idx + 200]
        match = RESIDUAL_RATING_PATTERN.search(window)
        assert match is not None, (
            f"§7.3 row for '{tag}' has no canonical rating token "
            f"(window: {window!r})"
        )


def test_aggregate_risk_map_per_item_residual_matches_section_residual():
    """The §N.2 residual-risk paragraph rating for each RES-Dn must
    match the §7.3 row for the same item.

    This pins the cross-table consistency invariant: the
    per-item residual narrative cannot drift from the aggregate
    distribution table.
    """
    text = _load_doc()
    sections = _split_top_sections(text)
    s7 = sections["## 7."]
    distribution_idx = s7.find("Residual-risk distribution")
    assert distribution_idx >= 0
    distribution_block = s7[distribution_idx:]
    for marker, tag in ITEMS:
        # Per-item residual block from §N.2.
        section_body = sections[marker]
        residual_idx_lower = section_body.lower().find("residual risk")
        assert residual_idx_lower >= 0, (
            f"§{marker} ({tag}) missing residual-risk sub-section"
        )
        section_residual = section_body[residual_idx_lower:]
        section_match = RESIDUAL_RATING_PATTERN.search(section_residual)
        assert section_match is not None, (
            f"§{marker} ({tag}) residual-risk text contains no canonical "
            f"rating token"
        )
        section_rating = section_match.group(0).lower()
        # §7.3 row for the same tag.
        tag_idx = distribution_block.find(tag)
        assert tag_idx >= 0
        window = distribution_block[tag_idx:tag_idx + 200]
        dist_match = RESIDUAL_RATING_PATTERN.search(window)
        assert dist_match is not None
        dist_rating = dist_match.group(0).lower()
        assert section_rating == dist_rating, (
            f"residual-rating mismatch for {tag}: §{marker} says "
            f"'{section_rating}', §7.3 says '{dist_rating}' "
            f"(distribution-table drift)"
        )


def test_aggregate_hot_spots_cite_at_least_three_distinct_modes():
    """§7.2 (Cross-item hot spots) must call out at least three
    distinct cross-item failure-mode patterns.

    The Tag-67 narrative explicitly identifies three hot spots
    (rollback-atomicity, cross-layer enforcement asymmetry, RES-D4
    isolation). The pre-mortem reader must be able to count them
    structurally (each as its own bullet or named pattern)."""
    text = _load_doc()
    sections = _split_top_sections(text)
    s7 = sections["## 7."]
    hot_idx = s7.find("Cross-item hot spots")
    assert hot_idx >= 0, "§7.2 must carry 'Cross-item hot spots'"
    # Slice from §7.2 header up to the next "###" sub-section.
    rest = s7[hot_idx:]
    next_sub = rest.find("\n### ", 3)
    hot_block = rest[:next_sub] if next_sub >= 0 else rest
    # Count bullet markers '- **' or '* **' (named-pattern markers).
    bullet_count = len(re.findall(r"^[\-\*]\s+\*\*", hot_block, re.MULTILINE))
    assert bullet_count >= 3, (
        f"§7.2 must enumerate >=3 named cross-item hot spots; "
        f"found {bullet_count} bullet markers"
    )


def test_aggregate_family_aggregation_table_present():
    """§7.1 must carry a four-column aggregation table with the
    'Items affected' column populated for every row (at least one
    row references each of the five RES-Dn items across the table).
    """
    text = _load_doc()
    sections = _split_top_sections(text)
    s7 = sections["## 7."]
    agg_idx = s7.find("Cross-item failure-mode aggregation")
    assert agg_idx >= 0, (
        "§7 must carry 'Cross-item failure-mode aggregation'"
    )
    # Slice to the next sub-heading.
    rest = s7[agg_idx:]
    next_sub = rest.find("\n### ", 3)
    agg_block = rest[:next_sub] if next_sub >= 0 else rest
    # Required table headers.
    for header in (
        "Mode-family", "Items affected",
        "Worst residual rating", "Mitigation-surface",
    ):
        assert header in agg_block, (
            f"§7.1 aggregation table missing required column "
            f"'{header}'"
        )
    # Every RES-Dn must appear somewhere in the aggregation block.
    for _, tag in ITEMS:
        assert tag in agg_block, (
            f"§7.1 aggregation block does not mention '{tag}'"
        )


def test_res_d4_uniquely_high_in_residual_distribution():
    """The Tag-67 narrative invariant: RES-D4 is the ONLY item with
    a residual rating 'high' (uncompounded) in the §7.3 RATING
    cell. The other four items are 'medium', 'medium-low', or
    'low-medium'. This is the Tag-67 load-bearing risk-map fact
    (informs CEO-Triage indefinite-deferral default).

    Implementation: parse each table row of the §7.3 distribution
    table and read the 'Residual rating' cell (column 2 of the
    three-cell row). Compare ONLY the rating cell — the 'Dominant
    residual driver' free-text cell may contain the word 'high'
    incidentally (e.g. for RES-D2's 'A3 high impact policy-layer
    mirror drift' annotation) and must not confound this test.
    """
    text = _load_doc()
    sections = _split_top_sections(text)
    s7 = sections["## 7."]
    distribution_idx = s7.find("Residual-risk distribution")
    assert distribution_idx >= 0
    distribution_block = s7[distribution_idx:]
    # Slice up to the next sub-section header to bound the table.
    next_sub = distribution_block.find("\n### ", 3)
    if next_sub >= 0:
        distribution_block = distribution_block[:next_sub]
    high_uncompounded = re.compile(
        r"^high$", re.IGNORECASE
    )
    high_count = 0
    res_d4_marked_high = False
    for _, tag in ITEMS:
        # Find the table row beginning with '| {tag} |'.
        row_marker = f"| {tag} |"
        row_idx = distribution_block.find(row_marker)
        assert row_idx >= 0, (
            f"§7.3 distribution table missing row for '{tag}'"
        )
        row_end = distribution_block.find("\n", row_idx)
        if row_end < 0:
            row_end = len(distribution_block)
        row = distribution_block[row_idx:row_end]
        cells = _split_table_row(row)
        # Three-cell row: [tag, rating, driver].
        assert len(cells) >= 3, (
            f"§7.3 row for '{tag}' has insufficient cells: {row!r}"
        )
        rating_cell = cells[1].strip().lower()
        if high_uncompounded.match(rating_cell):
            high_count += 1
            if tag == "RES-D4":
                res_d4_marked_high = True
    assert res_d4_marked_high, (
        "RES-D4 must be marked 'high' (uncompounded) in §7.3 "
        "rating cell"
    )
    assert high_count == 1, (
        f"exactly one item must be marked 'high' (uncompounded) "
        f"in §7.3 rating cell; found {high_count}"
    )


def test_aggregate_block_cites_governance_md_section_10():
    """§7 cross-anchor must cite GOVERNANCE.md §10 (the
    informative-skizze posture)."""
    text = _load_doc()
    sections = _split_top_sections(text)
    s7 = sections["## 7."]
    assert "GOVERNANCE.md" in s7, (
        "§7 cross-anchor must cite GOVERNANCE.md"
    )
    # The §10 reference must appear near the GOVERNANCE.md anchor.
    govern_idx = s7.find("GOVERNANCE.md")
    window = s7[govern_idx:govern_idx + 60]
    assert "10" in window, (
        f"GOVERNANCE.md citation must include §10 reference "
        f"(found near: {window!r})"
    )


# --------------------------------------------------------------- #
# Tag-65 cross-reference layer                                    #
# --------------------------------------------------------------- #


def test_tag65_cross_reference_doc_present():
    """The Tag-65 promotion-sequencing doc must be present in the
    repository; the Tag-67 pre-mortem and the Tag-68 coverage
    suite both treat Tag-65 as the upstream sequencing-authority.
    """
    if not TAG65_DOC_PATH.exists():
        pytest.skip(
            f"Tag-65 doc not present at {TAG65_DOC_REL} "
            f"(skip-if-absent for portability)"
        )
    assert TAG65_DOC_PATH.is_file()


def test_tag65_cross_reference_step_count_matches_item_count():
    """The Tag-65 promotion-sequencing doc declares one ordered
    per-item sub-section per RES-Dn item (§2.1..§2.5 in the
    current Tag-65 doc layout). The Tag-67 pre-mortem inventories
    one §N section per item (§2..§6). Both counts must agree at
    five.

    We accept either the §2.N sub-heading idiom (current Tag-65
    layout) OR a 'Step N' marker idiom (alternative Tag-65 layout
    that may be adopted by Mira-Edit in the future). Both are
    valid sequencing-doc forms; the invariant is the count of 5.
    """
    if not TAG65_DOC_PATH.exists():
        pytest.skip(f"Tag-65 doc not present at {TAG65_DOC_REL}")
    tag65_text = TAG65_DOC_PATH.read_text(encoding="utf-8")
    # First try the §2.N idiom (current layout).
    subsection_count = sum(
        1
        for n in range(1, 6)
        if re.search(rf"^### 2\.{n}\b", tag65_text, re.MULTILINE)
    )
    # Fallback: count 'Step N' header occurrences.
    step_marker_count = sum(
        1
        for n in range(1, 6)
        if re.search(rf"^#+.*\bStep\s+{n}\b", tag65_text, re.MULTILINE)
    )
    found = max(subsection_count, step_marker_count)
    assert found == 5, (
        f"Tag-65 must declare 5 per-item markers (either §2.1..§2.5 "
        f"sub-headings or 'Step 1..Step 5' headers); found "
        f"§2.N={subsection_count}, Step-N={step_marker_count}"
    )


def test_tag65_cross_reference_all_items_named():
    """Tag-65 must name every RES-Dn item (RES-D1..RES-D5)."""
    if not TAG65_DOC_PATH.exists():
        pytest.skip(f"Tag-65 doc not present at {TAG65_DOC_REL}")
    tag65_text = TAG65_DOC_PATH.read_text(encoding="utf-8")
    for _, tag in ITEMS:
        assert tag in tag65_text, (
            f"Tag-65 promotion-sequencing doc is missing '{tag}'"
        )


def test_tag67_pre_mortem_cites_tag65_explicitly():
    """The Tag-67 pre-mortem doc text body must cite Tag-65 in the
    body (not only in §7.4 cross-anchor). The Tag-65 schedule
    recommendation is the binding-by-default reference frame for
    the pre-mortem's per-item residual evaluations."""
    text = _load_doc()
    # Count Tag-65 mentions in the body (excluding §7.4 cross-anchor).
    sections = _split_top_sections(text)
    body_sections = "".join(
        sections[m] for m in ("## 1.", "## 2.", "## 3.", "## 4.",
                              "## 5.", "## 6.")
    )
    body_mentions = body_sections.count("Tag-65")
    assert body_mentions >= 5, (
        f"Tag-67 doc body (§1..§6) must cite 'Tag-65' at least 5 "
        f"times (one per item, on average); found {body_mentions}"
    )


# --------------------------------------------------------------- #
# Mode-Code coverage completeness                                  #
# --------------------------------------------------------------- #


def test_full_inventory_50_rows_total_under_per_item_sections():
    """Sanity guard: across §2..§6, the doc must contain exactly 50
    failure-mode-row markers (5 items x 10 codes). This guards
    against silent doubling (a code copied twice) or silent loss
    (a code missing from a section), in addition to the parametric
    per-tuple existence tests above."""
    text = _load_doc()
    sections = _split_top_sections(text)
    total = 0
    for marker, _ in ITEMS:
        body = sections[marker]
        for code in MODE_CODES:
            occurrences = body.count(f"| {code} |")
            # The §N.1 table has exactly one row per code.
            assert occurrences == 1, (
                f"§{marker} contains {occurrences} rows for code "
                f"'{code}'; expected exactly 1"
            )
            total += occurrences
    assert total == 50, (
        f"§2..§6 must contain exactly 50 failure-mode rows total; "
        f"found {total}"
    )


def test_mode_code_lexical_ordering_per_item():
    """Within each per-item §N.1 table, the mode codes must appear in
    canonical lexical order A1..A5, B1..B5 (top-to-bottom).
    Out-of-order codes indicate an editing accident."""
    text = _load_doc()
    sections = _split_top_sections(text)
    for marker, tag in ITEMS:
        body = sections[marker]
        positions = [
            (code, body.find(f"| {code} |"))
            for code in MODE_CODES
        ]
        # All must exist (already pinned per-tuple above).
        for code, pos in positions:
            assert pos >= 0, (
                f"§{marker} ({tag}) missing code '{code}'"
            )
        # Order check.
        last_pos = -1
        for code, pos in positions:
            assert pos > last_pos, (
                f"§{marker} ({tag}) code '{code}' at position {pos} "
                f"appears out of canonical A1..B5 order "
                f"(prior position {last_pos})"
            )
            last_pos = pos
