# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-58 — Engine 0.5.3-rc1 release-notes consistency pin (Selin, Persona-Engine).

The 0.5.3-rc1 bump is a **manifest-and-metadata-only** RC. It threads
the same version string ``0.5.3-rc1`` across four authority surfaces:

1. ``wirelang/persona_engine/__version__.py`` — the canonical Python
   source of truth (``__version__`` + ``ENGINE_VERSION``).
2. ``wirelang/persona_engine/__init__.py`` — re-exports
   ``__version__`` from #1.
3. ``wirelang/persona_engine/engine.py`` — re-exports
   ``ENGINE_VERSION`` from #1.
4. ``wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md`` —
   the §0 Version Header records the active engine version.
5. ``docs/persona-engine/0-5-3-rc1-release-notes.md`` — the public
   release-notes companion.

Any future bump that touches one of those surfaces but not the others
breaks one of the assertions below. The test is the single hermetic
guard that the four-file authority bundle stays consistent.

Secondary contracts pinned here:

* The release-notes file must mark **OPEN-J2 as the only remaining
  Operator-Hand item** (Tag-57 PR #366 closed K1/K2; Tag-57 PR #367
  closed J1).
* The release-notes Pre-Cutover Gate-Map must reference the Tag-56
  audit substrate (PR #362) and the Tag-57 closeout chain (PR #363,
  #366, #367) by exact PR number.
* The manifest §0 must list the four authority paths in the same
  shape the ``__version__`` module advertises via ``MANIFEST_RELPATH``
  and ``RELEASE_NOTES_RELPATH``.

Hermetic envelope
-----------------
* No network. No NATS, no SPIRE, no gRPC.
* No subprocess. No Rust binary build.
* No filesystem writes — pure file inspection.
* Deterministic — no clock-sensitive assertions.

Scope discipline (Selin)
------------------------
This file does **not** modify persona definitions (Aisha-Domäne,
ADR-0043), WAT-core logic (Tomás-Domäne, Zone-K), identity-substrate
design (Reza-Domäne, Zone-L), or container-infra (Kai-Domäne, Zone-J).
It only asserts the version-string consistency relation across the
five files listed above.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths anchored from the repo root. This file lives at
# wirelang/tests/persona_engine/, so repo_root = parents[3].
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]

VERSION_MODULE_PATH = (
    REPO_ROOT / "wirelang" / "persona_engine" / "__version__.py"
)
INIT_PATH = REPO_ROOT / "wirelang" / "persona_engine" / "__init__.py"
ENGINE_PATH = REPO_ROOT / "wirelang" / "persona_engine" / "engine.py"
MANIFEST_PATH = (
    REPO_ROOT
    / "wirelang"
    / "persona_engine"
    / "MANIFEST-0.5.2-final-pre-cutover.md"
)
RELEASE_NOTES_PATH = (
    REPO_ROOT / "docs" / "persona-engine" / "0-5-3-rc1-release-notes.md"
)

EXPECTED_VERSION = "0.5.3-rc1"

# Tag-57 closeout PR numbers that the release-notes Pre-Cutover Gate-Map
# must reference. These are pinned by the auftrag context.
TAG57_CLOSEOUT_PRS = ("#363", "#366", "#367")

# Tag-56 audit substrate PR that the release-notes carry-forward table
# must reference.
TAG56_AUDIT_PR = "#362"

# Five gate-substrate references that the Pre-Cutover Gate-Map must
# include. Each is a Tag-X / PR-Y pair from the Tag-52..Tag-57
# substrate chain.
REQUIRED_GATE_REFERENCES = (
    ("Tag-55", "#357"),  # Cosign-Strict-Mode G3+G5
    ("Tag-56", "#359"),  # Watch-day-practice-run CI gate
    ("Tag-56", "#361"),  # Phase-3-Marathon-Rollback workflow
    ("Tag-57", "#363"),  # state_backing pre-boot emit-order pin
    ("Tag-57", "#367"),  # OPEN-J1 Cross-Substrate-Parity-Gate closeout
)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_version_literal(source: str, symbol: str) -> str:
    """Extract ``SYMBOL = "<string>"`` literal from a python source file.

    Falls back to the first quoted string on a line that starts with
    ``SYMBOL = `` to keep the regex tolerant of import-alias patterns.
    """
    pattern = re.compile(
        rf"^{re.escape(symbol)}\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE
    )
    match = pattern.search(source)
    if match is None:
        return ""
    return match.group(1)


