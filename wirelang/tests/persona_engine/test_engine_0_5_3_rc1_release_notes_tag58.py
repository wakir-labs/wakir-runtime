# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-58 — Engine 0.5.3-rc1 release-notes historical-fixture pin (Selin).

Originally the Tag-58 hermetic consistency pin for the
``0.5.3-rc1`` four-surface authority bundle
(``__version__.py`` ↔ manifest §0 ↔ release-notes ↔ test). The
Tag-62 final-bump (0.5.3-rc1 → 0.5.3 final, rc1-suffix-drop)
promoted that role to the fresh
``test_engine_0_5_3_final_bump_tag62.py`` pin; this file is
preserved as the **historical-fixture anchor** for the rc1
substrate so the rc1 release-notes file and the manifest §0.1 Tag-58
history sub-section remain auditable forever.

What this file asserts after Tag-62
-----------------------------------

1. The rc1 release-notes file (``docs/persona-engine/0-5-3-rc1-
   release-notes.md``) is still present in the repo. It MUST NOT
   be deleted by future bumps — it is the public-facing record of
   the rc1 substrate.
2. The rc1 release-notes file H1 still pins ``0.5.3-rc1`` (it is a
   frozen artefact; its content does not migrate with the active
   version).
3. The rc1 release-notes file carries the five canonical sections
   (Scope, Carry-Forward, OPEN-Items, Pre-Cutover Gate-Map,
   Operator-Hand Items) it had at Tag-58 cut.
4. The Tag-52 manifest preserves a §0.1 sub-section that narrates
   the Tag-58 rc1 substrate as historical context (the Tag-62
   final-bump §0 rewrite explicitly added this sub-section so the
   rc1 → final transition stays auditable).
5. The manifest §0 (now active 0.5.3 final) references the rc1
   filename ``0.5.3-rc1`` somewhere in its body as predecessor
   marker.

Live four-surface consistency checks (``__version__`` ==
``ENGINE_VERSION`` == manifest §0 active-version-cell ==
release-notes H1 == test ``EXPECTED_VERSION``) are owned by
``test_engine_0_5_3_final_bump_tag62.py`` and have been removed
from this file.

Scope discipline (Selin)
------------------------
This file does **not** modify persona definitions (Aisha-Domäne,
ADR-0043), WAT-core logic (Tomás-Domäne, Zone-K), identity-substrate
design (Reza-Domäne, Zone-L), or container-infra (Kai-Domäne,
Zone-J).
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths anchored from the repo root. This file lives at
# wirelang/tests/persona_engine/, so repo_root = parents[3].
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]

MANIFEST_PATH = (
    REPO_ROOT
    / "wirelang"
    / "persona_engine"
    / "MANIFEST-0.5.2-final-pre-cutover.md"
)
RC1_RELEASE_NOTES_PATH = (
    REPO_ROOT / "docs" / "persona-engine" / "0-5-3-rc1-release-notes.md"
)

# Tag-58 rc1 substrate constants — preserved as historical fixtures.
RC1_VERSION = "0.5.3-rc1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ===========================================================================
# Test 1 — The rc1 release-notes file must survive as a historical artefact.
# ===========================================================================


def test_t01_rc1_release_notes_file_preserved_as_historical_artefact() -> None:
    """docs/persona-engine/0-5-3-rc1-release-notes.md is preserved post-Tag-62.

    The rc1 release-notes file is the public-facing record of the
    Tag-58 substrate. Future bumps MUST NOT delete it — they only
    add new release-notes files alongside.
    """
    assert RC1_RELEASE_NOTES_PATH.is_file(), (
        f"Tag-58 rc1 release-notes file missing — Tag-62 final-bump must "
        f"preserve historical artefacts: {RC1_RELEASE_NOTES_PATH}"
    )


# ===========================================================================
# Test 2 — The rc1 release-notes H1 still pins 0.5.3-rc1.
# ===========================================================================


def test_t02_rc1_release_notes_h1_still_pins_rc1_version() -> None:
    """The frozen H1 of the rc1 file must still carry 0.5.3-rc1."""
    source = _read(RC1_RELEASE_NOTES_PATH)
    h1_match = re.search(r"^#\s+(.+)$", source, re.MULTILINE)
    assert h1_match is not None, (
        "rc1 release-notes file has no H1 title"
    )
    h1 = h1_match.group(1)
    assert RC1_VERSION in h1, (
        f"rc1 release-notes H1 {h1!r} does not contain {RC1_VERSION!r} — "
        f"the frozen historical artefact has been corrupted"
    )


# ===========================================================================
# Test 3 — The rc1 release-notes carries the five canonical sections.
# ===========================================================================


def test_t03_rc1_release_notes_has_five_canonical_sections() -> None:
    """The rc1 release-notes must keep its Tag-58 five-section shape."""
    source = _read(RC1_RELEASE_NOTES_PATH)
    required_sections = (
        "## 1. Scope",
        "## 2. Carry-Forward",
        "## 3. OPEN-Items Status",
        "## 4. Pre-Cutover Gate-Map",
        "## 5. Operator-Hand Items",
    )
    for section in required_sections:
        assert section in source, (
            f"rc1 release-notes missing canonical section: {section!r} — "
            f"historical artefact corrupted"
        )


# ===========================================================================
# Test 4 — The rc1 release-notes marks the K1/K2/J1 closeouts + OPEN-J2.
# ===========================================================================


