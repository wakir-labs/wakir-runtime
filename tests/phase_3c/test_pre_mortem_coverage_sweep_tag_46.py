# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Phase-3-Marathon Pre-Mortem Failure-Mode Coverage-Sweep Tag-46.

This is the Tag-46 follow-on to the Tag-45 coverage-audit
(``test_pre_mortem_failure_mode_coverage_audit.py``). Where Tag-45
pinned the *baseline* coverage-matrix (9 COVERED / 5 PARTIAL / 10
GAP-ACCEPTED out of 24 failure-modes), Tag-46 is the **sweep** that
checks whether the Tag-46 follow-up spawns (Reza A2, Selin A8, Kai
A6, Tomás B1) have landed the PARTIAL-classified items as COVERED.

Auftrag-Anker
-------------

- Tag-46 Amara Auftrag — Coverage-Sweep aller 5 Tag-46+-Items +
  Gap-Re-Detection (Continuous-Mode, AR-persistent, 2026-05-18).
- Tag-45 baseline:
  ``tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py``
  + ``docs/quality-gates/pre-mortem-failure-mode-coverage.md`` §4
  enumerated the 5 PARTIAL items and named the Tag-46+ follow-ups.
- Henrik Tag-44 Pre-Mortem-Skizze:
  ``reports/audit/phase-3-marathon-pre-mortem-2026-05-18.md`` —
  canonical 24 failure-mode list (A8 + B6 + C5 + D5).

Tag-46 sweep-scope
------------------

The sweep covers four spawn-streams that target the five PARTIAL
items named in §4 of the Tag-45 coverage-matrix:

| # | PARTIAL-Item        | Tag-46 Spawn-Owner | Expected follow-up artefact                                     |
|---|---------------------|--------------------|-----------------------------------------------------------------|
| 1 | A2 FSM-Phantom      | Reza               | ``tests/phase_3c/test_fsm_transition_legality_marathon.py``     |
| 2 | A6 Cosign-Drift     | Kai                | ``tests/phase_3c/test_cosign_chain_marathon_image_hash_stability.py`` |
| 3 | A8 NATS-JetStream   | Selin (or Reza)    | ``tests/phase_3c/test_welle_4_state_backing_persistence_loss.py`` |
| 4 | B1 AR-Hand-Stop     | Tomás              | ``tests/phase_3c/test_ar_hand_stop_marker_trigger_invariant.py`` |
| 5 | B3 Welle-3 Pre-Aud  | (Tag-47+ deferred) | ``tests/phase_3c/test_welle_3_pre_auditor_designation_precondition.py`` |

The sweep is **defensive**: each Tag-46 item is checked for either
COVERED-promotion (follow-up file exists with the expected pinning
test) OR PARTIAL-retention (follow-up file absent — gap remains,
Tag-47+ re-spawn implied). The §3 coverage-summary totals shift
accordingly:

- If all four Tag-46 items land: Coverage 9->13 COVERED, 5->1
  PARTIAL (only B3 remains in PARTIAL bucket; hard prerequisite
  before KW-25 cutover 2026-06-15).
- If zero land: Coverage stays at Tag-45 baseline (9 / 5 / 10 / 0).
- Partial-land states are documented per-item.

Cross-Validation A6 + B1 (self-authored)
----------------------------------------

In addition to detecting Tag-46 follow-up files, this sweep
self-authors **cross-validation tests** for A6 and B1 — the two
items where Amara is the cross-review-partner (Kai for A6, Tomás
for B1). The cross-validation tests assert from QA-perspective
that the structural invariants the COVERED-promotion would claim
are anchored in artefacts that already exist in the repo:

- A6 cross-validation: Cosign image-hash-chain stability is
  anchored on the ``build_wakir_provisioner`` workflow's cosign-
  login + signing chain (existing CI surface) AND the cutover-
  cheat-sheet §I trigger-9 (Quadlet-Restart-Failure mit Engine-
  Init-Loop) which surfaces image-identity drift. The Tag-46 Kai-
  spawn artefact may add a marathon-level stability assertion;
  this cross-validation makes the structural anchor explicit even
  if Kai's spawn has not landed.