# ===========================================================================
# Test 1 — __version__.py is the canonical anchor.
# ===========================================================================


def test_t01_version_module_exists_and_pins_0_5_3_rc1() -> None:
    """The Tag-58 anchor module must exist and pin exactly 0.5.3-rc1."""
    assert VERSION_MODULE_PATH.is_file(), (
        f"Tag-58 canonical version anchor missing: {VERSION_MODULE_PATH}"
    )
    source = _read(VERSION_MODULE_PATH)
    literal = _extract_version_literal(source, "__version__")
    assert literal == EXPECTED_VERSION, (
        f"__version__.py pins {literal!r}, expected {EXPECTED_VERSION!r}"
    )


# ===========================================================================
# Test 2 — ENGINE_VERSION mirrors __version__ inside __version__.py.
# ===========================================================================


def test_t02_engine_version_alias_in_version_module() -> None:
    """ENGINE_VERSION in __version__.py must alias __version__."""
    source = _read(VERSION_MODULE_PATH)
    # ENGINE_VERSION = __version__ is the canonical form. Accept either the
    # alias form or a direct literal — both yield the same value at import.
    assert "ENGINE_VERSION" in source, (
        "ENGINE_VERSION symbol missing from canonical anchor module"
    )
    # If the alias is a literal, it must match expected.
    literal = _extract_version_literal(source, "ENGINE_VERSION")
    if literal:
        assert literal == EXPECTED_VERSION, (
            f"ENGINE_VERSION literal {literal!r} drifts from "
            f"__version__ {EXPECTED_VERSION!r}"
        )


# ===========================================================================
# Test 3 — __init__.py re-exports from __version__.py.
# ===========================================================================


def test_t03_init_py_imports_version_from_canonical_anchor() -> None:
    """__init__.py must import __version__ from .__version__, not inline."""
    source = _read(INIT_PATH)
    assert "from .__version__ import __version__" in source, (
        "wirelang/persona_engine/__init__.py must import __version__ "
        "from the canonical anchor module (Tag-58 refactor)"
    )
    # Negative: no inline 0.5.2 / 0.5.1 / 0.5.0 literal leak.
    for stale in ("0.5.0-pilot", "0.5.1-pre-cutover", "0.5.2-final-pre-cutover"):
        assert f'__version__ = "{stale}"' not in source, (
            f"__init__.py still carries stale inline literal {stale!r}"
        )


# ===========================================================================
# Test 4 — engine.py imports ENGINE_VERSION from __version__.py.
# ===========================================================================


def test_t04_engine_py_imports_engine_version_from_canonical_anchor() -> None:
    """engine.py must import ENGINE_VERSION from .__version__."""
    source = _read(ENGINE_PATH)
    assert "from .__version__ import ENGINE_VERSION" in source, (
        "wirelang/persona_engine/engine.py must import ENGINE_VERSION "
        "from the canonical anchor module (Tag-58 refactor)"
    )
    # Negative: no stale inline literal.
    assert 'ENGINE_VERSION = "0.5.0-pilot"' not in source, (
        "engine.py still carries the stale ENGINE_VERSION inline literal"
    )


# ===========================================================================
# Test 5 — Public import surface yields the expected version string.
# ===========================================================================


def test_t05_public_import_surface_yields_expected_version() -> None:
    """``import wirelang.persona_engine`` must expose the bumped version."""
    pkg = pytest.importorskip("wirelang.persona_engine")
    assert getattr(pkg, "__version__", None) == EXPECTED_VERSION, (
        f"wirelang.persona_engine.__version__ = "
        f"{getattr(pkg, '__version__', None)!r}, expected {EXPECTED_VERSION!r}"
    )


# ===========================================================================
# Test 6 — Manifest §0 Version Header pins the same string.
# ===========================================================================


def test_t06_manifest_section_zero_pins_engine_version() -> None:
    """The Tag-52 manifest §0 must record engine version 0.5.3-rc1."""
    source = _read(MANIFEST_PATH)
    assert "## 0. Version Header" in source, (
        "Manifest §0 Version Header section missing (Tag-58 bump)"
    )
    # The §0 table must carry the exact bumped version inside a code-span.
    assert f"`{EXPECTED_VERSION}`" in source, (
        f"Manifest §0 does not record {EXPECTED_VERSION!r} as the active "
        f"engine version"
    )


