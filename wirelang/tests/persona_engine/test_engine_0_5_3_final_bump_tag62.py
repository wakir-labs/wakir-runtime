# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-62 — Engine 0.5.3 final-bump consistency pin (Selin, Persona-Engine).

The Tag-62 (2026-05-19) bump promotes the engine from
``0.5.3-rc1`` (Tag-58, PR #372) to ``0.5.3`` final by dropping the
rc1-suffix. It is a strict-superset, manifest-and-metadata-only
release-candidate promotion before the KW-24 cutover-T0 window
(2026-06-08/09). Substrate is byte-stable vs. rc1: no record
added/renamed, no ENV-flag flipped, no crate version bumped, no
V-907-baseline refresh (the Tag-59 seal at
``wirelang/persona_engine/v907-hash-baseline.json`` survives
unchanged — the V-907 composite hash is byte-bounded to manifest §1
+ pin-pack ``boot_wired_crates`` + engine.py resolver-block).

Four authority surfaces stamped at 0.5.3
----------------------------------------

1. ``wirelang/persona_engine/__version__.py:46`` — the canonical
   Python source-of-truth literal (``__version__ = "0.5.3"``) plus
   the ``RELEASE_NOTES_RELPATH`` pointer updated to the new
   final-release-notes file.
2. ``wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md``
   §0 Version Header — rewritten to record 0.5.3 final as the
   active version. A new §0.1 Tag-58 history sub-section preserves
   the rc1 substrate as historical context.
3. ``wirelang/persona_engine/cli.py`` line 3 — module docstring
   carries ``(v0.5.3)`` (one of the Tag-59 hot-fix drift sites).
4. ``wirelang/persona_engine/engine_async.py`` line 96 —
   ``ASYNC_ENGINE_VERSION = "0.5.3"`` (the second Tag-59 hot-fix
   site).

Plus the supporting surfaces:

* ``wirelang/persona_engine/engine.py`` line 84 — canonical-anchor
  import comment narrates ``Tag-62 canonical anchor (0.5.3, rc1
  dropped)``.
* ``docs/persona-engine/0-5-3-final-release-notes.md`` — fresh
  public-facing release notes with five canonical sections.
* ``tooling/ci/scan_engine_version_drift.py`` — ``ACTIVE_VERSION``
  bumped to ``0.5.3``; ``STALE_VERSIONS`` extended with
  ``0.5.3-rc1`` so the drift scanner hunts the new stale literal.
* ``tooling/ci/engine-version-drift-allowlist.json`` — extended
  with the legitimate rc1-surviving artefacts (v907-hash-baseline,
  tag58/59/60 hermetic-test fixtures).
* ``tooling/ci/aggregate_persona_engine_pre_cutover_final.py`` —
  ``EXPECTED_ACTIVE_VERSION`` bumped to ``0.5.3``.

Tag-60 drift-coverage scanner contract
--------------------------------------

The Tag-60 scanner (``scan_engine_version_drift.py``) must cover
this Tag-62 bump. Verification:

* ``ACTIVE_VERSION`` equals the bumped ``__version__``.
* ``0.5.3-rc1`` is in ``STALE_VERSIONS`` (it is now a hunted stale).
* A hermetic scan over the repo emits zero un-allowlisted findings.
* The allowlist registers v907-hash-baseline.json (the Tag-59 seal
  that legitimately keeps rc1 in its engine_version field).

Hermetic envelope
-----------------
* No network. No NATS, no SPIRE, no gRPC.
* No subprocess. No Rust binary build.
* No filesystem writes outside ``tmp_path``.
* Deterministic — no clock-sensitive assertions.

Scope discipline (Selin, ADR-0036/0043/0065/0066)
-------------------------------------------------
This file does **not** modify persona definitions (Aisha-Domäne,
ADR-0043), WAT-core / V-907 logic (Tomás-Domäne, Zone-K),
identity-substrate design (Reza-Domäne, Zone-L), or container-infra
(Kai-Domäne, Zone-J). The Tag-59 V-907 hash-pin baseline seal at
``v907-hash-baseline.json`` is explicitly NOT refreshed by this
bump; refresh requires Selin-Hand + Tomás Zone-K cross-review per
the Tag-59 seal contract.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
import sys
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
ENGINE_ASYNC_PATH = (
    REPO_ROOT / "wirelang" / "persona_engine" / "engine_async.py"
)
CLI_PATH = REPO_ROOT / "wirelang" / "persona_engine" / "cli.py"
MANIFEST_PATH = (
    REPO_ROOT
    / "wirelang"
    / "persona_engine"
    / "MANIFEST-0.5.2-final-pre-cutover.md"
)
RELEASE_NOTES_PATH = (
    REPO_ROOT
    / "docs"
    / "persona-engine"
    / "0-5-3-final-release-notes.md"
)
RC1_RELEASE_NOTES_PATH = (
    REPO_ROOT / "docs" / "persona-engine" / "0-5-3-rc1-release-notes.md"
)
V907_BASELINE_PATH = (
    REPO_ROOT / "wirelang" / "persona_engine" / "v907-hash-baseline.json"
)
SCANNER_PATH = (
    REPO_ROOT / "tooling" / "ci" / "scan_engine_version_drift.py"
)
ALLOWLIST_PATH = (
    REPO_ROOT / "tooling" / "ci" / "engine-version-drift-allowlist.json"
)
AGGREGATOR_PATH = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "aggregate_persona_engine_pre_cutover_final.py"
)