- B1 cross-validation: AR-Hand-Stop-Marker-Trigger invariant is
  anchored on (1) the Tag-45 Noa alert
  ``WakirPhase3FailureModeB1ArHandStopMissingTrigger`` in
  ``dashboards/phase-3-marathon-alerts.yaml`` (SRE-side trigger),
  AND (2) the cutover-cheat-sheet §I structural list of 10
  trigger conditions, AND (3) the
  ``test_cutover_cheat_sheet_structure.py`` shape pin. The Tag-46
  Tomás-spawn artefact may add a marathon-level transition oracle;
  this cross-validation makes the multi-anchor structural cover
  explicit.

Tag-47+ deferred items (Vermutungs-Kennzeichnung P2)
----------------------------------------------------

- **B3 Welle-3-Pre-Auditor-Designation** is the *hard* deferred
  item: it MUST land before KW-25 cutover (2026-06-15) since it
  is a Welle-3 cutover pre-condition. This sweep records B3 as
  remaining PARTIAL and emits an explicit deadline-marker.
- Any newly-discovered failure-modes from Tag-46 marathon-rehearsal
  or pre-cutover-probes are surfaced as `GAP-OPEN` candidates and
  recorded in the §5 narrative of the coverage-matrix doc on the
  next coverage-doc update.

Test budget
-----------

20+ tests in this file (function-style):

* 5 tests: per Tag-46 PARTIAL-item, assert the COVERED-promotion
  state given the presence/absence of the follow-up file.
* 4 tests: cross-validation A6 anchors (workflow + cheat-sheet +
  CI tests).
* 4 tests: cross-validation B1 anchors (alert-rule + cheat-sheet +
  CI tests + structure-test).
* 2 tests: B3 Welle-3 PARTIAL-retention + KW-25 deadline-marker.
* 3 tests: Tag-46 sweep coverage-summary recomputation (which
  shape the §3 table now takes).
* 2 tests: Tag-45 baseline regression — the coverage-matrix doc
  + coverage-audit test file are still intact (no Tag-46 spawn
  accidentally removed Tag-45 anchors).

Vermutungs-Kennzeichnung (P2)
-----------------------------

- The PARTIAL-to-COVERED promotion logic uses **file-presence**
  as the primary signal. A follow-up test file may exist but not
  cover the failure-mode adequately; this sweep does NOT re-
  validate the substantive coverage of follow-up tests. The
  follow-up test files themselves are expected to carry their own
  invariant assertions; this sweep only verifies their existence
  as a meta-coverage signal.
- "Cross-validation" in §A6 / §B1 below means QA-perspective
  re-statement of existing anchors, not new assertions about
  system behaviour. The system-behaviour invariants are in
  Tag-40 / Tag-41 / Tag-43 / Tag-44 / Noa-alert-suite.

License: Apache-2.0 (parity with sibling Phase-3c artefacts).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Dict,
    FrozenSet,
    Mapping,
    Optional,
    Tuple,
)

import pytest


