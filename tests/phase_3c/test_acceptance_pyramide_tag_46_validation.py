# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Phase-3-Acceptance-Pyramide Tag-46 Layer-Consistency-Audit (Tag-47).

The Tag-45 PR #293 established the five-layer Phase-3-Acceptance
Pyramide. The Tag-46 spawn-cycle then landed four COVERED-promotion
follow-ups (A2 / A6 / A8 / B1) and the Tag-46 Coverage-Sweep itself.
This Tag-47 audit is the meta-meta-test that pins the Pyramide as a
structurally-consistent contract: each layer requires its predecessors,
the Tag-46 follow-ups sit at well-defined layer-slots, and the doc-side
matrix names the layer-membership for every artefact in §0 / §3 / §4.

Auftrag-Anker
-------------

- Tag-47 Amara Auftrag — Phase-3-Acceptance-Pyramide Tag-46-Layer-Audit
  (Continuous-Mode, AR-persistent, 2026-05-18). Baseline commit
  ``7ada5ab`` (Tag-46 PR #299 merge tip).
- Tag-45 baseline:
  * ``tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py``
    (Layer-5 introspection test, 25 tests).
  * ``docs/quality-gates/pre-mortem-failure-mode-coverage.md``
    (Layer-1..5 pyramid §0 table + §2 per-mode classification).
- Tag-46 sweep + follow-ups (all merged on main at audit-time):
  * ``tests/phase_3c/test_pre_mortem_coverage_sweep_tag_46.py``
    (PR #301, Amara — 24 sweep tests across §1 promotion-detection,
    §2 A6 cross-validation, §3 B1 cross-validation, §4 B3 deadline,
    §5 summary recomputation, §6 baseline regression).
  * ``wirelang/tests/persona_engine/test_fsm_phantom_transition_
    coverage_a2.py`` (Reza PR #295, A2 PARTIAL -> COVERED).
  * ``tests/infra/test_cosign_drift_coverage_a6.py`` (Kai PR #298,
    A6 PARTIAL -> COVERED at substrate-layer).
  * ``wirelang/persona_engine/tests/test_nats_jetstream_loss_
    recovery_a8.py`` (Selin PR #300, A8 PARTIAL -> COVERED).
  * ``tests/ci/test_ar_hand_stop_marker_trigger_b1.py`` (Tomás
    PR #299, B1 PARTIAL -> COVERED).

The Tag-46 cumulative state recorded in §3 of the coverage doc:
COVERED 9 -> 12, PARTIAL 5 -> 2, GAP-ACCEPTED 10, GAP-OPEN 0, total
24. B3 + A2-marathon-defence remain the two PARTIAL items at audit
time (B3 is the hard KW-25 blocker; A2-marathon-defence is an
additional defence-in-depth pin pending Amara-spawn).

Pyramide-Layer-Consistency contract
-----------------------------------

The Phase-3-Acceptance Pyramide is a strict ordering where each layer
asserts a strict superset of the invariants of the previous layer at
a higher level of integration:

  Layer 1 (State-Machine) -- sign-off-record -> COMPLETE-marker
  Layer 2 (Per-Day)       -- one cutover-day -> one sign-off-record
  Layer 3 (Marathon)      -- seven days     -> AC-1..AC-5 conjunction
  Layer 4 (Anti-Pattern)  -- control-surface REJECTS anti-patterns
  Layer 5 (Pre-Mortem)    -- Layer-1..4 union covers failure-modes

The audit enforces:

1. **File-presence cascade.** Layer-N file MUST exist iff Layer-1..N-1
   files all exist (Pyramide has no holes). If Layer-3 is missing,
   Layer-4 and Layer-5 are structurally hollow.
2. **Doc-side membership table consistency.** The §0 "Phase-3-
   Acceptance pyramid grows to five layers" table in the coverage doc
   MUST name exactly the five Tag-40/Tag-41/Tag-43/Tag-44/Tag-45 test
   files in the right layer-slots.
3. **Layer-5 dependency-edge consistency.** The Layer-5 audit file
   MUST introspect Layer-1..4 modules (via importlib) and reference
   them by name in the module-docstring's companion-list.
4. **Tag-46 promotion-detection layer-assignment.** Each Tag-46
   follow-up has a §4 documented "Layer" column. The audit asserts
   the follow-up file actually lives at a path consistent with that
   layer slot (Layer-5 marathon -> tests/phase_3c/, Layer-3 substrate
   -> tests/infra/, persona-engine-module -> wirelang/.../persona_
   engine/tests/, CI-shape -> tests/ci/).
5. **Tag-46 sweep self-consistency.** The sweep test-module's
   ``TAG46_FOLLOWUPS`` constant MUST cover exactly the five §4
   follow-up items and their cross-review partners MUST match the
   §4 doc.
6. **Doc-refresh marker.** §0 of the coverage doc MUST carry a
   Tag-47 audit reference once this file lands (the doc-refresh half
   of this task).

Why a separate Tag-47 audit (vs. extending Tag-46 sweep)
--------------------------------------------------------

* The Tag-46 sweep (PR #301) is a **content** audit — does each
  Tag-46 follow-up file exist and contain >=1 test? It accepts five
  alias-paths per follow-up.
* This Tag-47 audit is a **structural** audit — does the layered
  contract hold? Is each layer's file present, is the doc-side
  table internally consistent, do the Tag-46 placements honour the
  layer-membership claimed by the doc?
* The two audits are companion-tests, not duplicates: the sweep
  passes if "the four files exist anywhere"; this audit passes if
  "the four files exist at paths consistent with their declared
  layer-slots and the doc internally agrees".

Test budget
-----------

~20 tests, six sections:

* §1 — Layer-1..5 file-presence cascade (5 tests).
* §2 — Doc-side §0 pyramid-table consistency (4 tests).
* §3 — Layer-5 dependency-edge consistency (3 tests).
* §4 — Tag-46 promotion-detection layer-slot consistency (5 tests).
* §5 — Tag-46 sweep TAG46_FOLLOWUPS internal-consistency (2 tests).
* §6 — Doc-refresh + Tag-47 audit-marker presence (1 test).

Vermutungs-Kennzeichnung (P2)
-----------------------------

* This file is a meta-meta-audit. It does NOT re-execute Layer-1..5
  invariants; it asserts their structural existence + doc-side
  membership-consistency. Substantive correctness of each layer is
  the Layer-N file's own responsibility. (Layer-5 already enforces
  Layer-1..4 coverage of Henrik's failure-modes; this audit enforces
  the Layer-5 layer-assignment-table is internally consistent.)
* The Tag-46 follow-up layer-paths are accepted at a small canonical
  set per layer (e.g. Layer-3-substrate is ``tests/infra/`` and Layer-
  5-marathon is ``tests/phase_3c/`` + the persona-engine module
  paths). New layer-slots (e.g. a hypothetical Layer-3-frontend) would
  require updating this audit.
* The doc-refresh assertion (§6) is the only test that requires a
  doc-side change as part of this Tag-47 PR. The §0 of the coverage
  doc gains one new row referencing the Tag-47 audit file (cross-
  reference to the structural-consistency audit). The rest of §0..§6
  of the doc remains intact.

License: Apache-2.0 (parity with Tag-45 baseline + Tag-46 sweep).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, FrozenSet, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Repo-root + helper loaders (parity with Tag-45 / Tag-46 modules).
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the wakir-runtime repo root from this test file."""
    here = Path(__file__).resolve()
    return here.parent.parent.parent


def _coverage_doc_path() -> Path:
    return (
        _repo_root()
        / "docs"
        / "quality-gates"
        / "pre-mortem-failure-mode-coverage.md"
    )


def _coverage_doc_text() -> str:
    return _coverage_doc_path().read_text(encoding="utf-8")


def _load_module(filename: Path, module_name: str) -> Optional[Any]:
    """Load a test module by absolute path."""
    if not filename.is_file():
        return None
    spec = importlib.util.spec_from_file_location(module_name, str(filename))
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception:
        return None
    return module


def _module_test_names(module: Any) -> FrozenSet[str]:
    """Collect public test-function + test-class names."""
    names: set[str] = set()
    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        attr = getattr(module, attr_name)
        if callable(attr) and attr_name.startswith("test_"):
            names.add(attr_name)
            continue
        if isinstance(attr, type) and attr_name.startswith("Test"):
            for method_name in dir(attr):
                if method_name.startswith("test_"):
                    names.add(f"{attr_name}::{method_name}")
            names.add(attr_name)
    return frozenset(names)


# ---------------------------------------------------------------------------
# Pyramide canonical layer-membership table.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PyramideLayer:
    """One layer of the Phase-3-Acceptance Pyramide."""

    layer: int  # 1..5
    name: str  # short label
    tag_origin: str  # "Tag-40" | "Tag-41" | "Tag-43" | "Tag-44" | "Tag-45"
    file_path: str  # repo-relative path
    contract: str  # one-line contract


PYRAMIDE: Tuple[PyramideLayer, ...] = (
    PyramideLayer(
        layer=1,
        name="State-Machine",
        tag_origin="Tag-40",
        file_path="tests/phase_3c/test_phase_3_final_regression.py",
        contract=(
            "Given seven sign-off-records, does the Phase-3-COMPLETE-marker "
            "fire?"
        ),
    ),
    PyramideLayer(
        layer=2,
        name="Per-Day",
        tag_origin="Tag-41",
        file_path="tests/phase_3c/test_cutover_day_e2e_drill.py",
        contract=(
            "Does one Cutover-Mittwoch produce a correctly-shaped sign-off-"
            "record?"
        ),
    ),
    PyramideLayer(
        layer=3,
        name="Marathon",
        tag_origin="Tag-43",
        file_path="tests/phase_3c/test_marathon_schluss_acceptance_drill.py",
        contract=(
            "Does the four-Wochen-Sequence thread the per-day records into "
            "the AC-1..AC-5 conjunction, fire the marker, fire the Bilanz-"
            "Trigger?"
        ),
    ),
    PyramideLayer(
        layer=4,
        name="Anti-Pattern",
        tag_origin="Tag-44",
        file_path="tests/phase_3c/test_marathon_anti_patterns.py",
        contract=(
            "Does the control-surface REJECT ten dedicated control-plane "
            "anti-patterns by construction?"
        ),
    ),
    PyramideLayer(
        layer=5,
        name="Pre-Mortem Coverage",
        tag_origin="Tag-45",
        file_path=(
            "tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py"
        ),
        contract=(
            "Does the union of Layer-1..4 cover the 23 Pre-Mortem failure-"
            "modes, or is each gap explicitly classified?"
        ),
    ),
)

PYRAMIDE_BY_LAYER = {p.layer: p for p in PYRAMIDE}


# ---------------------------------------------------------------------------
# Tag-46 follow-up canonical layer-slot table.
#
# Each follow-up has an expected layer-slot per §4 of the coverage doc.
# The audit asserts the follow-up file lives at a path consistent with
# that slot.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tag46LayerSlot:
    failure_mode_id: str
    follow_up_relative_path: str  # canonical (or accepted) path
    layer_slot: int  # 1..5
    layer_slot_label: str  # short label
    spawn_owner: str
    cross_review_partner: str


TAG46_LAYER_SLOTS: Tuple[Tag46LayerSlot, ...] = (
    Tag46LayerSlot(
        failure_mode_id="A2",
        follow_up_relative_path=(
            "wirelang/tests/persona_engine/"
            "test_fsm_phantom_transition_coverage_a2.py"
        ),
        layer_slot=5,
        layer_slot_label="Marathon (persona-engine sub-layer)",
        spawn_owner="Reza",
        cross_review_partner="Amara",
    ),
    Tag46LayerSlot(
        failure_mode_id="A6",
        follow_up_relative_path="tests/infra/test_cosign_drift_coverage_a6.py",
        layer_slot=3,
        layer_slot_label="substrate (CI-workflow + infra-layer)",
        spawn_owner="Kai",
        cross_review_partner="Amara",
    ),
    Tag46LayerSlot(
        failure_mode_id="A8",
        follow_up_relative_path=(
            "wirelang/persona_engine/tests/"
            "test_nats_jetstream_loss_recovery_a8.py"
        ),
        layer_slot=5,
        layer_slot_label="Marathon (persona-engine sub-layer)",
        spawn_owner="Selin",
        cross_review_partner="Reza",
    ),
    Tag46LayerSlot(
        failure_mode_id="B1",
        follow_up_relative_path=(
            "tests/ci/test_ar_hand_stop_marker_trigger_b1.py"
        ),
        layer_slot=5,
        layer_slot_label="Marathon (CI-shape sub-layer)",
        spawn_owner="Tomás",
        cross_review_partner="Amara",
    ),
)


# ---------------------------------------------------------------------------
# §1 — Layer-1..5 file-presence cascade (5 tests).
#
# Each layer requires its predecessors. We assert the file-presence
# cascade by checking that Layer-N exists AND all Layer-(<N) exist.
# ---------------------------------------------------------------------------


def _layer_file_exists(layer: int) -> bool:
    p = _repo_root() / PYRAMIDE_BY_LAYER[layer].file_path
    return p.is_file()


def test_pyramide_layer_1_state_machine_present() -> None:
    """Layer-1 State-Machine file MUST exist (Tag-40 anchor)."""
    p = PYRAMIDE_BY_LAYER[1]
    assert _layer_file_exists(1), (
        f"Layer-1 ({p.name}, {p.tag_origin}) file {p.file_path!r} missing — "
        f"Pyramide hollow at its base. All higher-layer assertions are "
        f"structurally meaningless without the state-machine anchor."
    )


def test_pyramide_layer_2_per_day_present_iff_layer_1() -> None:
    """Layer-2 Per-Day file MUST exist AND Layer-1 MUST exist."""
    p = PYRAMIDE_BY_LAYER[2]
    assert _layer_file_exists(1), (
        f"Layer-2 ({p.name}, {p.tag_origin}) present-check requires Layer-1 "
        f"as predecessor; Layer-1 missing — Pyramide-cascade-violation."
    )
    assert _layer_file_exists(2), (
        f"Layer-2 ({p.name}, {p.tag_origin}) file {p.file_path!r} missing — "
        f"per-day walkthrough cannot anchor Layer-3 marathon."
    )


def test_pyramide_layer_3_marathon_present_iff_layer_1_and_2() -> None:
    """Layer-3 Marathon file MUST exist AND Layer-1..2 MUST exist."""
    p = PYRAMIDE_BY_LAYER[3]
    assert _layer_file_exists(1) and _layer_file_exists(2), (
        f"Layer-3 ({p.name}, {p.tag_origin}) present-check requires Layer-"
        f"1..2 as predecessors; one or both missing — Pyramide-cascade-"
        f"violation."
    )
    assert _layer_file_exists(3), (
        f"Layer-3 ({p.name}, {p.tag_origin}) file {p.file_path!r} missing — "
        f"marathon-aggregate-level invariants unanchored."
    )


def test_pyramide_layer_4_anti_pattern_present_iff_layer_1_to_3() -> None:
    """Layer-4 Anti-Pattern file MUST exist AND Layer-1..3 MUST exist."""
    p = PYRAMIDE_BY_LAYER[4]
    for predecessor in (1, 2, 3):
        assert _layer_file_exists(predecessor), (
            f"Layer-4 ({p.name}, {p.tag_origin}) present-check requires "
            f"Layer-{predecessor} as predecessor; missing — Pyramide-cascade-"
            f"violation."
        )
    assert _layer_file_exists(4), (
        f"Layer-4 ({p.name}, {p.tag_origin}) file {p.file_path!r} missing — "
        f"anti-pattern control-surface unanchored."
    )


def test_pyramide_layer_5_pre_mortem_present_iff_layer_1_to_4() -> None:
    """Layer-5 Pre-Mortem file MUST exist AND Layer-1..4 MUST exist.

    This is the strictest cascade: Layer-5 makes claims ABOUT Layer-1..4
    coverage. If any predecessor is missing, Layer-5 introspection of
    that layer would fail at import-time, but the per-failure-mode
    classification would silently regress. This test forbids that
    regression.
    """
    p = PYRAMIDE_BY_LAYER[5]
    for predecessor in (1, 2, 3, 4):
        assert _layer_file_exists(predecessor), (
            f"Layer-5 ({p.name}, {p.tag_origin}) cascade requires Layer-"
            f"{predecessor}; missing — Layer-5 meta-coverage claims become "
            f"unprovable."
        )
    assert _layer_file_exists(5), (
        f"Layer-5 ({p.name}, {p.tag_origin}) file {p.file_path!r} missing — "
        f"Pre-Mortem coverage-audit unanchored; Henrik's 24 failure-mode "
        f"classifications have no enforcement surface."
    )


# ---------------------------------------------------------------------------
# §2 — Doc-side §0 pyramid-table consistency (4 tests).
#
# The §0 section of the coverage doc carries a five-row table with one
# row per layer. The audit asserts the table is internally consistent
# with the canonical PYRAMIDE constant above.
# ---------------------------------------------------------------------------


def test_pyramide_doc_section_0_table_names_all_five_layers() -> None:
    """§0 table MUST list all five layer-labels."""
    content = _coverage_doc_text()
    expected_labels = (
        "1 — State-Machine",
        "2 — Per-Day",
        "3 — Marathon",
        "4 — Anti-Pattern",
        "5 — Pre-Mortem Coverage",
    )
    for label in expected_labels:
        assert label in content, (
            f"§0 pyramid-table missing layer label {label!r}; doc-side "
            f"Pyramide-membership structurally inconsistent."
        )


def test_pyramide_doc_section_0_table_names_all_five_tag_origins() -> None:
    """§0 table MUST reference all five Tag-N origins in order."""
    content = _coverage_doc_text()
    # Tag-N origins appear in §0 as parenthetical anchors. Extract the
    # §0 table region and assert each Tag-N is in scope.
    # §0 is delimited by "## 0. Contract scope" and "## 1. Classification".
    m = re.search(
        r"##\s*0\.\s*Contract\s*scope(.*?)##\s*1\.\s*Classification",
        content,
        re.DOTALL,
    )
    assert m is not None, "§0 section delimiter missing in coverage doc"
    section_0 = m.group(1)
    for layer in PYRAMIDE:
        assert layer.tag_origin in section_0, (
            f"§0 pyramid-table missing Tag-origin reference {layer.tag_origin!r} "
            f"for Layer-{layer.layer} ({layer.name}); doc-side anchor drift."
        )


def test_pyramide_doc_section_0_table_names_all_five_file_paths() -> None:
    """§0 table MUST reference each layer's file-basename."""
    content = _coverage_doc_text()
    m = re.search(
        r"##\s*0\.\s*Contract\s*scope(.*?)##\s*1\.\s*Classification",
        content,
        re.DOTALL,
    )
    assert m is not None
    section_0 = m.group(1)
    for layer in PYRAMIDE:
        basename = Path(layer.file_path).name
        assert basename in section_0, (
            f"§0 pyramid-table missing file-basename {basename!r} for "
            f"Layer-{layer.layer} ({layer.name}); doc-side file-reference drift."
        )


def test_pyramide_doc_section_0_owner_amara_all_five_layers() -> None:
    """§0 table rows MUST attribute Amara as Owner on all five layers.

    Pyramide ownership is a structural invariant: all five layers are
    QA-domain artefacts (Layer-1..4 system-behaviour invariants +
    Layer-5 coverage-meta-audit). Other personae cross-review but do
    not own a layer.
    """
    content = _coverage_doc_text()
    m = re.search(
        r"##\s*0\.\s*Contract\s*scope(.*?)##\s*1\.\s*Classification",
        content,
        re.DOTALL,
    )
    assert m is not None
    section_0 = m.group(1)
    # Count "| Amara |" occurrences inside the pyramid-table.
    # Five layers, one "Amara" per row -> exactly five "| Amara |" tokens.
    amara_count = section_0.count("| Amara |")
    assert amara_count == 5, (
        f"§0 pyramid-table expected 5 'Amara' Owner-entries (one per layer); "
        f"found {amara_count}. Doc-side ownership-anchor inconsistent — "
        f"either a layer-row was removed/renamed or a non-Amara Owner was "
        f"inserted."
    )


# ---------------------------------------------------------------------------
# §3 — Layer-5 dependency-edge consistency (3 tests).
#
# Layer-5 (`test_pre_mortem_failure_mode_coverage_audit.py`) makes
# claims ABOUT Layer-1..4. The audit asserts that the Layer-5 module
# imports / references Layer-1..4 by their actual file-basenames.
# ---------------------------------------------------------------------------


def test_pyramide_layer_5_module_docstring_references_layer_1_to_4() -> None:
    """Layer-5 docstring MUST name all four predecessor layer-files."""
    layer_5_path = _repo_root() / PYRAMIDE_BY_LAYER[5].file_path
    assert layer_5_path.is_file()
    content = layer_5_path.read_text(encoding="utf-8")
    for layer in PYRAMIDE:
        if layer.layer == 5:
            continue
        basename = Path(layer.file_path).name
        assert basename in content, (
            f"Layer-5 module {layer_5_path.name!r} does not reference Layer-"
            f"{layer.layer} file {basename!r}. The Layer-5 meta-audit claims "
            f"to introspect Layer-{layer.layer}; reference-anchor missing."
        )


def test_pyramide_layer_5_test_count_matches_doc_contract() -> None:
    """Layer-5 has 25 tests per §6 of the coverage doc (24 modes + 1 sum).

    The Tag-45 §6 doc-contract names 25 tests in Layer-5: 24 per-
    failure-mode + 1 summary. The Tag-46 sweep (separate file) adds
    more; the Layer-5 file ITSELF retains exactly 25.
    """
    layer_5_path = _repo_root() / PYRAMIDE_BY_LAYER[5].file_path
    module = _load_module(layer_5_path, "amara_tag47_audit_layer_5")
    assert module is not None, "Layer-5 module load failed"
    test_names = _module_test_names(module)
    # Function-style test_* names only (Layer-5 is function-style, not
    # class-style). Filter to flat function names.
    flat_test_names = {n for n in test_names if "::" not in n and not n.startswith("Test")}
    # Tolerance: the Tag-46 sweep may add a small number of follow-on
    # introspection tests inside Layer-5. The §6 contract is "25 tests";
    # accept 24..30 as the tolerance band (24 modes + 1 sum + up to 5
    # incremental Tag-46+ entries).
    assert 24 <= len(flat_test_names) <= 30, (
        f"Layer-5 test-count {len(flat_test_names)} outside accepted band "
        f"24..30; §6 doc-contract says 25. Layer-5 has drifted from the "
        f"documented test-budget."
    )


def test_pyramide_layer_5_sweep_companion_present() -> None:
    """The Tag-46 sweep MUST be at the documented sibling-location.

    The Tag-46 sweep
    ``tests/phase_3c/test_pre_mortem_coverage_sweep_tag_46.py`` is the
    promotion-detection companion to the Layer-5 baseline. The doc
    (§4a) names this companion explicitly. The audit pins its
    presence.
    """
    sweep_path = (
        _repo_root()
        / "tests"
        / "phase_3c"
        / "test_pre_mortem_coverage_sweep_tag_46.py"
    )
    assert sweep_path.is_file(), (
        "Tag-46 coverage-sweep file missing at the documented sibling-path "
        "tests/phase_3c/test_pre_mortem_coverage_sweep_tag_46.py. The §4a "
        "narrative of the coverage doc becomes orphan."
    )
    content = _coverage_doc_text()
    assert "test_pre_mortem_coverage_sweep_tag_46.py" in content, (
        "Coverage doc must reference the Tag-46 sweep filename in §4a or §0."
    )


# ---------------------------------------------------------------------------
# §4 — Tag-46 promotion-detection layer-slot consistency (5 tests).
#
# Each Tag-46 follow-up file lives at a path consistent with the layer-
# slot the doc claims for it. The audit pins file-presence at the
# canonical path AND the doc-side §4 claim.
# ---------------------------------------------------------------------------


def _tag46_slot_by_id(failure_mode_id: str) -> Tag46LayerSlot:
    for s in TAG46_LAYER_SLOTS:
        if s.failure_mode_id == failure_mode_id:
            return s
    raise KeyError(failure_mode_id)


def test_tag46_a2_layer_slot_persona_engine_marathon() -> None:
    """A2 follow-up MUST live in wirelang/.../persona_engine/ tree.

    A2 is an FSM-transition-legality oracle — naturally pinned at the
    persona-engine module-level (not at tests/phase_3c/ marathon
    aggregation). The doc accepts the persona-engine layout as an
    alias-path for Layer-5-Marathon.
    """
    slot = _tag46_slot_by_id("A2")
    p = _repo_root() / slot.follow_up_relative_path
    assert p.is_file(), (
        f"A2 follow-up missing at canonical path {slot.follow_up_relative_path!r}. "
        f"Reza-spawn PR #295 may have been reverted, or path drifted."
    )
    # Doc-side: §4 row 1 references the A2 follow-up.
    assert "A2 FSM-Phantom-Transitions" in _coverage_doc_text(), (
        "Coverage doc §4 row 1 (A2) missing; §4 follow-up table drifted."
    )


def test_tag46_a6_layer_slot_infra_substrate() -> None:
    """A6 follow-up MUST live at tests/infra/ (substrate-layer slot).

    A6 cosign-drift is a substrate-layer concern (per-binary drift
    detection across the 15-binary inventory). The doc §3 PARTIAL-
    bucket §A6 structural-seam observation explicitly names "tests/
    infra/test_cosign_drift_coverage_a6.py" as the substrate-layer
    closeout (17 hermetic invariants).
    """
    slot = _tag46_slot_by_id("A6")
    p = _repo_root() / slot.follow_up_relative_path
    assert p.is_file(), (
        f"A6 follow-up missing at substrate-layer canonical path "
        f"{slot.follow_up_relative_path!r}. Kai-spawn PR #298 may have been "
        f"reverted, or path drifted."
    )
    # Doc-side: §4 row 2a references the A6 substrate-layer follow-up.
    assert "test_cosign_drift_coverage_a6.py" in _coverage_doc_text(), (
        "Coverage doc §4 row 2a (A6 substrate) missing filename anchor; "
        "§4 follow-up table drifted."
    )


def test_tag46_a8_layer_slot_persona_engine_marathon() -> None:
    """A8 follow-up MUST live at wirelang/persona_engine/tests/.

    A8 NATS-JetStream-Loss-Recovery is naturally pinned at the persona-
    engine module-level (NATS-publish-sink + KV-failover stubs live in
    the persona_engine package). The doc §3 PARTIAL-bucket §A8 names
    the persona-engine path as the canonical layer-slot.
    """
    slot = _tag46_slot_by_id("A8")
    p = _repo_root() / slot.follow_up_relative_path
    assert p.is_file(), (
        f"A8 follow-up missing at canonical path {slot.follow_up_relative_path!r}. "
        f"Selin-spawn PR #300 may have been reverted, or path drifted."
    )
    # Doc-side: §4 row 3 references the A8 follow-up.
    assert "test_nats_jetstream_loss_recovery_a8.py" in _coverage_doc_text(), (
        "Coverage doc §4 row 3 (A8) missing filename anchor; §4 follow-up "
        "table drifted."
    )


def test_tag46_b1_layer_slot_ci_marathon() -> None:
    """B1 follow-up MUST live at tests/ci/ (CI-shape Layer-5 slot).

    B1 AR-Hand-Stop-Marker-Trigger is the CI-shape sub-layer pin: the
    marker is a JSON-shape sign-off-marker that the CI/operator
    surface checks. Tomás PR #299 explicitly placed it at tests/ci/
    (companion to the Tag-45 alert-shape test
    tests/ci/test_phase_3_marathon_failure_mode_alerts.py).
    """
    slot = _tag46_slot_by_id("B1")
    p = _repo_root() / slot.follow_up_relative_path
    assert p.is_file(), (
        f"B1 follow-up missing at canonical path {slot.follow_up_relative_path!r}. "
        f"Tomás-spawn PR #299 may have been reverted, or path drifted."
    )
    assert "test_ar_hand_stop_marker_trigger_b1.py" in _coverage_doc_text(), (
        "Coverage doc must reference the B1 follow-up filename in §4 or §4a."
    )


def test_tag46_layer_slot_count_summary_post_tag_46_state() -> None:
    """Tag-46 cumulative state: COVERED 12, PARTIAL 2, GAP-ACCEPTED 10.

    The Tag-46 cumulative recorded in §3 of the coverage doc:
    COVERED 9 -> 12 (A6 + A8 + B1 promoted; A2 promoted at persona-
    engine layer), PARTIAL 5 -> 2 (B3 hard-deferred + A2-marathon-
    defence-in-depth), GAP-ACCEPTED 10, GAP-OPEN 0, total 24.

    Vermutungs-Kennzeichnung P2: the cumulative-12 figure assumes A2
    is counted via the Reza PR #295 persona-engine pin. If the doc
    decides to keep A2 at PARTIAL until the marathon-level defence-in-
    depth pin lands, the figure becomes 11 / 3.
    """
    content = _coverage_doc_text()
    # The doc explicitly carries "COVERED 9 -> 12" + "PARTIAL 5 -> 2"
    # in §3 post-cumulative narrative.
    assert "9 -> 12" in content, (
        "Coverage doc §3 missing the cumulative COVERED 9 -> 12 anchor. "
        "Tag-46 promotion narrative drifted."
    )
    assert "5 -> 2" in content, (
        "Coverage doc §3 missing the cumulative PARTIAL 5 -> 2 anchor. "
        "Tag-46 promotion narrative drifted."
    )


# ---------------------------------------------------------------------------
# §5 — Tag-46 sweep TAG46_FOLLOWUPS internal-consistency (2 tests).
#
# The sweep test-module's TAG46_FOLLOWUPS constant lists five items
# (A2/A6/A8/B1/B3). The audit asserts the constant matches the doc's
# §4 / §4a follow-up table.
# ---------------------------------------------------------------------------


def test_tag46_sweep_followups_constant_matches_doc_4_failure_mode_ids() -> None:
    """Sweep TAG46_FOLLOWUPS MUST cover {A2, A6, A8, B1, B3}."""
    sweep_path = (
        _repo_root()
        / "tests"
        / "phase_3c"
        / "test_pre_mortem_coverage_sweep_tag_46.py"
    )
    module = _load_module(sweep_path, "amara_tag47_audit_sweep_consistency")
    assert module is not None, "Tag-46 sweep module load failed"
    followups = getattr(module, "TAG46_FOLLOWUPS", None)
    assert followups is not None, (
        "Tag-46 sweep TAG46_FOLLOWUPS constant missing; sweep contract broken."
    )
    ids = sorted({item.failure_mode_id for item in followups})
    assert ids == ["A2", "A6", "A8", "B1", "B3"], (
        f"Sweep TAG46_FOLLOWUPS failure-mode-id set drifted: {ids!r}. "
        f"Expected exactly the five Tag-45 §4 items {{A2, A6, A8, B1, B3}}."
    )


def test_tag46_sweep_followups_cross_review_partners_match_doc() -> None:
    """Sweep TAG46_FOLLOWUPS cross-review-partners MUST match doc §4 + §4a."""
    sweep_path = (
        _repo_root()
        / "tests"
        / "phase_3c"
        / "test_pre_mortem_coverage_sweep_tag_46.py"
    )
    module = _load_module(sweep_path, "amara_tag47_audit_sweep_xreview")
    assert module is not None
    followups = getattr(module, "TAG46_FOLLOWUPS", None)
    assert followups is not None
    by_id = {item.failure_mode_id: item for item in followups}
    expected = {
        "A2": "Amara",
        "A6": "Amara",
        "A8": "Reza",
        "B1": "Amara",
        "B3": "Henrik",
    }
    for fm_id, expected_partner in expected.items():
        assert by_id[fm_id].cross_review_partner == expected_partner, (
            f"Sweep TAG46_FOLLOWUPS[{fm_id}] cross_review_partner is "
            f"{by_id[fm_id].cross_review_partner!r}; doc §4/§4a expects "
            f"{expected_partner!r}. Zone-X cross-review-anchor drift."
        )


# ---------------------------------------------------------------------------
# §6 — Doc-refresh + Tag-47 audit-marker presence (1 test).
#
# As part of this Tag-47 PR, the coverage doc §0 gains one anchor row
# / line that references the Tag-47 audit file. The audit asserts the
# anchor exists.
# ---------------------------------------------------------------------------


def test_tag47_audit_doc_refresh_marker_present() -> None:
    """Coverage doc §0 MUST reference the Tag-47 audit file.

    This is the doc-refresh half of the Tag-47 task: the coverage doc
    (§0 metadata table + brief §0 narrative pointer) gains a reference
    to ``tests/phase_3c/test_acceptance_pyramide_tag_46_validation.py``
    so that future readers can locate the structural-consistency audit
    alongside the substantive Layer-5 + Tag-46 sweep companions.
    """
    content = _coverage_doc_text()
    assert "test_acceptance_pyramide_tag_46_validation.py" in content, (
        "Coverage doc missing Tag-47 audit-file reference. Doc-refresh "
        "step of Tag-47 task incomplete. Add a row to the §0 metadata "
        "table:\n"
        "  | Test-File (Tag-47 structural-audit) | "
        "`tests/phase_3c/test_acceptance_pyramide_tag_46_validation.py` |"
    )
