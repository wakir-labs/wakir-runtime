# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic doc-audit for ``docs/quality-gates/phase-3-marathon-
final-acceptance.md`` (Tag-54 consolidated final-acceptance doc).

Auftrag-Anker
-------------

* Tag-54 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode, AR-persistent):
  consolidated Marathon-Final-Acceptance Definition-of-Done doc rolling
  up Tag-40..Tag-53 substrates into a single artefact.
* Companion docs that this doc references but does NOT replace:
    - ``docs/quality-gates/marathon-acceptance-pyramide.md`` (Tag-53)
    - ``docs/quality-gates/phase-3-marathon-anti-patterns.md`` (Tag-44)
    - ``docs/quality-gates/pre-mortem-failure-mode-coverage.md`` (Tag-45/46/50)
    - ``docs/quality-gates/phase-3-marathon-schluss-acceptance.md`` (Tag-43)
    - ``docs/observability/sli-slo-phase-3-marathon.md`` (Noa Tag-52)
    - ``docs/ci/pre-cutover-final-sanity-gate-runbook.md`` (Tomas Tag-53)
    - ``.github/workflows/phase-3-complete-marker.yml`` (Tomas Tag-40)
    - ``.github/workflows/pre-cutover-final-sanity-gate.yml`` (Tomas Tag-53)
* Auftrag minimum: >= 10 hermetic tests.

Scope
-----

This module is a DOC-SIDE AUDIT, not a re-execution of any surface's
contract. It asserts:

1. The doc exists and is non-trivial (consolidated artefact).
2. The doc enumerates the five Marathon-acceptance surfaces (Surface-1..5).
3. The doc enumerates the Pre-Cutover-Final-Sanity-Gate as Surface-Pre.
4. The doc cites AC-1..AC-5 marker-emit predicate (Surface-1).
5. The doc cites all six Pyramide layers + their Tag-N origins (Surface-2).
6. The doc cites all ten AP-1..AP-10 anti-pattern axes (Surface-3).
7. The doc cites the four Pre-Mortem failure-mode classes + 23-headline (Surface-4).
8. The doc cites all seven SLI-MARATHON-1..7 SLO IDs (Surface-5).
9. The doc cites all seven S1..S7 Pre-Cutover-Sanity substrates (Surface-Pre).
10. The doc cites the four-KW Marathon-Cadence (ADR-0066 KW-24..KW-27).
11. The doc cites the Marathon-Bilanz-Trigger schema (post-marker).
12. The doc captures Zone-N coordination with Henrik (boundary).
13. The doc captures the "What this doc is NOT" anti-scope section.
14. The doc has a Tag-54 self-identification anchor.
15. Each companion-doc cross-reference resolves to a file on tree.
16. The doc closes with the canonical Amara sign-off.
17. The doc references ADR-0066 + ADR-0058 + IIA-1130.
18. The doc identifies Amara as Owner + Henrik as Zone-N cross-check.
19. The doc enumerates the Tag-N anchor map (Tag-40..Tag-54).
20. The doc carries the Maintenance-contract section.

The audit is stdlib-only (re, pathlib, dataclasses); no third-party
deps; no network IO; no subprocess; hermetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import pytest

# ---------------------------------------------------------------------------
# Repo-root anchor.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if (ancestor / ".git").exists() or (ancestor / "pyproject.toml").exists():
            return ancestor
    raise RuntimeError(
        f"could not locate repo-root from {here!r} (no .git/ or "
        f"pyproject.toml ancestor)"
    )


DOC_PATH = (
    _repo_root()
    / "docs"
    / "quality-gates"
    / "phase-3-marathon-final-acceptance.md"
)


# ---------------------------------------------------------------------------
# Canonical surface anchors (must reconcile with doc §1).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SurfaceAnchor:
    surface_id: str
    cardinality_label: str  # human-readable cardinality
    must_cite_in_doc: Tuple[str, ...]  # substrings that MUST appear in doc


