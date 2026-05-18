# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Structural validation for docs/phase-3c/cutover-operator-cheat-sheet.md.

Hermetic, stdlib-only (no PyYAML dependency — we parse the simple
YAML-front-matter subset by hand). Validates:

  1. File exists at the expected path under docs/phase-3c/.
  2. Has a YAML-frontmatter block opened and closed by '---'.
  3. Frontmatter contains the mandatory keys
     (title, owner, audit, adr, status, sprint_tag, welle_count).
  4. welle_count matches the seven Welle-Sections present in body.
  5. Every Welle-Section (§B..§H) declares the required sub-headings
     (Pre-Conditions, Cutover-Step, Post-Verify, Rollback-Step,
     Phone-a-Friend).
  6. Cross-Welle-Coordination table (§A) has exactly 4 KW-rows
     covering KW-24 .. KW-27 (ADR-0066 sequence).
  7. AR-Hand-Stop-Marker section (§I) enumerates >= 5 trigger
     conditions (Auftrag: 5-10 Bedingungen).
  8. Phase-3-COMPLETE-Marker section (§J) references the two
     Tomas-Workflows (PR #258 + PR #266) and the marker artifact
     `state/phase-3-complete-marker.json`.
  9. PDF-Render section (§K) lists at least one render-toolchain
     (pandoc OR markdown-pdf OR Browser-Print).
  10. All Welle-Runbook-Links resolve to existing files on disk
      (link-validity check).
  11. Cheat-sheet body stays <= 500 lines (Auftrag-limit).

Scope (12 tests, exceeds Auftrag-Tag-43 minimum of 10)
------------------------------------------------------

 1. test_cheat_sheet_file_exists
 2. test_frontmatter_block_present_and_closed
 3. test_frontmatter_has_mandatory_keys
 4. test_welle_count_matches_section_count
 5. test_every_welle_section_has_required_subheadings
 6. test_cross_welle_coordination_table_covers_kw_24_to_27
 7. test_ar_hand_stop_marker_lists_at_least_five_triggers
 8. test_phase_3_complete_marker_section_references_workflows
 9. test_pdf_render_section_documents_a_toolchain
10. test_all_runbook_links_resolve_on_disk
11. test_cheat_sheet_under_500_line_limit
12. test_phone_a_friend_subsection_present_per_welle
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

import pytest


# ---------------------------------------------------------------------------
# Path-helpers.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    # tests/phase_3c/test_cutover_cheat_sheet_structure.py -> 2x parent.
    return here.parent.parent.parent


CHEAT_SHEET_PATH = (
    _repo_root() / "docs" / "phase-3c" / "cutover-operator-cheat-sheet.md"
)


# ---------------------------------------------------------------------------
# Simple frontmatter parser (stdlib-only — avoids PyYAML dep).
# ---------------------------------------------------------------------------


def _split_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Return (frontmatter-dict, body-text). Frontmatter is a small
    YAML subset: 'key: "value"' or 'key: value', one-per-line, fenced
    by '---' lines at the very top of the document."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm_block = text[4:end]
    body = text[end + 5 :]
    fm: Dict[str, str] = {}
    for raw in fm_block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        fm[key] = value
    return fm, body


@pytest.fixture(scope="module")
def cheat_sheet_text() -> str:
    if not CHEAT_SHEET_PATH.is_file():
        pytest.fail(f"cheat-sheet not found at {CHEAT_SHEET_PATH}")
    return CHEAT_SHEET_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(cheat_sheet_text: str) -> Tuple[Dict[str, str], str]:
    return _split_frontmatter(cheat_sheet_text)


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_cheat_sheet_file_exists() -> None:
    assert CHEAT_SHEET_PATH.is_file(), (
        f"expected cheat-sheet at {CHEAT_SHEET_PATH}"
    )


def test_frontmatter_block_present_and_closed(cheat_sheet_text: str) -> None:
    assert cheat_sheet_text.startswith("---\n"), (
        "cheat-sheet must open with YAML-frontmatter '---' fence"
    )
    # Locate the closing fence.
    closing = cheat_sheet_text.find("\n---\n", 4)
    assert closing > 0, "cheat-sheet YAML-frontmatter must close with '---'"


def test_frontmatter_has_mandatory_keys(
    parsed: Tuple[Dict[str, str], str]
) -> None:
    fm, _ = parsed
    mandatory = {
        "title",
        "owner",
        "audit",
        "adr",
        "status",
        "sprint_tag",
        "welle_count",
    }
    missing = mandatory - set(fm.keys())
    assert not missing, f"frontmatter missing mandatory keys: {missing}"
    # sprint_tag must be the integer-string '43'.
    assert fm["sprint_tag"] == "43", (
        f"expected sprint_tag=43, got {fm['sprint_tag']!r}"
    )
    # welle_count must be the integer-string '7'.
    assert fm["welle_count"] == "7", (
        f"expected welle_count=7, got {fm['welle_count']!r}"
    )


def test_welle_count_matches_section_count(
    parsed: Tuple[Dict[str, str], str]
) -> None:
    fm, body = parsed
    # Welle-Sections are §B..§H — exactly 7.
    welle_section_regex = re.compile(
        r"^## §[B-H] — Welle-([1-7]):", re.MULTILINE
    )
    matches = welle_section_regex.findall(body)
    assert len(matches) == 7, (
        f"expected 7 Welle-Sections (§B..§H), found {len(matches)}: {matches}"
    )
    # Each Welle 1..7 must appear exactly once.
    assert sorted(matches) == [str(i) for i in range(1, 8)], (
        f"Welle-Section IDs must be 1..7 exactly, got {sorted(matches)}"
    )


def test_every_welle_section_has_required_subheadings(
    parsed: Tuple[Dict[str, str], str]
) -> None:
    _, body = parsed
    # Split body at each Welle-Section marker.
    # Use a finditer + slice approach.
    headers = list(re.finditer(r"^## §[B-H] — Welle-[1-7]:", body, re.MULTILINE))
    assert headers, "no Welle-Section headers found"
    # Append a sentinel end-of-body marker.
    boundaries = [m.start() for m in headers] + [len(body)]
    required_subs = (
        "### Pre-Conditions",
        "### Cutover-Step",
        "### Post-Verify",
        "### Rollback-Step",
        "### Phone-a-Friend",
    )
    for idx, hdr in enumerate(headers):
        section_body = body[boundaries[idx] : boundaries[idx + 1]]
        for sub in required_subs:
            assert sub in section_body, (
                f"Welle-Section starting at offset {hdr.start()} "
                f"missing required subheading {sub!r}"
            )


def test_cross_welle_coordination_table_covers_kw_24_to_27(
    parsed: Tuple[Dict[str, str], str]
) -> None:
    _, body = parsed
    # Locate the §A section and the table inside it.
    section_match = re.search(
        r"^## §A — Cross-Welle-Coordination-Mini-Tabelle.*?^##",
        body,
        re.DOTALL | re.MULTILINE,
    )
    assert section_match is not None, "§A section not found"
    section_text = section_match.group(0)
    # Each KW-row starts with "| 24 " or "| 25 " etc.
    kw_rows = re.findall(r"^\|\s*(2[4-7])\s*\|", section_text, re.MULTILINE)
    assert sorted(kw_rows) == ["24", "25", "26", "27"], (
        f"§A table must cover KW-24..KW-27 exactly, got {kw_rows}"
    )


def test_ar_hand_stop_marker_lists_at_least_five_triggers(
    parsed: Tuple[Dict[str, str], str]
) -> None:
    _, body = parsed
    section_match = re.search(
        r"^## §I — AR-Hand-Stop-Marker.*?^## §J",
        body,
        re.DOTALL | re.MULTILINE,
    )
    assert section_match is not None, "§I AR-Hand-Stop-Marker section missing"
    section_text = section_match.group(0)
    # Enumerated trigger conditions are markdown ordered-list "1." ... "N.".
    enumerated = re.findall(r"^\s*(\d+)\. \*\*", section_text, re.MULTILINE)
    assert len(enumerated) >= 5, (
        f"§I must enumerate >= 5 trigger conditions, found "
        f"{len(enumerated)}: {enumerated}"
    )
    # Auftrag-upper-bound: max 10.
    assert len(enumerated) <= 10, (
        f"§I must enumerate <= 10 trigger conditions (Auftrag-cap), "
        f"found {len(enumerated)}"
    )


def test_phase_3_complete_marker_section_references_workflows(
    parsed: Tuple[Dict[str, str], str]
) -> None:
    _, body = parsed
    section_match = re.search(
        r"^## §J — Phase-3-COMPLETE-Marker.*?^## §K",
        body,
        re.DOTALL | re.MULTILINE,
    )
    assert section_match is not None, "§J Phase-3-COMPLETE-Marker section missing"
    section_text = section_match.group(0)
    # Must reference Tomas-Workflow PR-258 and PR-266.
    assert "#258" in section_text, "§J must reference PR #258"
    assert "#266" in section_text, "§J must reference PR #266"
    # Must reference the marker artifact path.
    assert "state/phase-3-complete-marker.json" in section_text, (
        "§J must reference the phase-3-complete-marker.json artifact path"
    )
    # Must reference the marker-emitting workflow filename.
    assert "phase-3-complete-marker.yml" in section_text, (
        "§J must reference phase-3-complete-marker.yml workflow"
    )


def test_pdf_render_section_documents_a_toolchain(
    parsed: Tuple[Dict[str, str], str]
) -> None:
    _, body = parsed
    section_match = re.search(
        r"^## §K — Cheat-Sheet-PDF-Render.*?^## §L",
        body,
        re.DOTALL | re.MULTILINE,
    )
    assert section_match is not None, "§K PDF-Render section missing"
    section_text = section_match.group(0)
    # At least one render toolchain mentioned.
    toolchains = ("pandoc", "markdown-pdf", "Browser-Print")
    found = [t for t in toolchains if t in section_text]
    assert found, (
        f"§K must document at least one of {toolchains}; "
        f"none found in section"
    )


def test_all_runbook_links_resolve_on_disk(
    parsed: Tuple[Dict[str, str], str]
) -> None:
    _, body = parsed
    # Extract every `./welle-N-*-runbook.md` reference.
    refs = re.findall(r"\]\(\./(welle-[0-9]+-[a-z0-9-]+-runbook\.md)\)", body)
    assert refs, "cheat-sheet must reference at least one Welle-Runbook"
    docs_dir = CHEAT_SHEET_PATH.parent
    missing = [r for r in refs if not (docs_dir / r).is_file()]
    assert not missing, (
        f"cheat-sheet references non-existent runbook(s) on main: {missing}"
    )
    # Must reference all seven Welle-Runbooks at least once.
    welle_nums = {int(re.match(r"welle-(\d+)-", r).group(1)) for r in refs}
    assert welle_nums == {1, 2, 3, 4, 5, 6, 7}, (
        f"cheat-sheet must reference all 7 Welle-Runbooks, got {welle_nums}"
    )


def test_cheat_sheet_under_500_line_limit(cheat_sheet_text: str) -> None:
    line_count = cheat_sheet_text.count("\n") + (
        0 if cheat_sheet_text.endswith("\n") else 1
    )
    assert line_count <= 500, (
        f"cheat-sheet exceeds 500-line Auftrag-limit: {line_count} lines"
    )


def test_phone_a_friend_subsection_present_per_welle(
    parsed: Tuple[Dict[str, str], str]
) -> None:
    """Every Welle-Section names a phone-a-friend persona from the
    set: Reza / Selin / Kai / Tomás / Amara / Noa / Henrik / Priya."""
    _, body = parsed
    welle_personas = {
        1: ("Reza", "Tomás"),
        2: ("Reza", "Kai"),
        3: ("Henrik", "Tomás", "Reza"),
        4: ("Tomás", "Reza", "Henrik"),
        5: ("Tomás", "Selin", "Henrik"),
        6: ("Reza", "Kai", "Noa"),
        7: ("Tomás", "Henrik", "Amara"),
    }
    headers = list(re.finditer(
        r"^## §[B-H] — Welle-([1-7]):", body, re.MULTILINE
    ))
    boundaries = [m.start() for m in headers] + [len(body)]
    for idx, hdr in enumerate(headers):
        welle_num = int(hdr.group(1))
        section_body = body[boundaries[idx] : boundaries[idx + 1]]
        phone_match = re.search(
            r"### Phone-a-Friend(.*?)\*\*Voll-Runbook",
            section_body,
            re.DOTALL,
        )
        assert phone_match is not None, (
            f"Welle-{welle_num}: Phone-a-Friend subsection malformed "
            "(missing or no Voll-Runbook close)"
        )
        phone_text = phone_match.group(1)
        expected = welle_personas[welle_num]
        # At least one of the expected personas must appear.
        assert any(p in phone_text for p in expected), (
            f"Welle-{welle_num}: Phone-a-Friend must name one of "
            f"{expected}; got: {phone_text!r}"
        )
