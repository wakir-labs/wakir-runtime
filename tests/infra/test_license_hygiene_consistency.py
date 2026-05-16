# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""License-Hygiene consistency tests (ADR-0061 Schritt 8).

These hermetic tests cement the externer-Audit-Empfehlung 1:1 in the
test suite, so any drift away from the ADR-0061 Sollstellung breaks
the License-Gate CI. The test vectors mirror the Acceptance-Gates
listed at the bottom of ADR-0061:

* ``LICENSING.md`` exists, lists all expected paths.
* ``LICENSES/`` carries the three full-text files
  (Apache-2.0, BUSL-1.1, CC-BY-4.0).
* Every BSL-Subtree carries ``LICENSE-BSL.md`` without entwurfs-
  wording ("draft", "subject to legal review",
  "pending legal review").
* ``pyproject.toml`` ``license-files`` list covers all six
  LICENSE-BSL paths.
* WAT-Change-Date concretely ``2030-05-07``.
* ``NOTICE`` is schlank (≤ 4 lines core text, no Governance-Narrative).
* ``README.md`` contains the LICENSING.md reference plus the
  Mix-License-Hinweis-Block.

Sub-Items the test does *not* touch:

* Full-text content of ``LICENSES/*.txt`` — that is REUSE's job and
  Reza's PR scope. We only assert existence + a substance marker.
* The wording of LICENSE-BSL.md (final or otherwise) beyond the
  draft-token absence — that is Júlia's PR scope.
* `bin/`-Shim relicensing — that is Reza's PR scope; the License-
  Gate workflow has a Stage-5 generic Apache-Shim-um-BUSL scanner
  for the runtime invariant.

Test-Vector matrix (15 vectors, all hermetic, no live network):

* TV-LH-01..03: LICENSING.md existence + mix-license-header + path-map.
* TV-LH-04..06: LICENSES/ Apache-2.0.txt + BUSL-1.1.txt + CC-BY-4.0.txt.
* TV-LH-07..10: Each BSL-Subtree carries LICENSE-BSL.md with no
  entwurfs-wording.
* TV-LH-11..12: pyproject.toml license-files complete.
* TV-LH-13: WAT-Change-Date is ``2030-05-07``.
* TV-LH-14: NOTICE schlank (≤ 4 lines core text).
* TV-LH-15: README contains LICENSING.md reference + Mix-License-
  Hinweis-Block.

The test is written to run on the live repo state. While the
License-Hygiene-Welle is in flight (Júlia, Tomás, Reza, Selin in
parallel), individual vectors will be RED — that is by design; the
test surfaces the missing items for the merge-coordination loop.
Once all four parallel PRs (and this Kai-PR) are merged, the full
set must turn green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# TV-LH-01..03  LICENSING.md (ADR-0061 Schritt 1)
# ---------------------------------------------------------------------------

# Every path listed in the ADR-0061 §1 table must appear (literally or
# as the substring shown) in LICENSING.md. The substring is the *path*
# token, not the full table row — we only assert presence so that a
# documentation re-flow does not break the test.
LICENSING_MD_EXPECTED_PATHS: tuple[str, ...] = (
    "wirelang/",
    "wat/",
    "wat/anchor/external_verifier/",
    "wirelang/federation/",
    "wirelang/persona_engine/",
    "infra/spire/federation/",
    "infra/spire/agent/",
    "infra/persona-engine/",
    "docs/",
    "tooling/",
    "tests/",
)

LICENSING_MD_EXPECTED_HEADERS: tuple[str, ...] = (
    # The autoritative license-map narrative must be present.
    "mixed-license",
    # All three license families must be named.
    "Apache-2.0",
    "BUSL-1.1",
    "CC-BY-4.0",
)


def test_tv_lh_01_licensing_md_exists() -> None:
    """TV-LH-01: ``LICENSING.md`` exists at repo root."""
    path = REPO_ROOT / "LICENSING.md"
    assert path.exists(), (
        "LICENSING.md is missing at repo root. ADR-0061 Schritt 1 "
        "requires it as the authoritative license-map."
    )


def test_tv_lh_02_licensing_md_mix_license_header() -> None:
    """TV-LH-02: LICENSING.md announces mix-license + names all three families."""
    path = REPO_ROOT / "LICENSING.md"
    if not path.exists():
        pytest.skip("LICENSING.md not yet present (TV-LH-01 covers existence)")
    text = path.read_text(encoding="utf-8").lower()
    missing = [h for h in LICENSING_MD_EXPECTED_HEADERS if h.lower() not in text]
    assert not missing, (
        f"LICENSING.md is missing required header markers: {missing}. "
        f"ADR-0061 Schritt 1 mandates the mix-license narrative plus the "
        f"three license families."
    )


def test_tv_lh_03_licensing_md_path_map_complete() -> None:
    """TV-LH-03: LICENSING.md path-map names all expected sub-tree paths."""
    path = REPO_ROOT / "LICENSING.md"
    if not path.exists():
        pytest.skip("LICENSING.md not yet present (TV-LH-01 covers existence)")
    text = path.read_text(encoding="utf-8")
    missing = [p for p in LICENSING_MD_EXPECTED_PATHS if p not in text]
    assert not missing, (
        f"LICENSING.md is missing required path-map entries: {missing}. "
        f"ADR-0061 Schritt 1 mandates the full Pfad→Lizenz-Tabelle."
    )


# ---------------------------------------------------------------------------
# TV-LH-04..06  LICENSES/ full-text directory (ADR-0061 Schritt 2)
# ---------------------------------------------------------------------------

# Each license full-text must contain at least its license name in
# the first kilobyte — we only check for a marker, not the canonical
# full text (`reuse lint` does the latter).
LICENSES_FULLTEXT_FILES: tuple[tuple[str, str], ...] = (
    ("LICENSES/Apache-2.0.txt", "Apache License"),
    ("LICENSES/BUSL-1.1.txt", "Business Source License"),
    ("LICENSES/CC-BY-4.0.txt", "Creative Commons"),
)


@pytest.mark.parametrize("rel,marker", LICENSES_FULLTEXT_FILES)
def test_tv_lh_04_06_licenses_dir_carries_fulltext(rel: str, marker: str) -> None:
    """TV-LH-04..06: ``LICENSES/`` ships canonical full-text files."""
    path = REPO_ROOT / rel
    assert path.exists(), (
        f"{rel} missing. ADR-0061 Schritt 2 requires the three license "
        f"full-texts under LICENSES/ for REUSE-3.0 compliance."
    )
    head = path.read_text(encoding="utf-8", errors="replace")[:4096]
    assert marker in head, (
        f"{rel} does not contain the expected substance marker '{marker}' "
        f"in its first 4 KiB. Likely a placeholder file, not the canonical "
        f"upstream full text."
    )


# ---------------------------------------------------------------------------
# TV-LH-07..10  BSL-Subtree LICENSE-BSL.md without entwurfs-wording
# ---------------------------------------------------------------------------

# All six BSL-Subtrees per ADR-0059 + ADR-0061. The provisioner unit
# (ADR-0058) is listed alongside as it ships its own LICENSE-BSL.md.
BSL_SUBTREES_LICENSE_FILES: tuple[str, ...] = (
    "wat/LICENSE-BSL.md",
    "wirelang/federation/LICENSE-BSL.md",
    "wirelang/persona_engine/LICENSE-BSL.md",
    "infra/spire/federation/LICENSE-BSL.md",
    "infra/spire/agent/LICENSE-BSL.md",
    "infra/persona-engine/LICENSE-BSL.md",
)

ENTWURFS_TOKENS: tuple[str, ...] = (
    "draft",
    "subject to legal review",
    "pending legal review",
)


@pytest.mark.parametrize("rel", BSL_SUBTREES_LICENSE_FILES)
def test_tv_lh_07_10_bsl_subtree_license_exists(rel: str) -> None:
    """TV-LH-07a..10a: Each BSL-Subtree carries LICENSE-BSL.md."""
    path = REPO_ROOT / rel
    assert path.exists(), (
        f"{rel} missing. Every BSL-Subtree per ADR-0059 + ADR-0061 must "
        f"ship its own LICENSE-BSL.md with Change-Date / Change-License / "
        f"Additional-Use-Grant fields."
    )


@pytest.mark.parametrize("rel", BSL_SUBTREES_LICENSE_FILES)
def test_tv_lh_07_10_bsl_subtree_license_no_entwurfs_wording(rel: str) -> None:
    """TV-LH-07b..10b: LICENSE-BSL.md is free of entwurfs-wording.

    ADR-0061 §3: the BUSL texts must be final. Any occurrence of
    "draft", "subject to legal review", or "pending legal review" is
    a violation.
    """
    path = REPO_ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} not yet present (existence covered above)")
    text = path.read_text(encoding="utf-8").lower()
    hits = [tok for tok in ENTWURFS_TOKENS if tok in text]
    assert not hits, (
        f"{rel} still carries entwurfs-wording: {hits}. ADR-0061 §3 "
        f"requires the BUSL texts to be final for this release."
    )


# ---------------------------------------------------------------------------
# TV-LH-11..12  pyproject.toml license-files completeness
# ---------------------------------------------------------------------------

# ADR-0061 Schritt 6 mandates the exact license-files list.
PYPROJECT_LICENSE_FILES_EXPECTED: tuple[str, ...] = (
    "LICENSE",
    "NOTICE",
    "LICENSES/Apache-2.0.txt",
    "LICENSES/BUSL-1.1.txt",
    "LICENSES/CC-BY-4.0.txt",
    "wat/LICENSE-BSL.md",
    "wirelang/federation/LICENSE-BSL.md",
    "wirelang/persona_engine/LICENSE-BSL.md",
    "infra/spire/federation/LICENSE-BSL.md",
    "infra/spire/agent/LICENSE-BSL.md",
    "infra/persona-engine/LICENSE-BSL.md",
)


def _read_pyproject() -> str:
    return (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_tv_lh_11_pyproject_license_spdx_expression() -> None:
    """TV-LH-11: pyproject.toml carries the union SPDX expression."""
    text = _read_pyproject()
    # Either string form or table form is acceptable; both must contain
    # the union expression literally.
    assert "Apache-2.0 AND BUSL-1.1" in text, (
        "pyproject.toml is missing the union license expression "
        "'Apache-2.0 AND BUSL-1.1'. ADR-0061 Schritt 6 mandates this."
    )


def test_tv_lh_12_pyproject_license_files_complete() -> None:
    """TV-LH-12: pyproject.toml license-files lists all expected paths."""
    text = _read_pyproject()
    # We grep-substring rather than parse-TOML so the test does not
    # depend on the build-time TOML parser. Each expected path must
    # appear at least once as a literal substring.
    missing = [p for p in PYPROJECT_LICENSE_FILES_EXPECTED if p not in text]
    assert not missing, (
        f"pyproject.toml license-files is missing: {missing}. "
        f"ADR-0061 Schritt 6 mandates the complete list."
    )


# ---------------------------------------------------------------------------
# TV-LH-13  WAT-Change-Date konkret = 2030-05-07
# ---------------------------------------------------------------------------


def test_tv_lh_13_wat_change_date_concrete() -> None:
    """TV-LH-13: ``wat/LICENSE-BSL.md`` states Change-Date 2030-05-07."""
    path = REPO_ROOT / "wat" / "LICENSE-BSL.md"
    if not path.exists():
        pytest.skip("wat/LICENSE-BSL.md missing (TV-LH-07 covers existence)")
    text = path.read_text(encoding="utf-8")
    assert "2030-05-07" in text, (
        "wat/LICENSE-BSL.md does not state the canonical WAT Change-Date "
        "2030-05-07. ADR-0061 Schritt 4 requires the concrete date "
        "(4 years after ADR-0034 approval 2026-05-06 + 1 day, UTC)."
    )
    # Per ADR-0061 §4 the legacy "Four (4) years from" placeholder must
    # also be gone — concretely-dated, not formula-dated.
    assert "Four (4) years from" not in text, (
        "wat/LICENSE-BSL.md still carries the legacy formula-form "
        "Change-Date wording 'Four (4) years from ...'. ADR-0061 §4 "
        "requires the concrete date string instead."
    )


# ---------------------------------------------------------------------------
# TV-LH-14  NOTICE schlank
# ---------------------------------------------------------------------------

# ADR-0061 Schritt 9 mandates a schlank NOTICE: project name +
# copyright. Governance-/Brand-/Process-Narrative moves to dedicated
# files (GOVERNANCE.md, BRAND.md, ATTRIBUTION.md). We assert at most
# 4 non-blank lines of core text remain.
NOTICE_MAX_CORE_LINES = 4


def test_tv_lh_14_notice_schlank() -> None:
    """TV-LH-14: NOTICE has at most 4 non-blank core lines."""
    path = REPO_ROOT / "NOTICE"
    assert path.exists(), "NOTICE missing at repo root."
    raw = path.read_text(encoding="utf-8")
    # Skip blank lines, count substance lines only.
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(lines) <= NOTICE_MAX_CORE_LINES, (
        f"NOTICE has {len(lines)} non-blank lines (max {NOTICE_MAX_CORE_LINES}). "
        f"ADR-0061 Schritt 9 mandates a schlank NOTICE — move Governance, "
        f"Brand, and Arbeitsprozess-Narrative to GOVERNANCE.md / BRAND.md / "
        f"ATTRIBUTION.md."
    )
    # The remaining lines must at least include the project name and
    # the copyright statement.
    blob = "\n".join(lines)
    assert "Wakir" in blob, "NOTICE is missing the project name 'Wakir'."
    assert "Copyright" in blob or "©" in blob, (
        "NOTICE is missing the copyright statement."
    )


# ---------------------------------------------------------------------------
# TV-LH-15  README references LICENSING.md + Mix-License-Hinweis
# ---------------------------------------------------------------------------

README_EXPECTED_MARKERS: tuple[str, ...] = (
    # Reference to the authoritative license-map.
    "LICENSING.md",
    # Mix-license narrative from ADR-0061 Schritt 5.
    "mixed-license",
)


def test_tv_lh_15_readme_references_licensing_md() -> None:
    """TV-LH-15: README.md references LICENSING.md + mix-license hint."""
    path = REPO_ROOT / "README.md"
    assert path.exists(), "README.md missing at repo root."
    text = path.read_text(encoding="utf-8").lower()
    missing = [m for m in README_EXPECTED_MARKERS if m.lower() not in text]
    assert not missing, (
        f"README.md is missing required license-section markers: {missing}. "
        f"ADR-0061 Schritt 5 mandates a Mix-License-Hinweis-Block plus "
        f"a LICENSING.md reference in the README license section."
    )
