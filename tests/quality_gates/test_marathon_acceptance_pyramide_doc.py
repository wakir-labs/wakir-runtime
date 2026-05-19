# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic doc-audit for ``docs/quality-gates/marathon-acceptance-
pyramide.md`` (Tag-53 consolidated 6-layer doc-refresh).

Auftrag-Anker
-------------

* Tag-53 Amara Auftrag (Mira, 2026-05-19): formal doc-refresh for the
  Marathon-Acceptance-Pyramide after the Tag-52 PR #333 Layer-6
  addition. The Tag-45..52 cascade grew the pyramid from five to six
  layers; Tag-53 consolidates the canonical structural map into a
  single doc at ``docs/quality-gates/marathon-acceptance-pyramide.md``.
* Companion executable artefact: ``tests/phase_3c/test_acceptance_
  pyramide_tag_46_validation.py`` (Tag-47 structural cascade; the
  canonical ``PYRAMIDE`` constant lives there for Layer-1..5; Layer-6
  is anchored in ``tests/phase_3c/test_defence_in_depth_layer_6.py``).
* Auftrag minimum: >= 10 hermetic tests.

Scope
-----

This module is a DOC-SIDE AUDIT, not a re-execution of any layer's
contract. It asserts:

1. The doc exists and is non-trivial.
2. The §1 layer-map references each of the six layer-anchor files.
3. Each anchor-file exists on the working tree.
4. Each anchor-file has the expected minimum test-count (loose bound).
5. The doc enumerates exactly six layers (not five, not seven).
6. The doc preserves Amara as sole layer-owner.
7. The doc references the Tag-47 Pyramide-Validation-Audit as the
   structural-cascade companion.
8. The doc references the Layer-5 Pre-Mortem-Coverage doc.
9. The doc references the Layer-4 Anti-Pattern doc.
10. The doc has the Tag-53 Maintenance-Contract section.
11. The doc captures the cross-layer file-presence cascade invariant.
12. The doc closes with the canonical Amara-sign-off.
13. The doc's §1 table-row order is Layer-1..Layer-6 (no shuffle).

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
# Repo-root anchor (walk up from this file until a sentinel is found).
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
    _repo_root() / "docs" / "quality-gates" / "marathon-acceptance-pyramide.md"
)


# ---------------------------------------------------------------------------
# Canonical layer-anchor table (must match docs/quality-gates/marathon-
# acceptance-pyramide.md §1 row-by-row).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LayerAnchor:
    layer: int  # 1..6
    name: str
    tag_origin: str
    file_path: str  # repo-relative
    min_test_count: int  # loose lower bound


LAYERS: Tuple[LayerAnchor, ...] = (
    LayerAnchor(
        layer=1,
        name="State-Machine",
        tag_origin="Tag-40",
        file_path="tests/phase_3c/test_phase_3_final_regression.py",
        min_test_count=20,
    ),
    LayerAnchor(
        layer=2,
        name="Per-Day",
        tag_origin="Tag-41",
        file_path="tests/phase_3c/test_cutover_day_e2e_drill.py",
        min_test_count=20,
    ),
    LayerAnchor(
        layer=3,
        name="Marathon",
        tag_origin="Tag-43",
        file_path="tests/phase_3c/test_marathon_schluss_acceptance_drill.py",
        min_test_count=20,
    ),
    LayerAnchor(
        layer=4,
        name="Anti-Pattern",
        tag_origin="Tag-44",
        file_path="tests/phase_3c/test_marathon_anti_patterns.py",
        min_test_count=15,
    ),
    LayerAnchor(
        layer=5,
        name="Pre-Mortem Coverage",
        tag_origin="Tag-45",
        file_path=(
            "tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py"
        ),
        min_test_count=20,
    ),
    LayerAnchor(
        layer=6,
        name="Defence-in-Depth Run-Suite",
        tag_origin="Tag-52",
        file_path="tests/phase_3c/test_defence_in_depth_layer_6.py",
        min_test_count=20,
    ),
)


def _read_doc() -> str:
    assert DOC_PATH.exists(), (
        f"doc {DOC_PATH!r} missing — Tag-53 substrate not landed."
    )
    return DOC_PATH.read_text(encoding="utf-8")


def _count_tests(path: Path) -> int:
    """Count top-level + class-level ``def test_`` definitions."""
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8")
    return len(re.findall(r"^\s*def\s+test_\w+\s*\(", text, flags=re.MULTILINE))


# ---------------------------------------------------------------------------
# §1 — Doc presence and basic shape.
# ---------------------------------------------------------------------------