SURFACES: Tuple[SurfaceAnchor, ...] = (
    SurfaceAnchor(
        surface_id="Surface-1",
        cardinality_label="5 AC conjuncts",
        must_cite_in_doc=("Surface-1", "AC-1", "AC-2", "AC-3", "AC-4", "AC-5"),
    ),
    SurfaceAnchor(
        surface_id="Surface-2",
        cardinality_label="6-Layer Pyramide",
        must_cite_in_doc=(
            "Surface-2",
            "6-Layer",
            "Tag-40",
            "Tag-41",
            "Tag-43",
            "Tag-44",
            "Tag-45",
            "Tag-52",
        ),
    ),
    SurfaceAnchor(
        surface_id="Surface-3",
        cardinality_label="10 Anti-Pattern axes",
        must_cite_in_doc=(
            "Surface-3",
            "AP-1",
            "AP-2",
            "AP-3",
            "AP-4",
            "AP-5",
            "AP-6",
            "AP-7",
            "AP-8",
            "AP-9",
            "AP-10",
        ),
    ),
    SurfaceAnchor(
        surface_id="Surface-4",
        cardinality_label="23 Pre-Mortem failure-modes",
        must_cite_in_doc=(
            "Surface-4",
            "Class-A",
            "Class-B",
            "Class-C",
            "Class-D",
            "A1..A8",
            "B1..B6",
            "C1..C5",
            "D1..D5",
        ),
    ),
    SurfaceAnchor(
        surface_id="Surface-5",
        cardinality_label="7 SLO catalogue",
        must_cite_in_doc=(
            "Surface-5",
            "SLI-MARATHON-1",
            "SLI-MARATHON-2",
            "SLI-MARATHON-3",
            "SLI-MARATHON-4",
            "SLI-MARATHON-5",
            "SLI-MARATHON-6",
            "SLI-MARATHON-7",
        ),
    ),
    SurfaceAnchor(
        surface_id="Surface-Pre",
        cardinality_label="7 Pre-Cutover-Sanity substrates",
        must_cite_in_doc=(
            "Surface-Pre",
            "S1",
            "S2",
            "S3",
            "S4",
            "S5",
            "S6",
            "S7",
            "READY",
            "CAUTION",
            "BLOCK",
        ),
    ),
)


# Companion-doc anchor paths (file-on-tree existence asserted by §15).
COMPANION_FILES: Tuple[str, ...] = (
    "docs/quality-gates/marathon-acceptance-pyramide.md",
    "docs/quality-gates/phase-3-marathon-anti-patterns.md",
    "docs/quality-gates/pre-mortem-failure-mode-coverage.md",
    "docs/quality-gates/phase-3-marathon-schluss-acceptance.md",
    "docs/ci/pre-cutover-final-sanity-gate-runbook.md",
    "docs/observability/sli-slo-phase-3-marathon.md",
    ".github/workflows/phase-3-complete-marker.yml",
    ".github/workflows/pre-cutover-final-sanity-gate.yml",
)


def _read_doc() -> str:
    assert DOC_PATH.exists(), (
        f"doc {DOC_PATH!r} missing — Tag-54 substrate not landed."
    )
    return DOC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# §1 — Doc presence + non-trivial.
# ---------------------------------------------------------------------------


def test_doc_exists_and_is_non_trivial() -> None:
    """The Tag-54 final-acceptance doc MUST exist with non-trivial content."""
    assert DOC_PATH.exists(), (
        f"doc {DOC_PATH!r} missing — Tag-54 substrate not landed; "
        f"the consolidated final-acceptance doc is the Tag-54 deliverable."
    )
    size = DOC_PATH.stat().st_size
    # Consolidating five surfaces requires a wider doc than the 6-Layer
    # Pyramide-doc (~4kB). Set lower bound to 10kB.
    assert size >= 10_000, (
        f"doc {DOC_PATH!r} is {size} bytes; expected >= 10000 bytes — "
        f"the consolidated five-surface conjunction cannot fit in a "
        f"thinner doc."
    )


def test_doc_has_quality_gate_header() -> None:
    """The doc MUST open with the canonical Quality-Gate H1."""
    text = _read_doc()
    head = text.splitlines()[0]
    assert head.startswith("# Quality-Gate"), (
        f"doc H1 {head!r} does not start with '# Quality-Gate' — "
        f"breaks docs/quality-gates/* convention."
    )
    assert "Final-Acceptance" in head, (
        f"doc H1 {head!r} does not mention 'Final-Acceptance' — "
        f"breaks scope-signalling convention."
    )