def test_t04_rc1_release_notes_marks_tag57_closeouts_and_open_j2() -> None:
    """rc1 file carries the Tag-57 closeout markers + OPEN-J2 remaining item."""
    source = _read(RC1_RELEASE_NOTES_PATH)
    for closed_marker in ("OPEN-K1", "OPEN-K2", "OPEN-J1"):
        assert closed_marker in source, (
            f"rc1 release-notes missing Tag-57 closeout marker {closed_marker}"
        )
    assert "OPEN-J2" in source, (
        "rc1 release-notes missing OPEN-J2 (Operator-Hand cutover-day) marker"
    )
    assert "Closed in Tag-57" in source, (
        "rc1 release-notes must mark K1/K2/J1 as closed in Tag-57"
    )


# ===========================================================================
# Test 5 — The rc1 release-notes references the Tag-56/Tag-57 PR substrate.
# ===========================================================================


def test_t05_rc1_release_notes_references_tag56_tag57_pr_substrate() -> None:
    """rc1 file pins Tag-56 audit (#362) and Tag-57 closeouts (#363/#366/#367)."""
    source = _read(RC1_RELEASE_NOTES_PATH)
    for pr in ("#362", "#363", "#366", "#367"):
        assert pr in source, (
            f"rc1 release-notes missing Tag-56/57 PR substrate reference {pr}"
        )


# ===========================================================================
# Test 6 — Tag-52 manifest preserves the §0.1 Tag-58 history sub-section.
# ===========================================================================


def test_t06_manifest_preserves_tag58_history_subsection() -> None:
    """Manifest §0.1 must narrate the Tag-58 rc1 substrate post-Tag-62 bump.

    The Tag-62 final-bump rewrote §0 to record 0.5.3 final as active.
    To keep the rc1 substrate auditable, the rewrite added a §0.1
    Tag-58 history sub-section that preserves the rc1 narrative.
    """
    source = _read(MANIFEST_PATH)
    assert "### 0.1" in source or "## 0.1" in source, (
        "Manifest missing §0.1 history sub-section — Tag-62 rewrite must "
        "preserve a sub-section narrating the Tag-58 rc1 substrate"
    )
    # Find the §0.1 block (between the §0.1 heading and the next ##/### at
    # the same or higher level).
    sub_idx = source.find("### 0.1")
    if sub_idx < 0:
        sub_idx = source.find("## 0.1")
    assert sub_idx >= 0
    # Slice from §0.1 heading to the next ## (top-level §1+) heading.
    section_one_idx = source.index("## 1.", sub_idx)
    subsection = source[sub_idx:section_one_idx]
    assert "Tag-58" in subsection, (
        "Manifest §0.1 must reference Tag-58 explicitly"
    )
    assert RC1_VERSION in subsection, (
        f"Manifest §0.1 must reference the rc1 version literal {RC1_VERSION!r}"
    )


# ===========================================================================
# Test 7 — Tag-52 manifest §0 active-cell references rc1 as predecessor.
# ===========================================================================


def test_t07_manifest_section_zero_records_rc1_as_predecessor() -> None:
    """The active §0 must reference rc1 as 'strict superset of' predecessor."""
    source = _read(MANIFEST_PATH)
    section_zero_idx = source.index("## 0. Version Header")
    section_one_idx = source.index("## 1. Component Inventory")
    section_zero = source[section_zero_idx:section_one_idx]
    assert RC1_VERSION in section_zero, (
        f"Manifest §0 does not reference {RC1_VERSION!r} as predecessor — "
        f"the rc1 → final transition must remain visible in §0"
    )


# ===========================================================================
# Test 8 — rc1 release-notes scope discipline block is preserved.
# ===========================================================================


def test_t08_rc1_release_notes_pins_scope_discipline_j_k_l() -> None:
    """rc1 file §1 must declare Aisha/Tomás/Reza/Kai zones out of scope.

    Historical anchor — the scope-discipline contract was already
    binding at Tag-58 cut and remains visible in the frozen file.
    """
    source = _read(RC1_RELEASE_NOTES_PATH)
    lowered = source.lower()
    assert "aisha" in lowered
    assert "tomás" in lowered or "tomas" in lowered
    assert "reza" in lowered
    assert "kai" in lowered
    for zone in ("Zone-J", "Zone-K", "Zone-L"):
        assert zone in source, (
            f"rc1 release-notes scope-discipline block missing {zone} label"
        )


# ===========================================================================
# Test 9 — rc1 release-notes signed by Selin.
# ===========================================================================


def test_t09_rc1_release_notes_signed_by_selin() -> None:
    """The rc1 file ends with the Selin signature line."""
    source = _read(RC1_RELEASE_NOTES_PATH)
    assert "— Selin" in source or "- Selin" in source, (
        "rc1 release-notes missing the Selin signature line"
    )


# ===========================================================================
# Test 10 — The rc1 file no longer claims to be the active release.
# ===========================================================================


def test_t10_rc1_release_notes_is_frozen_historical_substrate() -> None:
    """rc1 file MAY say it WAS the final RC, but the canonical 0.5.3 path
    must now point to a different file.

    This test is a soft sanity check that the rc1 file remains an
    rc1 artefact (not silently re-titled as the final).
    """
    h1_match = re.search(r"^#\s+(.+)$", _read(RC1_RELEASE_NOTES_PATH), re.MULTILINE)
    assert h1_match is not None
    h1 = h1_match.group(1)
    # The H1 must explicitly carry the rc1 suffix; it is not the
    # final-release file.
    assert "rc1" in h1.lower(), (
        f"rc1 release-notes H1 {h1!r} does not carry the rc1 suffix — "
        f"the frozen artefact has drifted into a final-release claim"
    )
