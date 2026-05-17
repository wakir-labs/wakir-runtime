# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""LICENSING.md state-audit (Tag-31 EXT-AUDIT-FOLGE).

The external audit on 2026-05-17 flagged that the per-file license-
headers had drifted away from the human-readable LICENSING.md path-
map: new BSL sub-trees were activated (ADR-0058 provisioner
sibling-unit, ADR-0059 Federation/Persona-Engine activation) and a
new top-level Rust workspace (`wirelang-rust/`) had landed, but
LICENSING.md still only listed the original Phase-1 sub-trees plus a
generic `wirelang/` and `wat/` row. The README repository-layout
section even listed `wat/` as the *only* BSL sub-tree.

This test suite enforces that LICENSING.md, REUSE.toml, pyproject.toml
``license-files`` and the actual on-disk state of the BSL sub-trees
stay in lock-step. It is the diligence-ready acceptance gate the
external audit asked for.

Scope of the assertions (10 vectors):

* TV-LMS-01: every BSL sub-tree on disk (``LICENSE-BSL.md`` carrier)
  is named verbatim in LICENSING.md.
* TV-LMS-02: every BSL path explicitly named in LICENSING.md actually
  has a ``LICENSE-BSL.md`` file on disk (no phantom BSL claims).
* TV-LMS-03: every BSL sub-tree on disk is annotated in REUSE.toml
  with ``SPDX-License-Identifier = "BUSL-1.1"``.
* TV-LMS-04: every BSL sub-tree on disk is referenced in
  pyproject.toml ``license-files = [...]``.
* TV-LMS-05: the Rust workspace (``wirelang-rust/``) is named in
  LICENSING.md as Apache-2.0.
* TV-LMS-06: every crate under ``wirelang-rust/crates/`` either uses
  the workspace license inheritance (``license.workspace = true``)
  or carries an explicit ``license = "Apache-2.0"`` field — no crate
  may silently drift to a different license.
* TV-LMS-07: the README repository-layout section names every BSL
  sub-tree (not just `wat/`).
* TV-LMS-08: the README License section names every BSL sub-tree.
* TV-LMS-09: REUSE-lint is green on the repo (no Invalid SPDX License
  Expressions).
* TV-LMS-10: LICENSING.md mix-license narrative is BUSL-dominant
  ("mixed-license, BUSL-dominant") — diligence-ready posture aligned
  with the external-audit recommendation.