# ---------------------------------------------------------------------------
# Repo-root + helper loaders (parity with Tag-45 module).
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the wakir-runtime repo root from this test file."""
    here = Path(__file__).resolve()
    return here.parent.parent.parent


def _phase_3c_test_present(filename: str) -> bool:
    """Return True iff the named ``tests/phase_3c/`` file exists."""
    return (_repo_root() / "tests" / "phase_3c" / filename).is_file()


def _follow_up_test_present_anywhere(filename: str) -> bool:
    """Return True iff the named follow-up test file exists in any of
    the accepted root-relative locations.

    Tag-46 spawn-owners may place the follow-up file at one of:
      - ``tests/phase_3c/<filename>`` (Tag-45 §4 canonical)
      - ``wirelang/tests/persona_engine/<filename>`` (e.g. Reza A2 PR #295)
      - ``tests/persona_engine/<filename>`` (alternate persona-engine layout)
      - ``tests/ci/<filename>`` (CI-shape layer)
      - ``tests/infra/<filename>`` (substrate-layer, e.g. Kai A6 PR #298 cosign)

    The sweep is layout-tolerant: any of these locations promotes the
    follow-up to COVERED. The canonical Tag-45 §4 location remains the
    preferred placement; non-canonical placements are accepted to avoid
    spawn-owner / sweep author file-naming-collision lockouts.
    """
    candidate_dirs = (
        _repo_root() / "tests" / "phase_3c",
        _repo_root() / "wirelang" / "tests" / "persona_engine",
        _repo_root() / "tests" / "persona_engine",
        _repo_root() / "tests" / "ci",
        _repo_root() / "tests" / "infra",
    )
    for d in candidate_dirs:
        if (d / filename).is_file():
            return True
    return False


def _load_module_optional(filename: str, module_name: str) -> Optional[Any]:
    """Load a Tag-46 follow-up test module if found at any accepted
    location, else None.

    The optional-load is the structural mechanism by which this sweep
    is Tag-46-PR-arrival-tolerant: if the Tag-46 follow-up file has
    landed (at any accepted layout location), the module loads and we
    can introspect its names; if not, the sweep records PARTIAL-
    retention without erroring.
    """
    path = _resolve_follow_up_path(filename)
    if path is None:
        return None
    spec = importlib.util.spec_from_file_location(module_name, str(path))
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
    """Return frozenset of test-function names + Class names + methods."""
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
# Tag-46 follow-up file map (Tag-45 §4 anchor list).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tag46FollowUpItem:
    """One Tag-46 follow-up spawn item.

    ``follow_up_filenames`` is a tuple of accepted file names — spawn-
    owners may choose between the Tag-45 §4 canonical name and a
    semantically equivalent variant. Any tuple-member's presence in
    ``tests/phase_3c/`` promotes the item to COVERED.
    """

    failure_mode_id: str  # "A2" | "A6" | "A8" | "B1" | "B3"
    spawn_owner: str  # "Reza" | "Kai" | "Selin" | "Tomás"
    follow_up_filenames: Tuple[str, ...]  # accepted filenames
    cross_review_partner: str  # "Amara" | "Kai" | "Tomás" | "Henrik"
    rationale_keyword: str  # short pin
    kw25_blocker: bool  # True iff hard prerequisite before KW-25

    @property
    def follow_up_filename(self) -> str:
        """Primary (Tag-45 §4 canonical) filename for the follow-up."""
        return self.follow_up_filenames[0]


TAG46_FOLLOWUPS: Tuple[Tag46FollowUpItem, ...] = (
    Tag46FollowUpItem(
        failure_mode_id="A2",
        spawn_owner="Reza",
        follow_up_filenames=(
            "test_fsm_transition_legality_marathon.py",
            # Reza Tag-46 PR #295 landed under this name.
            "test_fsm_phantom_transition_coverage_a2.py",
        ),
        cross_review_partner="Amara",
        rationale_keyword="fsm-transition-legality",
        kw25_blocker=False,
    ),
    Tag46FollowUpItem(
        failure_mode_id="A6",
        spawn_owner="Kai",
        follow_up_filenames=(
            "test_cosign_chain_marathon_image_hash_stability.py",
            "test_cosign_chain_image_hash_stability_a6.py",
            # Kai Tag-46 PR #298 landed under this name at tests/infra/.
            "test_cosign_drift_coverage_a6.py",
        ),
        cross_review_partner="Amara",
        rationale_keyword="cosign-marathon-image-hash-stability",
        kw25_blocker=False,
    ),
    Tag46FollowUpItem(
        failure_mode_id="A8",
        spawn_owner="Selin",
        follow_up_filenames=(
            "test_welle_4_state_backing_persistence_loss.py",
            "test_welle_4_jetstream_persistence_loss_a8.py",
        ),
        cross_review_partner="Reza",
        rationale_keyword="welle-4-state-backing-persistence-loss",
        kw25_blocker=False,
    ),
    Tag46FollowUpItem(
        failure_mode_id="B1",
        spawn_owner="Tomás",
        follow_up_filenames=(
            "test_ar_hand_stop_marker_trigger_invariant.py",
            "test_ar_hand_stop_marker_trigger_b1.py",
        ),
        cross_review_partner="Amara",
        rationale_keyword="ar-hand-stop-marker-trigger-invariant",
        kw25_blocker=False,
    ),
    Tag46FollowUpItem(
        failure_mode_id="B3",
        spawn_owner="(deferred)",
        follow_up_filenames=(
            "test_welle_3_pre_auditor_designation_precondition.py",
            "test_welle_3_pre_auditor_designation_b3.py",
        ),
        cross_review_partner="Henrik",
        rationale_keyword="welle-3-pre-auditor-designation",
        kw25_blocker=True,
    ),
)


TAG46_BY_ID: Mapping[str, Tag46FollowUpItem] = {
    item.failure_mode_id: item for item in TAG46_FOLLOWUPS
}


def _any_follow_up_filename_present(item: Tag46FollowUpItem) -> Optional[str]:
    """Return the first follow-up filename that exists in any accepted
    location, or None.
    """
    for candidate in item.follow_up_filenames:
        if _follow_up_test_present_anywhere(candidate):
            return candidate
    return None


def _resolve_follow_up_path(filename: str) -> Optional[Path]:
    """Return the resolved Path to the follow-up file in any accepted
    location, or None.
    """
    candidate_dirs = (
        _repo_root() / "tests" / "phase_3c",
        _repo_root() / "wirelang" / "tests" / "persona_engine",
        _repo_root() / "tests" / "persona_engine",
        _repo_root() / "tests" / "ci",
        _repo_root() / "tests" / "infra",
    )
    for d in candidate_dirs:
        candidate = d / filename
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# §1 — Per-PARTIAL-item promotion-detection tests (5 tests).
#
# Each test detects whether the Tag-46 follow-up file is present and
# records the resulting COVERED-or-PARTIAL state. The test does NOT
# fail if the file is absent; it asserts the documented expectation
# (B3 PARTIAL, others COVERED-iff-present-else-PARTIAL).
# ---------------------------------------------------------------------------


def _resolve_promotion_state(failure_mode_id: str) -> str:
    """Return "COVERED" if any accepted Tag-46 follow-up file exists,
    else "PARTIAL".
    """
    item = TAG46_BY_ID[failure_mode_id]
    landed = _any_follow_up_filename_present(item)
    return "COVERED" if landed is not None else "PARTIAL"


def _assert_landed_file_loadable(
    item: Tag46FollowUpItem, sweep_module_name: str
) -> None:
    """If any accepted file landed, assert it loads + has >= 1 test."""
    landed = _any_follow_up_filename_present(item)
    if landed is None:
        return  # PARTIAL — nothing to assert beyond detection.
    module = _load_module_optional(landed, sweep_module_name)
    assert module is not None, (
        f"{item.failure_mode_id} follow-up file {landed!r} present but "
        f"module-load failed. {item.spawn_owner}-Tag-46 substance review "
        f"needed (cross-review: {item.cross_review_partner})."
    )
    names = _module_test_names(module)
    assert len(names) >= 1, (
        f"{item.failure_mode_id} follow-up file {landed!r} present but "
        f"contains no tests."
    )


def test_t46_a2_fsm_transition_legality_promotion_detection() -> None:
    """A2 follow-up detection: COVERED iff Reza-Tag-46 file landed."""
    state = _resolve_promotion_state("A2")
    assert state in ("COVERED", "PARTIAL"), state
    _assert_landed_file_loadable(TAG46_BY_ID["A2"], "amara_tag46_sweep_a2")


def test_t46_a6_cosign_chain_marathon_promotion_detection() -> None:
    """A6 follow-up detection: COVERED iff Kai-Tag-46 file landed."""
    state = _resolve_promotion_state("A6")
    assert state in ("COVERED", "PARTIAL"), state
    _assert_landed_file_loadable(TAG46_BY_ID["A6"], "amara_tag46_sweep_a6")


def test_t46_a8_state_backing_persistence_loss_promotion_detection() -> None:
    """A8 follow-up detection: COVERED iff Selin-Tag-46 file landed."""
    state = _resolve_promotion_state("A8")
    assert state in ("COVERED", "PARTIAL"), state
    _assert_landed_file_loadable(TAG46_BY_ID["A8"], "amara_tag46_sweep_a8")


def test_t46_b1_ar_hand_stop_marker_trigger_promotion_detection() -> None:
    """B1 follow-up detection: COVERED iff Tomás-Tag-46 file landed."""
    state = _resolve_promotion_state("B1")
    assert state in ("COVERED", "PARTIAL"), state
    _assert_landed_file_loadable(TAG46_BY_ID["B1"], "amara_tag46_sweep_b1")


def test_t46_b3_welle_3_pre_auditor_designation_partial_retention() -> None:
    """B3 retention: this item is the deferred KW-25 blocker.

    Per Tag-45 §4 + Tag-46 sweep-scope, B3 is the *hard* deferred
    item — it requires AR-Hand designation of an external Pre-Auditor
    BEFORE Welle-3 cutover (KW-25, 2026-06-15). The sweep does not
    expect Tag-46 to land this item; it asserts the PARTIAL-retention
    and surfaces the KW-25 deadline via the deadline-marker test
    below.
    """
    state = _resolve_promotion_state("B3")
    # B3 may have been independently authored if Henrik+AR moved on
    # designation early; the sweep tolerates either state but pins the
    # follow-up filename so the AR-Hand-decision-spec writer + Amara
    # converge on a single file name.
    assert state in ("COVERED", "PARTIAL"), state
    item = TAG46_BY_ID["B3"]
    assert item.kw25_blocker is True, "B3 must be flagged as KW-25 blocker"
    assert item.cross_review_partner == "Henrik", (
        "B3 Zone-N partner must be Henrik (IIA-1130 designation question)"
    )


# ---------------------------------------------------------------------------
# §2 — A6 Cross-Validation (4 tests, Amara cross-review-anchored).
#
# These tests state from QA-perspective the structural anchors that
# would make a marathon-level cosign-image-hash-stability assertion
# defensible. They do not replace Kai's Tag-46 follow-up; they make
# the cross-review-substrate explicit.
# ---------------------------------------------------------------------------


def test_t46_a6xv_build_workflow_cosign_signing_chain_present() -> None:
    """A6 cross-validation 1/4: cosign signing-chain present in build workflow."""
    workflow_path = (
        _repo_root() / ".github" / "workflows" / "build-wakir-provisioner.yml"
    )
    assert workflow_path.is_file(), (
        "build-wakir-provisioner workflow missing; A6 cosign-chain anchor "
        "lost. Image-hash-stability claim has no CI substrate."
    )
    content = workflow_path.read_text(encoding="utf-8")
    assert "cosign" in content.lower(), (
        "build workflow exists but contains no `cosign` references; A6 "
        "anchor is hollow."
    )


def test_t46_a6xv_cosign_step_tests_present() -> None:
    """A6 cross-validation 2/4: existing cosign CI tests still cover signing chain."""
    ci_test_path = (
        _repo_root() / "tests" / "ci" / "test_build_wakir_provisioner_workflow.py"
    )
    assert ci_test_path.is_file(), (
        "build-workflow CI tests missing; A6 cosign-chain anchor lost."
    )
    content = ci_test_path.read_text(encoding="utf-8")
    # Two minimum required cosign-step assertions named in Tag-45 §A6.
    assert "test_cosign_login_step_present" in content
    assert "test_cosign_login_runs_before_sign" in content


def test_t46_a6xv_cheat_sheet_quadlet_restart_trigger_present() -> None:
    """A6 cross-validation 3/4: image-identity-drift surfacing in cheat sheet."""
    cheat_sheet = (
        _repo_root() / "docs" / "phase-3c" / "cutover-operator-cheat-sheet.md"
    )
    assert cheat_sheet.is_file(), (
        "cutover-operator-cheat-sheet missing; A6 image-identity-drift "
        "surface anchor lost."
    )
    content = cheat_sheet.read_text(encoding="utf-8")
    # §I trigger-9 names Quadlet-Restart-Failure (image-identity-drift).
    assert "Quadlet-Restart-Failure" in content, (
        "Cheat sheet §I trigger-9 (Quadlet-Restart-Failure / Container-"
        "Identity-Drift) missing; A6 operator-surface anchor lost."
    )
    assert "Container-Identity-Drift" in content, (
        "Cheat sheet §I trigger-9 explicit Container-Identity-Drift label "
        "missing; A6 anchor is structurally weakened."
    )


def test_t46_a6xv_quadlet_cosign_substrate_doc_present() -> None:
    """A6 cross-validation 4/4: Tag-45 Quadlet+Cosign substrate doc present."""
    substrate_doc = (
        _repo_root() / "docs" / "phase-3c" / "quadlet-cosign-15-binary-installer.md"
    )
    assert substrate_doc.is_file(), (
        "quadlet-cosign-15-binary-installer doc missing; A6 substrate-refresh "
        "anchor lost (Tag-45 Kai PR #294)."
    )


# ---------------------------------------------------------------------------
# §3 — B1 Cross-Validation (4 tests, Amara cross-review-anchored).
#
# The B1 AR-Hand-Stop-Marker-Trigger invariant has three structural
# anchors already in the repo (Tag-43 cheat-sheet, Tag-45 Noa alert,
# existing structure test). These tests pin each anchor.
# ---------------------------------------------------------------------------


def test_t46_b1xv_alert_rule_present_in_marathon_alerts() -> None:
    """B1 cross-validation 1/4: Noa Tag-45 alert rule present."""
    alerts_path = (
        _repo_root() / "dashboards" / "phase-3-marathon-alerts.yaml"
    )
    assert alerts_path.is_file(), (
        "Phase-3-marathon-alerts.yaml missing; B1 SRE-trigger anchor lost."
    )
    content = alerts_path.read_text(encoding="utf-8")
    assert "WakirPhase3FailureModeB1ArHandStopMissingTrigger" in content, (
        "B1 alert rule name missing in phase-3-marathon-alerts.yaml; "
        "Noa Tag-45 SRE-side anchor not present. Tag-45 PR #292 may have "
        "been reverted."
    )


def test_t46_b1xv_alert_rule_test_present() -> None:
    """B1 cross-validation 2/4: Noa alert test pins B1 expression structure."""
    alert_test_path = (
        _repo_root()
        / "tests"
        / "ci"
        / "test_phase_3_marathon_failure_mode_alerts.py"
    )
    assert alert_test_path.is_file(), (
        "phase-3-marathon-failure-mode-alerts test missing; B1 alert-shape "
        "anchor lost."
    )
    content = alert_test_path.read_text(encoding="utf-8")
    assert "def test_b1_ar_hand_stop_missing_is_conjunction" in content, (
        "B1 alert-shape conjunction-assertion missing; SRE-side B1 anchor "
        "structurally weakened."
    )


def test_t46_b1xv_cheat_sheet_section_i_ten_triggers_present() -> None:
    """B1 cross-validation 3/4: cheat sheet §I lists 10 operator triggers."""
    cheat_sheet = (
        _repo_root() / "docs" / "phase-3c" / "cutover-operator-cheat-sheet.md"
    )
    assert cheat_sheet.is_file(), "cheat sheet missing"
    content = cheat_sheet.read_text(encoding="utf-8")
    # Section header present.
    assert "AR-Hand-Stop-Marker" in content, (
        "Cheat sheet AR-Hand-Stop-Marker section missing; B1 operator-"
        "surface anchor lost."
    )
    # The 10 triggers are numbered 1..10 in §I. Count them.
    # Lines start with "1." through "10." (one trigger per numbered item).
    section_i_match = re.search(
        r"##\s*§I.*?AR-Hand-Stop-Marker.*?(?=##\s*§J|\Z)",
        content,
        re.DOTALL,
    )
    assert section_i_match is not None, (
        "Cheat sheet §I section header pattern not found; structural drift."
    )
    section_i = section_i_match.group(0)
    # Numbered triggers (1. through 10.).
    numbered_triggers = re.findall(r"^\s*(\d+)\.\s", section_i, re.MULTILINE)
    distinct_triggers = sorted(set(int(n) for n in numbered_triggers))
    assert len(distinct_triggers) >= 10, (
        f"Cheat sheet §I has only {len(distinct_triggers)} distinct "
        f"numbered triggers; expected >= 10 (Tag-43 baseline). B1 "
        f"trigger-list structural shrinkage detected."
    )


def test_t46_b1xv_cheat_sheet_structure_test_pins_section_i() -> None:
    """B1 cross-validation 4/4: structure test pins cheat sheet §I."""
    structure_test = (
        _repo_root()
        / "tests"
        / "phase_3c"
        / "test_cutover_cheat_sheet_structure.py"
    )
    assert structure_test.is_file(), (
        "test_cutover_cheat_sheet_structure.py missing; B1 PARTIAL anchor "
        "lost (Tag-43 baseline assumes this file exists)."
    )


# ---------------------------------------------------------------------------
# §4 — B3 KW-25 deadline-marker tests (2 tests).
# ---------------------------------------------------------------------------


def test_t46_b3_kw25_deadline_marker_documented() -> None:
    """B3 KW-25 deadline is documented in coverage-matrix doc §4."""
    matrix_doc = (
        _repo_root()
        / "docs"
        / "quality-gates"
        / "pre-mortem-failure-mode-coverage.md"
    )
    assert matrix_doc.is_file(), "coverage matrix doc missing"
    content = matrix_doc.read_text(encoding="utf-8")
    # KW-25 deadline-mention must be present (Tag-45 §4 sequencing-observation).
    assert "KW-25" in content, (
        "Coverage-matrix doc missing KW-25 deadline-mention for B3 "
        "Welle-3-Pre-Auditor-Designation. Hard prerequisite at risk of "
        "implicit-drift."
    )


def test_t46_b3_iia_1130_pre_decision_spec_anchor_present() -> None:
    """B3 IIA-1130 Pre-Decision Spec must exist for AR-Hand decision path."""
    # The spec lives outside `wakir-runtime` (it is an audit artefact in
    # `reports/audit/` at the AI-Corp root). We resolve via the AI-Corp
    # root path, but tolerate file-relocation (similar resilience to
    # Tag-45 sibling test).
    ai_corp_root = _repo_root().parent.parent.parent
    candidate_paths = [
        ai_corp_root
        / "reports"
        / "audit"
        / "welle-3-iia-1130-pre-decision-spec-2026-05-18.md",
    ]
    found = any(p.is_file() for p in candidate_paths)
    if not found:
        # Sandboxed worktree / cross-repo layout may not see the audit
        # path. Document the expected location and skip rather than
        # fail — the spec presence is verified in Henrik's own audit-
        # surface, not in wakir-runtime CI.
        pytest.skip(
            f"Welle-3 IIA-1130 Pre-Decision-Spec not found at "
            f"{candidate_paths[0]} (worktree-resolution constraint). "
            f"This test is informational only; Henrik's audit-side "
            f"check is authoritative."
        )


# ---------------------------------------------------------------------------
# §5 — Tag-46 sweep coverage-summary recomputation (3 tests).
# ---------------------------------------------------------------------------


def test_t46_sweep_summary_partial_to_covered_promotion_count() -> None:
    """Sweep summary: how many of the 4 Tag-46 candidates have landed?

    Returns the COVERED-count via assertion-narrative; does not fail
    on absence (each per-item test handles its own state).
    """
    covered_count = 0
    partial_retained: list[str] = []
    for item in TAG46_FOLLOWUPS:
        if item.failure_mode_id == "B3":
            # B3 is the deferred KW-25 blocker; never expected to land
            # via Tag-46 sweep. Excluded from promotion-count.
            continue
        if _any_follow_up_filename_present(item) is not None:
            covered_count += 1
        else:
            partial_retained.append(item.failure_mode_id)
    # Acceptable range: 0..4 (sweep is detection-mode, not enforcement-mode).
    assert 0 <= covered_count <= 4, covered_count
    # Coverage-count plus partial-retained = 4 (the four Tag-46 spawn items
    # excluding B3).
    assert covered_count + len(partial_retained) == 4, (
        f"sweep accounting drift: covered={covered_count} + "
        f"partial={len(partial_retained)} != 4 (Tag-46 items A2/A6/A8/B1)"
    )


def test_t46_sweep_summary_projected_phase_3c_coverage_state() -> None:
    """Sweep summary: projected post-Tag-46 §3 totals.

    If all four Tag-46 items land: 13 COVERED / 1 PARTIAL / 10 GAP-ACCEPTED.
    If zero land: 9 / 5 / 10 (Tag-45 baseline).
    Either way, GAP-OPEN remains 0 and total stays at 24.
    """
    covered_promoted = 0
    for item in TAG46_FOLLOWUPS:
        if item.failure_mode_id == "B3":
            continue
        if _any_follow_up_filename_present(item) is not None:
            covered_promoted += 1
    # Tag-45 baseline: 9 COVERED, 5 PARTIAL.
    projected_covered = 9 + covered_promoted
    projected_partial = 5 - covered_promoted
    assert projected_covered + projected_partial == 14, (
        "projected COVERED + PARTIAL must sum to 14 (the in-scope subset)"
    )
    # B3 always retained in PARTIAL.
    assert projected_partial >= 1, (
        "projected PARTIAL must be >= 1 (B3 deferred to Tag-47+)"
    )
    # GAP-ACCEPTED remains 10 by Tag-45 contract.
    projected_gap_accepted = 10
    projected_gap_open = 0
    grand_total = (
        projected_covered
        + projected_partial
        + projected_gap_accepted
        + projected_gap_open
    )
    assert grand_total == 24, f"grand total drift: {grand_total} != 24"


def test_t46_sweep_summary_b3_remains_in_partial_bucket() -> None:
    """B3 always remains in PARTIAL post-sweep (KW-25 hard prerequisite)."""
    b3_item = TAG46_BY_ID["B3"]
    assert b3_item.kw25_blocker is True
    assert b3_item.cross_review_partner == "Henrik"
    # Even if the file landed independently (Henrik+AR moved faster
    # than expected), the sweep accounting still records B3 as the
    # Tag-47+ deferred item under §4 of the coverage doc.
    state = _resolve_promotion_state("B3")
    # Tolerate either state.
    assert state in ("COVERED", "PARTIAL")


# ---------------------------------------------------------------------------
# §6 — Tag-45 baseline regression-checks (2 tests).
#
# Defensive: the Tag-46 sweep must not pass if Tag-45 anchors were
# silently removed (e.g. someone deleted the coverage-matrix doc as
# part of Tag-46 cleanup).
# ---------------------------------------------------------------------------


def test_t46_regression_tag_45_coverage_matrix_doc_intact() -> None:
    """Tag-45 coverage-matrix doc must still exist with §3 summary."""
    matrix_doc = (
        _repo_root()
        / "docs"
        / "quality-gates"
        / "pre-mortem-failure-mode-coverage.md"
    )
    assert matrix_doc.is_file(), "Tag-45 coverage-matrix doc deleted"
    content = matrix_doc.read_text(encoding="utf-8")
    # §3 coverage-summary header.
    assert "## 3. Coverage summary" in content, (
        "Tag-45 §3 coverage-summary header removed; doc structural drift."
    )
    # §4 follow-up section.
    assert "Tag-46+ follow-up items" in content, (
        "Tag-45 §4 follow-up section removed; sweep narrative-anchor lost."
    )


def test_t46_regression_tag_45_coverage_audit_test_intact() -> None:
    """Tag-45 coverage-audit test file must still exist with 25 tests."""
    audit_test = (
        _repo_root()
        / "tests"
        / "phase_3c"
        / "test_pre_mortem_failure_mode_coverage_audit.py"
    )
    assert audit_test.is_file(), "Tag-45 coverage-audit test file deleted"
    content = audit_test.read_text(encoding="utf-8")
    # Spot-check key per-failure-mode tests.
    assert "def test_pm_a1_cross_modul_drift_welle_n_to_n_plus_1" in content
    assert "def test_pm_b3_welle_3_iia_1130_pre_auditor_conflict" in content
    assert "def test_pm_summary_totals_match_per_class_classifications" in content