# ---------------------------------------------------------------------------
# §2 — Five-surface conjunction (Surface-1..5 + Surface-Pre).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "surface",
    SURFACES,
    ids=[s.surface_id for s in SURFACES],
)
def test_doc_cites_surface(surface: SurfaceAnchor) -> None:
    """For each surface, the doc MUST cite the surface-id + cardinality
    markers exhaustively (no surface partially elided)."""
    text = _read_doc()
    for needle in surface.must_cite_in_doc:
        assert needle in text, (
            f"{surface.surface_id} ({surface.cardinality_label}): doc "
            f"does not cite required marker {needle!r}; consolidated-"
            f"acceptance-surface internal consistency violated."
        )


def test_doc_enumerates_five_marathon_acceptance_surfaces() -> None:
    """The doc MUST enumerate exactly five Marathon-acceptance surfaces
    (Surface-1..5), plus one Surface-Pre. The five-surface conjunction
    is the structural invariant of the consolidated doc."""
    text = _read_doc()
    # Count Surface-N markers (N in 1..5).
    seen_main = set()
    for n in range(1, 6):
        if f"Surface-{n}" in text:
            seen_main.add(n)
    assert seen_main == {1, 2, 3, 4, 5}, (
        f"doc Surface-N set is {sorted(seen_main)}; expected "
        f"{{1,2,3,4,5}} — five-surface-conjunction invariant violated."
    )
    assert "Surface-Pre" in text, (
        "doc does not cite Surface-Pre — Pre-Cutover-Final-Sanity-Gate "
        "is the Monday-morning pre-flight that gates the Wednesday "
        "auto-scheduler; missing-Surface-Pre breaks the marathon-cadence "
        "completeness narrative."
    )


# ---------------------------------------------------------------------------
# §3 — Companion-doc cross-references resolve.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("companion_path", COMPANION_FILES)
def test_companion_doc_referenced_in_doc(companion_path: str) -> None:
    """For each companion-doc, the doc MUST cite the companion's repo-
    relative path or basename, AND the companion-doc MUST exist on tree."""
    text = _read_doc()
    basename = Path(companion_path).name
    assert basename in text, (
        f"companion {companion_path!r} basename {basename!r} not cited "
        f"in doc — section 0 source-of-truth table broken."
    )
    on_tree = _repo_root() / companion_path
    assert on_tree.exists(), (
        f"companion {companion_path!r} cited in doc but missing on tree "
        f"— consolidated-doc cross-reference cascade broken."
    )


# ---------------------------------------------------------------------------
# §4 — Cadence + governance + audit-boundary anchors.
# ---------------------------------------------------------------------------


def test_doc_cites_four_kw_marathon_cadence() -> None:
    """The doc MUST cite the four-KW Marathon-Cadence (KW-24..KW-27,
    per ADR-0066). The cadence is the temporal substrate the five-
    surface conjunction is evaluated over."""
    text = _read_doc()
    for kw in ("KW-24", "KW-25", "KW-26", "KW-27"):
        assert kw in text, (
            f"doc does not cite {kw} — ADR-0066 four-Wochen-Cadence "
            f"temporal substrate broken."
        )
    # Cutover-Mittwoch + Sign-Off-Freitag are the per-KW rhythm.
    assert "Cutover-Mittwoch" in text
    assert "Sign-Off-Freitag" in text


def test_doc_cites_adr_0066_and_0058() -> None:
    """The doc MUST cite ADR-0066 (cadence source) and ADR-0058 (live-VM
    nachtrag, anti-scope anchor)."""
    text = _read_doc()
    assert "ADR-0066" in text, (
        "doc does not cite ADR-0066 — four-Wochen-Cadence source missing."
    )
    assert "ADR-0058" in text, (
        "doc does not cite ADR-0058 — live-VM-acceptance-lane anti-scope "
        "anchor missing."
    )


def test_doc_cites_iia_1130() -> None:
    """The doc MUST cite IIA-1130 — the Internal-Audit-Independence anchor
    that gates the AC-5 AR-Hand-Pre-Auditor-Decision."""
    text = _read_doc()
    assert "IIA-1130" in text, (
        "doc does not cite IIA-1130 — Internal-Audit-Independence "
        "anchor for AC-5 / Welle-7-Pre-Auditor-Decision missing."
    )