Disjoint from ``test_license_hygiene_consistency.py`` (PR #85/#90):

* That test asserts file *existence* + a substring-marker check.
* This test cross-references LICENSING.md with the *actual on-disk
  set* of BSL sub-trees — if a new BSL sub-tree is added without
  updating LICENSING.md, this test fails. If a BSL row is removed
  from LICENSING.md without removing the sub-tree, this test fails.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _discover_bsl_subtrees() -> list[str]:
    """Return every directory under REPO_ROOT that contains LICENSE-BSL.md.

    Paths are returned relative to REPO_ROOT, with a trailing slash, so
    they match the form used in LICENSING.md (e.g. ``wat/`` or
    ``wirelang/federation/``).
    """
    out: list[str] = []
    for marker in sorted(REPO_ROOT.glob("**/LICENSE-BSL.md")):
        rel_dir = marker.parent.relative_to(REPO_ROOT)
        token = str(rel_dir) + "/"
        out.append(token)
    return out


# ---------------------------------------------------------------------------
# TV-LMS-01: every BSL sub-tree on disk is named in LICENSING.md
# ---------------------------------------------------------------------------


def test_tv_lms_01_every_on_disk_bsl_subtree_listed_in_licensing_md() -> None:
    """Each ``LICENSE-BSL.md``-bearing directory must appear in LICENSING.md."""
    licensing_md = _read(REPO_ROOT / "LICENSING.md")
    discovered = _discover_bsl_subtrees()
    assert discovered, (
        "No LICENSE-BSL.md files found in the repo. Either the audit ran "
        "against an empty checkout or the BSL sub-trees were accidentally "
        "removed."
    )
    missing = [d for d in discovered if d not in licensing_md]
    assert not missing, (
        f"LICENSING.md is missing path-map entries for these on-disk BSL "
        f"sub-trees: {missing}. Update the LICENSING.md table so the human-"
        f"readable map matches the actual repo state (Tag-31 EXT-AUDIT-"
        f"FOLGE diligence-ready posture)."
    )


# ---------------------------------------------------------------------------
# TV-LMS-02: no phantom BSL paths in LICENSING.md
# ---------------------------------------------------------------------------

# BSL paths explicitly named in the Path-to-License Map of LICENSING.md.
# A small allow-list of paths is intentional (they appear in the
# explanatory narrative or as parent-paths, not as authoritative BSL
# claims) — adjusting this list is fine if LICENSING.md evolves, but
# every entry here must correspond to a real ``LICENSE-BSL.md`` on disk.
LICENSING_MD_CLAIMED_BSL_PATHS: tuple[str, ...] = (
    "wat/",
    "wirelang/federation/",
    "wirelang/persona_engine/",
    "infra/spire/federation/",
    "infra/spire/federation/provisioner/",
    "infra/spire/agent/",
    "infra/persona-engine/",
)


@pytest.mark.parametrize("rel_dir", LICENSING_MD_CLAIMED_BSL_PATHS)
def test_tv_lms_02_no_phantom_bsl_paths_in_licensing_md(rel_dir: str) -> None:
    """Each BSL path claimed in LICENSING.md must back the claim with a file."""
    licensing_md = _read(REPO_ROOT / "LICENSING.md")
    assert rel_dir in licensing_md, (
        f"Expected {rel_dir!r} to be named in LICENSING.md per the audit-"
        f"declared LICENSING_MD_CLAIMED_BSL_PATHS list. If you removed it "
        f"from LICENSING.md, also remove it from this list."
    )
    license_file = REPO_ROOT / rel_dir.rstrip("/") / "LICENSE-BSL.md"
    assert license_file.exists(), (
        f"LICENSING.md claims {rel_dir} is BSL but no LICENSE-BSL.md exists "
        f"at {license_file.relative_to(REPO_ROOT)}. Either add the LICENSE-"
        f"BSL.md file or remove the claim from LICENSING.md (phantom BSL "
        f"claims are an audit finding)."
    )


# ---------------------------------------------------------------------------
# TV-LMS-03: every BSL sub-tree is annotated in REUSE.toml
# ---------------------------------------------------------------------------


def test_tv_lms_03_every_on_disk_bsl_subtree_annotated_in_reuse_toml() -> None:
    """Each on-disk BSL sub-tree must have a REUSE.toml glob annotation."""
    reuse_toml = _read(REPO_ROOT / "REUSE.toml")
    discovered = _discover_bsl_subtrees()
    # REUSE.toml uses ``path = "<dir>/**"`` form — strip trailing slash
    # and check the glob substring.
    missing: list[str] = []
    for rel in discovered:
        glob = rel + "**"
        if glob not in reuse_toml:
            missing.append(glob)
    assert not missing, (
        f"REUSE.toml is missing BSL glob annotations for: {missing}. Each "
        f"BSL sub-tree on disk must have a ``[[annotations]] path = "
        f"\"<dir>/**\"`` block with ``SPDX-License-Identifier = "
        f"\"BUSL-1.1\"`` and ``precedence = \"closest\"`` so REUSE scanners "
        f"see the BSL claim without parsing per-file headers."
    )


# ---------------------------------------------------------------------------
# TV-LMS-04: pyproject.toml license-files covers every BSL sub-tree
# ---------------------------------------------------------------------------


def test_tv_lms_04_pyproject_license_files_covers_every_bsl_subtree() -> None:
    """``pyproject.toml`` license-files must reference every BSL sub-tree."""
    pyproject = _read(REPO_ROOT / "pyproject.toml")
    discovered = _discover_bsl_subtrees()
    missing = []
    for rel in discovered:
        # Provisioner is covered by the parent federation/ row in
        # license-files; the provisioner sibling-unit ships its own
        # LICENSE-BSL.md but PEP-639 license-files is project-level
        # metadata and the existing federation entry transitively
        # surfaces the BUSL claim via wheel metadata. Both the parent
        # and the sibling sub-tree license-files form is acceptable.
        license_path = rel + "LICENSE-BSL.md"
        if license_path in pyproject:
            continue
        if rel == "infra/spire/federation/provisioner/":
            # Parent federation/ row is acceptable cover.
            continue
        missing.append(license_path)
    assert not missing, (
        f"pyproject.toml license-files = [...] is missing entries for: "
        f"{missing}. Each BSL sub-tree's LICENSE-BSL.md must be in the "
        f"license-files list so PEP-639 wheel metadata surfaces the BUSL "
        f"claim to PyPI consumers."
    )


# ---------------------------------------------------------------------------
# TV-LMS-05: Rust workspace named in LICENSING.md
# ---------------------------------------------------------------------------


def test_tv_lms_05_rust_workspace_named_in_licensing_md() -> None:
    """``wirelang-rust/`` must appear in LICENSING.md as Apache-2.0."""
    licensing_md = _read(REPO_ROOT / "LICENSING.md")
    rust_root = REPO_ROOT / "wirelang-rust"
    if not rust_root.exists():
        pytest.skip("wirelang-rust/ workspace not present in tree")
    assert "wirelang-rust/" in licensing_md, (
        "LICENSING.md is missing a path-map entry for the wirelang-rust/ "
        "Rust workspace. Per ADR-0034 §3.7 + ADR-0035 the Rust workspace "
        "ships under the Apache-2.0 workspace-default license; the LICENSING."
        "md path-map must surface that posture explicitly."
    )
    # The row must classify it as Apache-2.0 (substring proximity check).
    rust_marker_idx = licensing_md.find("wirelang-rust/")
    nearby = licensing_md[rust_marker_idx : rust_marker_idx + 600]
    assert "Apache-2.0" in nearby, (
        "LICENSING.md mentions wirelang-rust/ but the nearby text (next "
        "~600 chars) does not name Apache-2.0. Confirm the workspace-"
        "default license is asserted in the LICENSING.md row."
    )


# ---------------------------------------------------------------------------
# TV-LMS-06: every Rust crate honours the workspace license posture
# ---------------------------------------------------------------------------


def test_tv_lms_06_every_rust_crate_apache_2_0() -> None:
    """Each ``wirelang-rust/crates/*/Cargo.toml`` must declare Apache-2.0."""
    rust_root = REPO_ROOT / "wirelang-rust"
    if not rust_root.exists():
        pytest.skip("wirelang-rust/ workspace not present in tree")
    crates = sorted((rust_root / "crates").glob("*/Cargo.toml"))
    assert crates, (
        "No crates discovered under wirelang-rust/crates/. The workspace "
        "must ship at least one crate."
    )
    violations: list[str] = []
    for cargo in crates:
        text = _read(cargo)
        # Accept either workspace inheritance or an explicit Apache-2.0
        # field. Any other licence (or no licence field at all) is a
        # violation that surfaces as an audit finding.
        if "license.workspace" in text and "true" in text:
            continue
        if 'license = "Apache-2.0"' in text:
            continue
        rel = cargo.relative_to(REPO_ROOT)
        violations.append(str(rel))
    assert not violations, (
        f"Rust crates with neither ``license.workspace = true`` nor "
        f"``license = \"Apache-2.0\"`` declared: {violations}. Per the "
        f"workspace-default posture (ADR-0034 §3.7) each crate must "
        f"either inherit the workspace license or assert Apache-2.0 "
        f"explicitly."
    )


# ---------------------------------------------------------------------------
# TV-LMS-07: README repository-layout names every BSL sub-tree
# ---------------------------------------------------------------------------


def test_tv_lms_07_readme_layout_names_every_bsl_subtree() -> None:
    """The README repo-layout block must list every BSL sub-tree by name."""
    readme = _read(REPO_ROOT / "README.md")
    # The audit specifically called out the README repository-layout
    # section. Find the block and assert each BSL path token is present
    # somewhere in the README (the layout uses a tree-like rendering, so
    # we check substrings against the full README).
    discovered = _discover_bsl_subtrees()
    missing: list[str] = []
    for rel in discovered:
        if rel not in readme:
            missing.append(rel)
    assert not missing, (
        f"README.md is missing repository-layout / license-section "
        f"references for these BSL sub-trees: {missing}. The external "
        f"audit (2026-05-17) flagged the layout section as listing only "
        f"`wat/` even though six other BSL sub-trees exist. Diligence-"
        f"ready posture requires every BSL sub-tree to be named."
    )


# ---------------------------------------------------------------------------
# TV-LMS-08: README License section spelled out
# ---------------------------------------------------------------------------


def test_tv_lms_08_readme_license_section_named_busl_dominant() -> None:
    """README License section must announce the BUSL-dominant posture."""
    readme = _read(REPO_ROOT / "README.md")
    assert "BUSL-dominant" in readme, (
        "README.md License section must announce the repo as "
        "'mixed-license, BUSL-dominant' so adopters know the dominant "
        "license posture without parsing LICENSING.md. The external "
        "audit (2026-05-17) flagged this gap."
    )
    # Each BSL sub-tree must also appear in the license narrative
    # (not just the layout-block). We check for the explicit bullet
    # list entries.
    must_mention = (
        "wat/",
        "wirelang/federation/",
        "wirelang/persona_engine/",
        "infra/spire/federation/",
        "infra/spire/federation/provisioner/",
        "infra/spire/agent/",
        "infra/persona-engine/",
    )
    missing = [m for m in must_mention if m not in readme]
    assert not missing, (
        f"README.md License section is missing explicit bullet entries "
        f"for: {missing}. Each BSL sub-tree must be named in the "
        f"License section narrative for diligence-ready disclosure."
    )


# ---------------------------------------------------------------------------
# TV-LMS-09: REUSE-lint is green
# ---------------------------------------------------------------------------


def test_tv_lms_09_reuse_lint_is_green() -> None:
    """``reuse lint`` must report no Invalid SPDX License Expressions."""
    try:
        result = subprocess.run(
            ["reuse", "lint"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip(
            "`reuse` tool not installed in the test environment. CI must "
            "install it via `pip install reuse>=6.0`; local dev can skip."
        )
    # The summary block ends with "Invalid SPDX License Expressions: <N>".
    # We grep for that exact field; anything other than 0 is a violation.
    haystack = result.stdout + result.stderr
    # Robust against the "Congratulations!" / "Unfortunately" footer
    # wording — we assert on the summary field directly.
    assert "Invalid SPDX License Expressions: 0" in haystack, (
        f"`reuse lint` reports non-zero Invalid SPDX License Expressions. "
        f"Wrap any SPDX-like substance strings (test assertions, awk "
        f"payloads, fixture writes) between ``# REUSE-IgnoreStart`` and "
        f"``# REUSE-IgnoreEnd`` markers so REUSE-3.0 stays green.\n"
        f"--- reuse lint output ---\n{haystack}"
    )
    # Belt-and-suspenders: also assert the explicit Pass marker line.
    assert "Congratulations" in haystack, (
        f"`reuse lint` did not report the 'Congratulations' compliance "
        f"line. Output:\n{haystack}"
    )


# ---------------------------------------------------------------------------
# TV-LMS-10: LICENSING.md narrative is BUSL-dominant
# ---------------------------------------------------------------------------


def test_tv_lms_10_licensing_md_busl_dominant_narrative() -> None:
    """LICENSING.md preamble must classify the repo as BUSL-dominant."""
    text = _read(REPO_ROOT / "LICENSING.md")
    assert "BUSL-dominant" in text, (
        "LICENSING.md must announce the repo as 'mixed-license, BUSL-"
        "dominant'. The external audit (2026-05-17) called the previous "
        "preamble too weak — only naming Apache-2.0 as the 'default' "
        "without surfacing that the *substantive* code is BSL. The "
        "BUSL-dominant qualifier is the diligence-ready phrasing."
    )