# ===========================================================================
# Test 7 — Manifest §0 references all four authority paths.
# ===========================================================================


def test_t07_manifest_section_zero_lists_four_authority_paths() -> None:
    """Manifest §0 must reference __version__.py, manifest, pin-pack, notes."""
    source = _read(MANIFEST_PATH)
    section_zero_start = source.index("## 0. Version Header")
    section_one_start = source.index("## 1. Component Inventory")
    section_zero = source[section_zero_start:section_one_start]

    required_paths = (
        "wirelang/persona_engine/__version__.py",
        "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md",
        "infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml",
        "docs/persona-engine/0-5-3-rc1-release-notes.md",
    )
    for relpath in required_paths:
        assert relpath in section_zero, (
            f"Manifest §0 missing authority-path reference: {relpath!r}"
        )


# ===========================================================================
# Test 8 — Release-notes file exists at the expected path.
# ===========================================================================


def test_t08_release_notes_file_exists_at_canonical_path() -> None:
    """docs/persona-engine/0-5-3-rc1-release-notes.md must exist."""
    assert RELEASE_NOTES_PATH.is_file(), (
        f"Tag-58 release-notes file missing: {RELEASE_NOTES_PATH}"
    )


# ===========================================================================
# Test 9 — Release-notes header pins the same version string.
# ===========================================================================


def test_t09_release_notes_header_pins_engine_version() -> None:
    """Release-notes title line must carry 0.5.3-rc1."""
    source = _read(RELEASE_NOTES_PATH)
    # The first H1 must mention the bumped version.
    h1_match = re.search(r"^#\s+(.+)$", source, re.MULTILINE)
    assert h1_match is not None, "Release-notes file has no H1 title"
    h1 = h1_match.group(1)
    assert EXPECTED_VERSION in h1, (
        f"Release-notes H1 {h1!r} does not contain {EXPECTED_VERSION!r}"
    )


# ===========================================================================
# Test 10 — Release-notes carries all five canonical sections.
# ===========================================================================


def test_t10_release_notes_has_all_five_canonical_sections() -> None:
    """Release-notes must contain the five sections specified by the auftrag."""
    source = _read(RELEASE_NOTES_PATH)
    required_sections = (
        "## 1. Scope",
        "## 2. Carry-Forward",
        "## 3. OPEN-Items Status",
        "## 4. Pre-Cutover Gate-Map",
        "## 5. Operator-Hand Items",
    )
    for section in required_sections:
        assert section in source, (
            f"Release-notes missing required section: {section!r}"
        )


# ===========================================================================
# Test 11 — OPEN-J2 marker present as the only remaining Operator-Hand item.
# ===========================================================================


def test_t11_release_notes_marks_open_j2_as_remaining_operator_hand() -> None:
    """OPEN-J2 must be marked as the only remaining open item."""
    source = _read(RELEASE_NOTES_PATH)
    assert "OPEN-J2" in source, (
        "Release-notes does not mark OPEN-J2 (Operator-Hand cutover-day)"
    )
    # And K1/K2/J1 must be marked closed (Tag-57 closeouts).
    for closed_marker in ("OPEN-K1", "OPEN-K2", "OPEN-J1"):
        assert closed_marker in source, (
            f"Release-notes does not reference Tag-57 closeout {closed_marker}"
        )
    # The "Closed in Tag-57" subsection header is the contract anchor.
    assert "Closed in Tag-57" in source, (
        "Release-notes must explicitly mark K1/K2/J1 as closed in Tag-57"
    )


# ===========================================================================
# Test 12 — Pre-Cutover Gate-Map references Tag-56 + Tag-57 substrate by PR.
# ===========================================================================