def test_doc_exists_and_is_non_trivial() -> None:
    """The Tag-53 doc MUST exist with non-trivial content (>= 4kB)."""
    assert DOC_PATH.exists(), (
        f"doc {DOC_PATH!r} missing — Tag-53 substrate not landed; "
        f"the consolidated Pyramide-doc is the Tag-53 deliverable."
    )
    size = DOC_PATH.stat().st_size
    assert size >= 4_000, (
        f"doc {DOC_PATH!r} is {size} bytes; expected >= 4000 bytes — "
        f"the canonical 6-layer map cannot fit in a thinner doc."
    )


def test_doc_has_quality_gate_header() -> None:
    """The doc MUST open with the canonical Quality-Gate H1."""
    text = _read_doc()
    head = text.splitlines()[0]
    assert head.startswith("# Quality-Gate"), (
        f"doc H1 {head!r} does not start with '# Quality-Gate' — "
        f"breaks docs/quality-gates/* convention."
    )
    assert "Pyramide" in head or "Pyramid" in head, (
        f"doc H1 {head!r} does not mention 'Pyramide'/'Pyramid' — "
        f"breaks scope-signalling convention."
    )


# ---------------------------------------------------------------------------
# §2 — Six-layer-count invariant.
# ---------------------------------------------------------------------------


def test_doc_enumerates_exactly_six_layers() -> None:
    """The doc MUST enumerate Layer-1..Layer-6 (not 5, not 7)."""
    text = _read_doc()
    # Count distinct Layer-N markers in the §1 table column.
    seen = set()
    for n in range(1, 10):
        # Match the table-row leading-cell "| N |" where N is the layer.
        # Use the more specific contract: each layer cited as "Layer-N"
        # AND the integer alone in column 1 of the §1 table.
        if re.search(rf"^\|\s*{n}\s*\|", text, flags=re.MULTILINE):
            seen.add(n)
    assert seen == {1, 2, 3, 4, 5, 6}, (
        f"doc §1 table layer-column set is {sorted(seen)}; expected "
        f"{{1,2,3,4,5,6}} — six-layer-cascade invariant violated."
    )


# ---------------------------------------------------------------------------
# §3 — Per-layer references in the doc.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("layer", LAYERS, ids=[f"L{p.layer}-{p.name}" for p in LAYERS])
def test_doc_references_layer_anchor_file(layer: LayerAnchor) -> None:
    """For each layer, the doc MUST cite the anchor-file basename."""
    text = _read_doc()
    basename = Path(layer.file_path).name
    assert basename in text, (
        f"doc does not cite Layer-{layer.layer} ({layer.name}) anchor-"
        f"file basename {basename!r}; expected at least one reference."
    )


@pytest.mark.parametrize("layer", LAYERS, ids=[f"L{p.layer}-{p.name}" for p in LAYERS])
def test_doc_references_layer_tag_origin(layer: LayerAnchor) -> None:
    """For each layer, the doc MUST cite the Tag-N origin (e.g. Tag-40)."""
    text = _read_doc()
    assert layer.tag_origin in text, (
        f"doc does not cite Layer-{layer.layer} ({layer.name}) Tag-"
        f"origin {layer.tag_origin!r}; doc-table internal consistency."
    )


@pytest.mark.parametrize("layer", LAYERS, ids=[f"L{p.layer}-{p.name}" for p in LAYERS])
def test_doc_references_layer_name(layer: LayerAnchor) -> None:
    """For each layer, the doc MUST cite the canonical layer-name."""
    text = _read_doc()
    assert layer.name in text, (
        f"doc does not cite Layer-{layer.layer} name {layer.name!r}; "
        f"doc-table internal consistency."
    )


# ---------------------------------------------------------------------------
# §4 — Per-layer file-on-tree existence + min-test-count.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("layer", LAYERS, ids=[f"L{p.layer}-{p.name}" for p in LAYERS])
def test_layer_anchor_file_exists_on_tree(layer: LayerAnchor) -> None:
    """For each layer, the anchor-file MUST exist on the working tree."""
    p = _repo_root() / layer.file_path
    assert p.exists(), (
        f"Layer-{layer.layer} ({layer.name}) anchor-file {layer.file_path!r} "
        f"missing — Pyramide-file-presence-cascade violated (Tag-47 audit)."
    )


@pytest.mark.parametrize("layer", LAYERS, ids=[f"L{p.layer}-{p.name}" for p in LAYERS])
def test_layer_anchor_file_has_min_test_count(layer: LayerAnchor) -> None:
    """For each layer, the anchor-file MUST have >= min_test_count tests."""
    p = _repo_root() / layer.file_path
    n = _count_tests(p)
    assert n >= layer.min_test_count, (
        f"Layer-{layer.layer} ({layer.name}) anchor-file has {n} tests; "
        f"expected >= {layer.min_test_count}."
    )