def test_doc_cites_marathon_bilanz_trigger() -> None:
    """The doc MUST capture the Marathon-Bilanz-Trigger as the post-marker
    input-event (Noa Tag-43 Bilanz-Generator)."""
    text = _read_doc()
    assert "BilanzTrigger" in text or "Bilanz-Trigger" in text, (
        "doc does not cite the Marathon-Bilanz-Trigger — post-marker "
        "input-event for Noa Tag-43 Bilanz-Generator missing."
    )
    # The schema lists four KW-N-sign-off-ISO fields.
    for kw_field in (
        "kw_24_signoff_iso",
        "kw_25_signoff_iso",
        "kw_26_signoff_iso",
        "kw_27_signoff_iso",
    ):
        assert kw_field in text, (
            f"doc does not cite Bilanz-Trigger field {kw_field!r} — "
            f"schema completeness broken."
        )


# ---------------------------------------------------------------------------
# §5 — Zone-N + anti-scope.
# ---------------------------------------------------------------------------


def test_doc_captures_zone_n_henrik_boundary() -> None:
    """The doc MUST capture the Zone-N coordination with Henrik — the
    QA-Audit-Evidence-Index vs. Audit-Trail boundary."""
    text = _read_doc()
    assert "Zone-N" in text or "Zone N" in text, (
        "doc does not capture Zone-N coordination — Amara/Henrik "
        "boundary not signalled."
    )
    assert "Amara" in text, "Owner-field (Amara) missing."
    assert "Henrik" in text, (
        "Zone-N cross-check counterparty (Henrik) missing — Audit-"
        "boundary not signalled."
    )


def test_doc_has_anti_scope_section() -> None:
    """The doc MUST have a 'What this doc is NOT' anti-scope section
    (anti-coverage-target framing, anti-release-gate framing)."""
    text = _read_doc()
    assert "is NOT" in text, (
        "doc does not have a 'What this doc is NOT' anti-scope section "
        "— consolidated-doc must guard against being mis-read as the "
        "release-gate itself."
    )
    # Anti-scope must explicitly name live-VM-acceptance-lane.
    assert "live-VM" in text or "live-vm" in text, (
        "doc anti-scope does not cite live-VM-acceptance-lane — ADR-0058 "
        "Nachtrag anti-scope anchor missing."
    )


def test_doc_has_maintenance_contract_section() -> None:
    """The doc MUST carry a Maintenance-contract section (drift-prevention)."""
    text = _read_doc()
    assert "Maintenance" in text and "contract" in text.lower(), (
        "doc does not carry a Maintenance-contract section — without it, "
        "future drift of the five-surface conjunction is unpinned."
    )


# ---------------------------------------------------------------------------
# §6 — Tag-N anchor map.
# ---------------------------------------------------------------------------


def test_doc_has_tag_n_anchor_map() -> None:
    """The doc MUST enumerate the Tag-N anchor map (Tag-40..Tag-54)."""
    text = _read_doc()
    expected_tags = (
        "Tag-40",
        "Tag-41",
        "Tag-43",
        "Tag-44",
        "Tag-45",
        "Tag-46",
        "Tag-47",
        "Tag-50",
        "Tag-52",
        "Tag-53",
        "Tag-54",
    )
    for tag in expected_tags:
        assert tag in text, (
            f"doc does not cite {tag} in the Tag-N anchor map — "
            f"provenance lineage broken."
        )


def test_doc_self_identifies_as_tag_54_consolidation() -> None:
    """The doc MUST self-identify as the Tag-54 consolidated artefact."""
    text = _read_doc()
    assert "Tag-54" in text, (
        "doc does not self-identify as Tag-54 — provenance anchor missing."
    )
    # The first 1500 chars should carry the Tag-54 source attribution
    # (metadata table or §0 contract-scope).
    head = text[:1500]
    assert "Tag-54" in head, (
        "doc Tag-54 self-id appears outside the leading 1500 chars — "
        "header-table provenance anchor weak."
    )


# ---------------------------------------------------------------------------
# §7 — Closing sign-off.
# ---------------------------------------------------------------------------