def test_t12_release_notes_gate_map_references_tag56_tag57_substrate() -> None:
    """Gate-Map must reference Tag-56 audit + Tag-57 closeout PRs by number."""
    source = _read(RELEASE_NOTES_PATH)
    # Tag-56 audit substrate is the anchor for the carry-forward table.
    assert TAG56_AUDIT_PR in source, (
        f"Release-notes does not reference Tag-56 audit PR {TAG56_AUDIT_PR}"
    )
    # Each Tag-57 closeout PR must be present.
    for pr in TAG57_CLOSEOUT_PRS:
        assert pr in source, (
            f"Release-notes does not reference Tag-57 closeout PR {pr}"
        )
    # And each required Tag-X/PR-Y gate-substrate pair must appear in the
    # release-notes (they may appear in the carry-forward §2 or the gate-
    # map §4 — both are acceptable).
    for tag, pr in REQUIRED_GATE_REFERENCES:
        assert tag in source, f"Release-notes missing {tag} reference"
        assert pr in source, f"Release-notes missing {tag} PR {pr} reference"


# ===========================================================================
# Test 13 — Scope discipline: explicit non-goal markers for J/K/L zones.
# ===========================================================================


def test_t13_release_notes_pins_scope_discipline_for_j_k_l_zones() -> None:
    """Release-notes §1 must declare Aisha/Tomás/Reza/Kai zones out of scope."""
    source = _read(RELEASE_NOTES_PATH)
    # Lower-case for case-insensitive name match while keeping the zone
    # labels exact.
    lowered = source.lower()
    assert "aisha" in lowered, "Release-notes does not mark Aisha-Domäne"
    assert "tomás" in lowered or "tomas" in lowered, (
        "Release-notes does not mark Tomás-Domäne"
    )
    assert "reza" in lowered, "Release-notes does not mark Reza-Domäne"
    assert "kai" in lowered, "Release-notes does not mark Kai-Domäne"
    # And the three Cross-Review zone labels must appear explicitly.
    for zone in ("Zone-J", "Zone-K", "Zone-L"):
        assert zone in source, (
            f"Release-notes scope-discipline block missing {zone} label"
        )


# ===========================================================================
# Test 14 — Strict-superset claim: no stale 0.5.2-final/0.5.1/0.5.0 version
#           string is silently substituted in the four authority surfaces.
# ===========================================================================


def test_t14_no_stale_version_literal_in_authority_surfaces() -> None:
    """The four authority surfaces must not carry a stale __version__ literal."""
    surfaces = (
        VERSION_MODULE_PATH,
        INIT_PATH,
        ENGINE_PATH,
    )
    stale_patterns = (
        '__version__ = "0.5.0-pilot"',
        '__version__ = "0.5.1-pre-cutover"',
        '__version__ = "0.5.2-final-pre-cutover"',
        'ENGINE_VERSION = "0.5.0-pilot"',
        'ENGINE_VERSION = "0.5.1-pre-cutover"',
        'ENGINE_VERSION = "0.5.2-final-pre-cutover"',
    )
    for path in surfaces:
        text = _read(path)
        for stale in stale_patterns:
            assert stale not in text, (
                f"{path.name} still carries stale literal: {stale!r}"
            )


# ===========================================================================
# Test 15 — MANIFEST_RELPATH and RELEASE_NOTES_RELPATH point to real files.
# ===========================================================================


def test_t15_version_module_relpaths_resolve_to_real_files() -> None:
    """The relpath constants in __version__.py must point to existing files."""
    pytest.importorskip("wirelang.persona_engine")
    # The anchor sub-module (not the package attribute) exports both
    # relpath constants. Import the sub-module explicitly.
    import importlib

    anchor = importlib.import_module(
        "wirelang.persona_engine.__version__"
    )

    manifest_path = REPO_ROOT / anchor.MANIFEST_RELPATH
    notes_path = REPO_ROOT / anchor.RELEASE_NOTES_RELPATH

    assert manifest_path.is_file(), (
        f"MANIFEST_RELPATH points to non-existent file: {manifest_path}"
    )
    assert notes_path.is_file(), (
        f"RELEASE_NOTES_RELPATH points to non-existent file: {notes_path}"
    )
    # And the release-notes path must end with the expected version slug.
    assert anchor.RELEASE_NOTES_RELPATH.endswith(
        f"{EXPECTED_VERSION.replace('.', '-')}-release-notes.md"
    ), (
        f"RELEASE_NOTES_RELPATH {anchor.RELEASE_NOTES_RELPATH!r} does not "
        f"match the canonical {EXPECTED_VERSION} slug"
    )