# ---------------------------------------------------------------------------
# §5 — Companion-doc cross-references.
# ---------------------------------------------------------------------------


def test_doc_references_layer_5_pre_mortem_doc() -> None:
    """The doc MUST reference the Layer-5 Pre-Mortem-Coverage doc."""
    text = _read_doc()
    assert "pre-mortem-failure-mode-coverage.md" in text, (
        "doc does not reference the Layer-5 Pre-Mortem-Coverage "
        "doc — companion cross-reference broken."
    )


def test_doc_references_layer_4_anti_pattern_doc() -> None:
    """The doc MUST reference the Layer-4 Anti-Pattern doc."""
    text = _read_doc()
    assert "phase-3-marathon-anti-patterns.md" in text, (
        "doc does not reference the Layer-4 Anti-Pattern doc — "
        "companion cross-reference broken."
    )


def test_doc_references_tag_47_validation_audit() -> None:
    """The doc MUST reference the Tag-47 Pyramide-Validation-Audit."""
    text = _read_doc()
    assert "test_acceptance_pyramide_tag_46_validation.py" in text, (
        "doc does not reference the Tag-47 Pyramide-Validation-Audit "
        "file — structural-cascade anchor broken."
    )


# ---------------------------------------------------------------------------
# §6 — Ownership and sign-off.
# ---------------------------------------------------------------------------


def test_doc_pins_amara_as_sole_layer_owner() -> None:
    """The doc MUST identify Amara as the layer-owner (Zone-N boundary)."""
    text = _read_doc()
    assert "Amara" in text, (
        "doc does not mention 'Amara' — Owner-field broken; Zone-N "
        "QA-vs-Audit boundary not signalled."
    )
    assert "Henrik" in text, (
        "doc does not mention 'Henrik' — Zone-N cross-check counter-"
        "party missing; Audit-boundary not signalled."
    )


def test_doc_closes_with_amara_signoff() -> None:
    """The doc MUST close with the canonical Amara sign-off."""
    text = _read_doc().rstrip()
    assert text.endswith("— Amara"), (
        f"doc does not close with '— Amara' — Amara-canonical-sign-off "
        f"convention broken; last 40 chars: {text[-40:]!r}"
    )


# ---------------------------------------------------------------------------
# §7 — Structural invariants.
# ---------------------------------------------------------------------------


def test_doc_captures_file_presence_cascade_invariant() -> None:
    """The doc MUST capture the file-presence cascade cross-layer invariant."""
    text = _read_doc()
    assert "cascade" in text.lower(), (
        "doc does not mention 'cascade' — file-presence-cascade "
        "cross-layer invariant not captured."
    )
    assert "File-presence cascade" in text or "file-presence cascade" in text, (
        "doc does not explicitly label the File-presence cascade as a "
        "cross-layer invariant section."
    )


def test_doc_has_maintenance_contract_section() -> None:
    """The doc MUST have a Maintenance-Contract section (§7)."""
    text = _read_doc()
    assert "Maintenance contract" in text or "## 7. Maintenance" in text, (
        "doc does not have the Tag-53 Maintenance-Contract section — "
        "without it, future drift is unpinned."
    )


def test_doc_layer_table_rows_are_in_order_1_to_6() -> None:
    """The §1 table MUST list Layer-1..Layer-6 in monotone order."""
    text = _read_doc()
    # Extract layer-numbers from §1 table rows (lines starting with "| N |").
    rows = re.findall(r"^\|\s*([1-9])\s*\|", text, flags=re.MULTILINE)
    layer_nums = [int(r) for r in rows]
    # Take the first six (the §1 table); subsequent tables (§5 Tag-N
    # anchor) reuse the | n | pattern but for Tag-N anchors, not layers.
    first_six = layer_nums[:6]
    assert first_six == [1, 2, 3, 4, 5, 6], (
        f"doc §1 table layer-column order is {first_six}; expected "
        f"[1,2,3,4,5,6] — monotone-cascade order violated."
    )


def test_doc_references_tag_53_consolidation() -> None:
    """The doc MUST self-identify as the Tag-53 consolidated refresh."""
    text = _read_doc()
    assert "Tag-53" in text, (
        "doc does not self-identify as a Tag-53 artefact — provenance "
        "anchor missing."
    )


def test_doc_references_adr_0066_cadence() -> None:
    """The doc MUST reference ADR-0066 (the four-Wochen-Cadence source)."""
    text = _read_doc()
    assert "ADR-0066" in text, (
        "doc does not reference ADR-0066 — the four-Wochen-Cadence "
        "(KW-24..KW-27) source-of-truth for the Marathon."
    )