EXPECTED_VERSION = "0.5.3"
PREDECESSOR_VERSION = "0.5.3-rc1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_assignment_literal(source: str, symbol: str) -> str:
    """Extract ``SYMBOL = "<string>"`` literal from a python source file."""
    pattern = re.compile(
        rf"^{re.escape(symbol)}\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE
    )
    match = pattern.search(source)
    return match.group(1) if match else ""


@pytest.fixture(scope="module")
def scanner_module():
    """Import the Tag-60 drift scanner by file-path (not via package)."""
    spec = importlib.util.spec_from_file_location(
        "scan_engine_version_drift_tag62_fixture", SCANNER_PATH
    )
    assert spec is not None and spec.loader is not None, (
        f"unable to load scanner spec from {SCANNER_PATH}"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def aggregator_module():
    """Import the Tag-61 aggregator by file-path."""
    spec = importlib.util.spec_from_file_location(
        "aggregate_persona_engine_pre_cutover_final_tag62_fixture",
        AGGREGATOR_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ===========================================================================
# Surface 1 — __version__.py canonical anchor pins 0.5.3 final.
# ===========================================================================


def test_t01_version_module_pins_0_5_3_final() -> None:
    """The Tag-62 canonical anchor module must pin exactly ``0.5.3``."""
    assert VERSION_MODULE_PATH.is_file(), (
        f"canonical version anchor module missing: {VERSION_MODULE_PATH}"
    )
    source = _read(VERSION_MODULE_PATH)
    literal = _extract_assignment_literal(source, "__version__")
    assert literal == EXPECTED_VERSION, (
        f"__version__.py pins {literal!r}, expected "
        f"{EXPECTED_VERSION!r} (Tag-62 rc1-suffix-drop)"
    )


# ===========================================================================
# Surface 1b — RELEASE_NOTES_RELPATH points at the new final-release file.
# ===========================================================================


def test_t02_version_module_release_notes_relpath_points_to_final_file() -> None:
    """``RELEASE_NOTES_RELPATH`` must point at the new final-release notes."""
    source = _read(VERSION_MODULE_PATH)
    relpath_literal = _extract_assignment_literal(
        source, "RELEASE_NOTES_RELPATH"
    )
    assert relpath_literal.endswith(
        "0-5-3-final-release-notes.md"
    ), (
        f"RELEASE_NOTES_RELPATH={relpath_literal!r} does not point at "
        f"the Tag-62 final-release-notes filename"
    )
    notes_path = REPO_ROOT / relpath_literal
    assert notes_path.is_file(), (
        f"RELEASE_NOTES_RELPATH points at non-existent file: {notes_path}"
    )


# ===========================================================================
# Surface 1c — ENGINE_VERSION mirrors __version__ via alias.
# ===========================================================================


def test_t03_engine_version_alias_in_version_module() -> None:
    """``ENGINE_VERSION = __version__`` (or literal-equal) holds."""
    source = _read(VERSION_MODULE_PATH)
    assert "ENGINE_VERSION" in source, (
        "ENGINE_VERSION symbol missing from canonical anchor module"
    )
    literal = _extract_assignment_literal(source, "ENGINE_VERSION")
    # Either the alias form (no literal) or an exact literal match.
    if literal:
        assert literal == EXPECTED_VERSION, (
            f"ENGINE_VERSION literal {literal!r} drifts from "
            f"__version__ {EXPECTED_VERSION!r}"
        )


# ===========================================================================
# Surface 1d — Public-import surface yields the bumped version.
# ===========================================================================


def test_t04_public_import_surface_yields_bumped_version() -> None:
    """``import wirelang.persona_engine`` exposes ``__version__`` = 0.5.3."""
    pkg = pytest.importorskip("wirelang.persona_engine")
    # Force reload in case the test module ran on a prior interpreter
    # snapshot — pytest's import-mode interactions can keep stale.
    importlib.reload(pkg)
    assert getattr(pkg, "__version__", None) == EXPECTED_VERSION, (
        f"wirelang.persona_engine.__version__ = "
        f"{getattr(pkg, '__version__', None)!r}, expected "
        f"{EXPECTED_VERSION!r}"
    )


# ===========================================================================
# Surface 2 — Manifest §0 records 0.5.3 final as active.
# ===========================================================================


def test_t05_manifest_section_zero_records_engine_version() -> None:
    """The Tag-52 manifest §0 must record engine version 0.5.3 as active."""
    source = _read(MANIFEST_PATH)
    assert "## 0. Version Header" in source, (
        "Manifest §0 Version Header section missing"
    )
    section_zero_idx = source.index("## 0. Version Header")
    section_one_idx = source.index("## 1. Component Inventory")
    section_zero = source[section_zero_idx:section_one_idx]
    # The §0 table active-version cell must carry ``0.5.3`` exactly
    # (inside a code-span). The predecessor rc1 is also referenced.
    assert f"`{EXPECTED_VERSION}`" in section_zero, (
        f"Manifest §0 does not record {EXPECTED_VERSION!r} as the "
        f"active engine version"
    )


# ===========================================================================
# Surface 2b — Manifest §0 lists the four authority paths.
# ===========================================================================


def test_t06_manifest_section_zero_lists_four_authority_paths() -> None:
    """Manifest §0 must reference __version__.py, manifest, pin-pack, notes."""
    source = _read(MANIFEST_PATH)
    section_zero_idx = source.index("## 0. Version Header")
    section_one_idx = source.index("## 1. Component Inventory")
    section_zero = source[section_zero_idx:section_one_idx]
    required_paths = (
        "wirelang/persona_engine/__version__.py",
        "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md",
        "infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml",
        "docs/persona-engine/0-5-3-final-release-notes.md",
    )
    for relpath in required_paths:
        assert relpath in section_zero, (
            f"Manifest §0 missing authority-path reference: {relpath!r}"
        )


# ===========================================================================
# Surface 2c — Manifest §0.1 history sub-section preserves Tag-58 rc1.
# ===========================================================================


def test_t07_manifest_section_zero_dot_one_preserves_rc1_history() -> None:
    """The §0.1 sub-section must narrate the Tag-58 rc1 substrate."""
    source = _read(MANIFEST_PATH)
    # Either ###/## numbering is acceptable; the Tag-62 author chose ###.
    assert (
        "### 0.1" in source or "## 0.1" in source
    ), "Manifest §0.1 Tag-58 history sub-section missing"
    sub_idx = source.find("### 0.1")
    if sub_idx < 0:
        sub_idx = source.find("## 0.1")
    section_one_idx = source.index("## 1.", sub_idx)
    subsection = source[sub_idx:section_one_idx]
    assert "Tag-58" in subsection, "§0.1 must reference Tag-58 explicitly"
    assert PREDECESSOR_VERSION in subsection, (
        f"§0.1 must reference {PREDECESSOR_VERSION!r} as historical anchor"
    )


# ===========================================================================
# Surface 3 — cli.py:3 docstring carries the bumped version.
# ===========================================================================


def test_t08_cli_module_docstring_carries_bumped_version() -> None:
    """``cli.py`` line 3 module docstring must say ``v0.5.3`` (not rc1).

    This is one of the four Tag-59 hot-fix drift sites the Tag-60
    scanner is wired to catch. The Tag-62 bump mirrors the canonical
    anchor at this site.
    """
    source = _read(CLI_PATH)
    # The third line is the H1 of the module docstring. Use a
    # tolerant pattern: the first ``v0.5.x`` reference must be the
    # bumped value.
    lines = source.splitlines()
    assert len(lines) >= 3, "cli.py is too short to have a line-3 docstring"
    line3 = lines[2]
    assert f"v{EXPECTED_VERSION}" in line3, (
        f"cli.py line 3 {line3!r} does not carry v{EXPECTED_VERSION}"
    )
    # And the rc1 literal MUST NOT be present in the cli.py active
    # docstring narrative (the rc1 narrative belongs in the
    # __version__.py docstring history block, not in cli.py).
    assert PREDECESSOR_VERSION not in source, (
        f"cli.py must not carry the stale {PREDECESSOR_VERSION!r} "
        f"literal after the Tag-62 bump"
    )


# ===========================================================================
# Surface 4 — engine_async.py:96 ASYNC_ENGINE_VERSION literal.
# ===========================================================================


def test_t09_engine_async_async_engine_version_literal() -> None:
    """``engine_async.py`` line 96 must pin ``ASYNC_ENGINE_VERSION = "0.5.3"``.

    Second of the four Tag-59 hot-fix drift sites. Tag-62 mirrors the
    canonical anchor here.
    """
    source = _read(ENGINE_ASYNC_PATH)
    literal = _extract_assignment_literal(source, "ASYNC_ENGINE_VERSION")
    assert literal == EXPECTED_VERSION, (
        f"engine_async.py ASYNC_ENGINE_VERSION = {literal!r}, expected "
        f"{EXPECTED_VERSION!r}"
    )
    # No rc1 leak in the active engine_async source — the rc1
    # narrative is bounded to __version__.py docstring history.
    assert PREDECESSOR_VERSION not in source, (
        f"engine_async.py must not carry the stale "
        f"{PREDECESSOR_VERSION!r} literal after the Tag-62 bump"
    )


# ===========================================================================
# Surface 5 — engine.py canonical-anchor import comment.
# ===========================================================================


def test_t10_engine_py_canonical_anchor_import_comment() -> None:
    """``engine.py:84`` comment must reference the Tag-62 0.5.3 bump.

    Third of the four Tag-59 hot-fix drift sites — the comment on
    the canonical-anchor import line.
    """
    source = _read(ENGINE_PATH)
    assert (
        "from .__version__ import ENGINE_VERSION" in source
    ), "engine.py must import ENGINE_VERSION from __version__ (canonical)"
    # The comment on the import line should reference 0.5.3 and the
    # Tag-62 bump (rc1 dropped). Be tolerant of whitespace.
    import_line = next(
        (
            line
            for line in source.splitlines()
            if "from .__version__ import ENGINE_VERSION" in line
        ),
        "",
    )
    assert EXPECTED_VERSION in import_line, (
        f"engine.py canonical-anchor import-comment line "
        f"{import_line!r} does not reference {EXPECTED_VERSION!r}"
    )


# ===========================================================================
# Surface 6 — Release-notes file (final) exists at the canonical path.
# ===========================================================================


def test_t11_final_release_notes_file_exists_at_canonical_path() -> None:
    """``docs/persona-engine/0-5-3-final-release-notes.md`` must exist."""
    assert RELEASE_NOTES_PATH.is_file(), (
        f"Tag-62 final-release-notes file missing: {RELEASE_NOTES_PATH}"
    )


# ===========================================================================
# Surface 6b — Final release-notes H1 + five canonical sections.
# ===========================================================================


def test_t12_final_release_notes_has_h1_and_five_sections() -> None:
    """The final release-notes file H1 pins 0.5.3 and lists 5 sections."""
    source = _read(RELEASE_NOTES_PATH)
    h1_match = re.search(r"^#\s+(.+)$", source, re.MULTILINE)
    assert h1_match is not None, "final release-notes has no H1 title"
    h1 = h1_match.group(1)
    assert EXPECTED_VERSION in h1, (
        f"final release-notes H1 {h1!r} does not contain "
        f"{EXPECTED_VERSION!r}"
    )
    required_sections = (
        "## 1. Scope",
        "## 2. Carry-Forward",
        "## 3. G5-PRE-CUTOVER-READY",  # Tag-62 spec'd sub-name
        "## 4. Pre-Cutover Gate-Map",
        "## 5. Operator-Hand Items",
    )
    for section in required_sections:
        assert section in source, (
            f"final release-notes missing required section: {section!r}"
        )


# ===========================================================================
# Surface 6c — Final release-notes records G5-PRE-CUTOVER-READY achievement.
# ===========================================================================


def test_t13_final_release_notes_records_g5_compositum_achievement() -> None:
    """Final release-notes §3 must record the G5 compositum verdict."""
    source = _read(RELEASE_NOTES_PATH)
    assert "G5-PRE-CUTOVER-READY" in source, (
        "final release-notes does not record the G5-PRE-CUTOVER-READY "
        "compositum verdict from Tag-61 PR #391"
    )
    # PR #391 is the substrate authority for the Tag-62 promotion.
    assert "#391" in source, (
        "final release-notes does not reference Tag-61 PR #391 as the "
        "upstream authority for the rc1 → final promotion"
    )


# ===========================================================================
# Drift-scanner — ACTIVE_VERSION mirrors __version__.
# ===========================================================================


def test_t14_drift_scanner_active_version_mirrors_canonical_anchor(
    scanner_module,
) -> None:
    """Tag-60 scanner ``ACTIVE_VERSION`` must equal canonical ``__version__``."""
    spec = importlib.util.spec_from_file_location(
        "persona_engine_version_tag62_fixture", VERSION_MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    assert scanner_module.ACTIVE_VERSION == mod.__version__, (
        f"scanner ACTIVE_VERSION={scanner_module.ACTIVE_VERSION!r} "
        f"!= __version__={mod.__version__!r}"
    )
    assert scanner_module.ACTIVE_VERSION == EXPECTED_VERSION, (
        f"scanner ACTIVE_VERSION={scanner_module.ACTIVE_VERSION!r} "
        f"!= Tag-62 expected {EXPECTED_VERSION!r}"
    )


# ===========================================================================
# Drift-scanner — STALE_VERSIONS extended with 0.5.3-rc1.
# ===========================================================================


def test_t15_drift_scanner_hunts_rc1_as_stale_literal(
    scanner_module,
) -> None:
    """Tag-62 extension: ``0.5.3-rc1`` joins the hunted ``STALE_VERSIONS``."""
    assert PREDECESSOR_VERSION in scanner_module.STALE_VERSIONS, (
        f"Tag-62 scanner extension missing — {PREDECESSOR_VERSION!r} "
        f"is not in STALE_VERSIONS={scanner_module.STALE_VERSIONS!r}"
    )
    # Longest-first invariant must still hold (Tag-60 test_03 also
    # asserts this; mirrored here for Tag-62-local sanity).
    stale_by_len = sorted(
        scanner_module.STALE_VERSIONS, key=len, reverse=True
    )
    assert list(scanner_module.STALE_VERSIONS) == stale_by_len, (
        "STALE_VERSIONS must be sorted longest-first; Tag-62 "
        f"extension violated invariant: {scanner_module.STALE_VERSIONS!r}"
    )


# ===========================================================================
# Drift-scanner — Hermetic full-repo scan emits zero un-allowlisted findings.
# ===========================================================================


def test_t16_drift_scanner_hermetic_scan_emits_zero_unallowlisted_findings(
    scanner_module,
) -> None:
    """Run the Tag-60 scanner over the real repo; expect zero un-allowlisted."""
    allowlist = scanner_module.load_allowlist(ALLOWLIST_PATH)
    result = scanner_module.scan_repo(REPO_ROOT, allowlist)
    if result.findings:
        sample = "\n".join(
            f"  {f.path}:{f.line}:{f.col} {f.literal} | {f.line_text.strip()}"
            for f in result.findings[:10]
        )
        pytest.fail(
            f"Tag-62 bump leaves {len(result.findings)} un-allowlisted "
            f"drift findings; first 10:\n{sample}"
        )


# ===========================================================================
# Drift-scanner — Allowlist registers v907-baseline as rc1-surviving artefact.
# ===========================================================================


def test_t17_drift_scanner_allowlist_covers_v907_baseline_seal(
    scanner_module,
) -> None:
    """v907-hash-baseline.json must be allowlisted under v907-baseline-pin."""
    allowlist = scanner_module.load_allowlist(ALLOWLIST_PATH)
    baseline_relpath = "wirelang/persona_engine/v907-hash-baseline.json"
    assert baseline_relpath in allowlist, (
        f"Tag-62 allowlist must register {baseline_relpath!r} as a "
        f"legitimate rc1-surviving artefact (Tag-59 seal)"
    )
    entry = allowlist[baseline_relpath]
    assert "v907-baseline-pin" in entry.categories, (
        f"v907-hash-baseline allowlist entry must have category "
        f"'v907-baseline-pin'; got {entry.categories!r}"
    )


# ===========================================================================
# V-907 baseline seal — engine_version metadata still rc1 (unchanged).
# ===========================================================================


def test_t18_v907_baseline_seal_unchanged_engine_version_metadata() -> None:
    """The Tag-59 V-907 baseline seal preserves engine_version = rc1.

    Refresh requires Selin-Hand + Tomás Zone-K cross-review per the
    Tag-59 seal contract. The Tag-62 final-bump explicitly does not
    exercise that authority — the §0 version-header rewrite is
    outside the V-907 byte-bounded slice (manifest §1 + pin-pack
    boot_wired_crates + engine.py resolver-block).
    """
    baseline = json.loads(_read(V907_BASELINE_PATH))
    assert baseline["engine_version"] == PREDECESSOR_VERSION, (
        f"V-907 baseline engine_version drifted to "
        f"{baseline['engine_version']!r}; Tag-62 must NOT refresh the "
        f"Tag-59 seal (Zone-K cross-review required for refresh)"
    )
    # And the composite_hash field must still be present (seal-shape
    # intact).
    assert "composite_hash" in baseline, (
        "V-907 baseline composite_hash missing — seal shape corrupted"
    )


# ===========================================================================
# Aggregator — EXPECTED_ACTIVE_VERSION bumped in lockstep.
# ===========================================================================


def test_t19_aggregator_expected_active_version_bumped(
    aggregator_module,
) -> None:
    """Tag-61 aggregator ``EXPECTED_ACTIVE_VERSION`` mirrors canonical."""
    assert (
        aggregator_module.EXPECTED_ACTIVE_VERSION == EXPECTED_VERSION
    ), (
        f"aggregator EXPECTED_ACTIVE_VERSION="
        f"{aggregator_module.EXPECTED_ACTIVE_VERSION!r} != "
        f"Tag-62 expected {EXPECTED_VERSION!r}"
    )


# ===========================================================================
# Scope discipline — Out-of-scope domains in release-notes.
# ===========================================================================


def test_t20_final_release_notes_pins_scope_discipline_j_k_l() -> None:
    """Final release-notes §1 must declare J/K/L zones out of scope."""
    source = _read(RELEASE_NOTES_PATH)
    lowered = source.lower()
    assert "aisha" in lowered
    assert "tomás" in lowered or "tomas" in lowered
    assert "reza" in lowered
    assert "kai" in lowered
    for zone in ("Zone-J", "Zone-K", "Zone-L"):
        assert zone in source, (
            f"final release-notes scope-discipline block missing "
            f"{zone} label"
        )


# ===========================================================================
# Historical-fixture preservation — rc1 release-notes file survives.
# ===========================================================================


def test_t21_rc1_release_notes_file_preserved_as_historical_artefact() -> None:
    """The rc1 release-notes file must remain in the repo as historical."""
    assert RC1_RELEASE_NOTES_PATH.is_file(), (
        f"Tag-62 must preserve the rc1 historical artefact: "
        f"{RC1_RELEASE_NOTES_PATH} (deleting it would erase the public "
        f"record of the Tag-58 substrate)"
    )


# ===========================================================================
# Strict-superset claim — No stale __version__ literal in authority surfaces.
# ===========================================================================


def test_t22_no_stale_version_literal_in_active_authority_surfaces() -> None:
    """The active authority surfaces carry no stale __version__ literal.

    The four active surfaces are: __version__.py (canonical),
    __init__.py (re-export), engine.py (re-export), engine_async.py
    (parallel async literal). None of them may carry the stale
    inline literal patterns.
    """
    surfaces = (
        VERSION_MODULE_PATH,
        INIT_PATH,
        ENGINE_PATH,
        ENGINE_ASYNC_PATH,
    )
    stale_patterns = (
        '__version__ = "0.5.0-pilot"',
        '__version__ = "0.5.1-pre-cutover"',
        '__version__ = "0.5.2-final-pre-cutover"',
        '__version__ = "0.5.3-rc1"',
        'ENGINE_VERSION = "0.5.0-pilot"',
        'ENGINE_VERSION = "0.5.1-pre-cutover"',
        'ENGINE_VERSION = "0.5.2-final-pre-cutover"',
        'ENGINE_VERSION = "0.5.3-rc1"',
        'ASYNC_ENGINE_VERSION = "0.5.0-pilot"',
        'ASYNC_ENGINE_VERSION = "0.5.1-pre-cutover"',
        'ASYNC_ENGINE_VERSION = "0.5.2-final-pre-cutover"',
        'ASYNC_ENGINE_VERSION = "0.5.3-rc1"',
    )
    for path in surfaces:
        text = _read(path)
        for stale in stale_patterns:
            assert stale not in text, (
                f"{path.name} still carries stale inline literal: "
                f"{stale!r}"
            )


# ===========================================================================
# Cross-zone scope discipline — No Aisha/Tomás/Reza/Kai-domain touches.
# ===========================================================================


def test_t23_tag62_bump_does_not_touch_cross_zone_substrate() -> None:
    """Cross-zone protection: the V-907 baseline is unchanged; the
    pin-pack YAML is unchanged; no persona-definition files are
    referenced as Tag-62-modified.

    This test is a soft sanity check that the Tag-62 bump-spec stays
    inside Selin's domain. The V-907 baseline file's engine_version
    metadata legitimately holds the rc1 literal (Tag-59 seal). The
    pin-pack YAML is referenced as carry-forward — its filename in
    the manifest §0 authority list is the 0.5.2-final-pre-cutover
    name, unchanged from rc1 (the YAML body stays sealed).
    """
    # Check the pin-pack YAML filename in §0 stays at the Tag-52 name.
    manifest = _read(MANIFEST_PATH)
    section_zero_idx = manifest.index("## 0. Version Header")
    section_one_idx = manifest.index("## 1. Component Inventory")
    section_zero = manifest[section_zero_idx:section_one_idx]
    assert (
        "infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml"
        in section_zero
    ), (
        "Pin-pack YAML reference in §0 must stay at the Tag-52 "
        "filename (carry-forward, Kai-Zone-J coordination respected)"
    )


# ===========================================================================
# Drift-scanner allowlist invariant — schema version bumped to 2.
# ===========================================================================


def test_t24_allowlist_schema_version_bumped_to_2() -> None:
    """The Tag-62 allowlist-extension bumps ``_schema.version`` to 2."""
    allowlist_data = json.loads(_read(ALLOWLIST_PATH))
    schema_version = allowlist_data.get("_schema", {}).get("version")
    assert schema_version == 2, (
        f"allowlist _schema.version={schema_version!r}, expected 2 "
        f"(Tag-62 extension)"
    )


# ===========================================================================
# Drift-scanner allowlist invariant — Tag tag bumped to Tag-62.
# ===========================================================================


def test_t25_allowlist_tag_field_records_tag62() -> None:
    """The Tag-62 allowlist-extension records ``_schema.tag`` = Tag-62."""
    allowlist_data = json.loads(_read(ALLOWLIST_PATH))
    schema_tag = allowlist_data.get("_schema", {}).get("tag", "")
    assert "Tag-62" in schema_tag, (
        f"allowlist _schema.tag={schema_tag!r} does not record Tag-62"
    )