def test_doc_closes_with_amara_signoff() -> None:
    """The doc MUST close with the canonical Amara sign-off."""
    text = _read_doc().rstrip()
    assert text.endswith("— Amara"), (
        f"doc does not close with '— Amara' — Amara-canonical-sign-off "
        f"convention broken; last 40 chars: {text[-40:]!r}"
    )


# ---------------------------------------------------------------------------
# §8 — Five-surface false-positive contract anchors.
# ---------------------------------------------------------------------------


def test_doc_captures_marker_false_positive_contract() -> None:
    """The doc MUST capture the marker false-positive contract — the
    seven negative conditions under which the marker MUST NOT fire
    (Tag-43 Schluss-DoD §4)."""
    text = _read_doc()
    assert "MUST NOT fire" in text, (
        "doc does not capture the marker false-positive contract — the "
        "negative-axis of Surface-1 (Tag-43 §4) missing."
    )
    # The seven canonical NEG-conditions surface key phrases:
    for needle in (
        "Welle-3",
        "Welle-7-Pre-Auditor-Decision",
        "Cross-modul drift",
        "Henrik aggregate_verdict",
        "AR-Hand-quote",
    ):
        assert needle in text, (
            f"doc false-positive contract does not capture {needle!r} — "
            f"NEG-axis completeness broken."
        )


def test_doc_captures_cutover_blocking_slo_conjunction() -> None:
    """The doc MUST capture the four cutover-blocking SLOs and the
    informational separation (Surface-5 §2.1..2.7 split)."""
    text = _read_doc()
    # The four cutover-blocking SLIs (1, 2, 5, 6, 7) all carry a 'YES'
    # cutover-blocking label.
    yes_count = text.count("**YES**")
    assert yes_count >= 4, (
        f"doc cutover-blocking SLO count is {yes_count}; expected >= 4 "
        f"(SLI-MARATHON-{{1,2,5,6,7}} are cutover-blocking per Noa Tag-52)."
    )


def test_doc_captures_pre_mortem_coverage_classification() -> None:
    """The doc MUST capture the four-state Pre-Mortem coverage
    classification (COVERED / PARTIAL / GAP-ACCEPTED / GAP-OPEN)."""
    text = _read_doc()
    for state in ("COVERED", "PARTIAL", "GAP-ACCEPTED", "GAP-OPEN"):
        assert state in text, (
            f"doc does not cite Pre-Mortem coverage state {state!r} — "
            f"Surface-4 classification taxonomy incomplete."
        )


# ---------------------------------------------------------------------------
# §9 — Layer-anchor file-on-tree (each Pyramide-Layer file exists).
# ---------------------------------------------------------------------------


LAYER_FILES: Tuple[str, ...] = (
    "tests/phase_3c/test_phase_3_final_regression.py",
    "tests/phase_3c/test_cutover_day_e2e_drill.py",
    "tests/phase_3c/test_marathon_schluss_acceptance_drill.py",
    "tests/phase_3c/test_marathon_anti_patterns.py",
    "tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py",
    "tests/phase_3c/test_defence_in_depth_layer_6.py",
)


@pytest.mark.parametrize("layer_file", LAYER_FILES)
def test_pyramide_layer_anchor_file_exists_on_tree(layer_file: str) -> None:
    """Each Pyramide-Layer anchor-file cited in this doc MUST exist on
    the working tree. Without the anchor-file, the Tag-54 consolidated
    citation is a dangling reference."""
    p = _repo_root() / layer_file
    assert p.exists(), (
        f"Layer-anchor-file {layer_file!r} missing on tree — Tag-54 "
        f"consolidated-doc cites a Pyramide-layer that does not exist "
        f"(file-presence-cascade violation)."
    )


@pytest.mark.parametrize("layer_file", LAYER_FILES)
def test_doc_cites_pyramide_layer_anchor_file(layer_file: str) -> None:
    """Each Pyramide-Layer anchor-file MUST be cited in the doc by its
    repo-relative path (or, at minimum, by its basename)."""
    text = _read_doc()
    basename = Path(layer_file).name
    assert basename in text, (
        f"doc does not cite Pyramide-Layer anchor-file basename "
        f"{basename!r} — Surface-2 layer-citation incomplete."
    )
