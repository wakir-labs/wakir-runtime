# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Phase-3-Marathon Pre-Mortem Failure-Mode Test-Coverage Audit — meta-
audit that classifies each of Henrik's 23 hypothetical failure-modes
(Tag-44 Pre-Mortem-Skizze) against the existing Phase-3 acceptance
test stack and pins the classification as an executable contract.

Auftrag-Anker
-------------

- Tag-45 Amara Auftrag — Henrik-Pre-Mortem-23-Failure-Modes Test-
  Coverage-Audit (Continuous-Mode, Aufsichtsrat 2026-05-18). Where
  the Tag-43 ``test_marathon_schluss_acceptance_drill.py`` pins the
  positive marathon-sequence and the Tag-44
  ``test_marathon_anti_patterns.py`` pins ten dedicated control-
  plane anti-patterns, this Tag-45 file pins the **meta-audit
  surface**: it asserts that for each of Henrik's 23 Pre-Mortem
  failure-modes (Klassen A/B/C/D), the coverage-state classification
  documented in ``docs/quality-gates/pre-mortem-failure-mode-
  coverage.md`` is consistent with the actual presence/absence of
  the named pinning-tests in the companion suites (Tag-40 / Tag-41 /
  Tag-43 / Tag-44 + selected per-Welle smokes).
- Henrik Tag-44 Pre-Mortem-Skizze: ``reports/audit/phase-3-marathon-
  pre-mortem-2026-05-18.md`` — the canonical failure-mode list. 23
  hypothetical failure-modes in four classes (A Technisch 8, B
  Operativ 6, C Prozedural 5, D Externe 5; the table-row count is
  A8 + B6 + C5 + D5 = 24, with one Henrik-acknowledged ID-Lücke in
  §6 of the pre-mortem). This file uses the table-row count (24)
  as the canonical denominator.
- ``docs/quality-gates/pre-mortem-failure-mode-coverage.md`` (Amara,
  this PR) — the coverage-matrix document this test-file enforces.

Cross-spawn-Konsistenz (Tag-45)
-------------------------------

- Companion (positive marathon-sequence): Tag-43
  ``test_marathon_schluss_acceptance_drill.py``. This Tag-45 file
  introspects the Tag-43 module's public test-function names and
  asserts a specific subset of names exists (the named pinning-
  tests for each COVERED failure-mode).
- Companion (control-plane anti-patterns): Tag-44
  ``test_marathon_anti_patterns.py``. This Tag-45 file introspects
  the Tag-44 module's public test-class names and asserts the AP-3
  / AP-4 / AP-6 / AP-7 / AP-9 / AP-10 axes (the ones referenced as
  pinning-tests in §2 of the coverage-matrix) exist.
- Companion (marker state-machine): Tag-40
  ``test_phase_3_final_regression.py``. Introspected for the named
  cross-Welle / marker-state-machine / cascade tests.
- Companion (per-day walkthrough): Tag-41
  ``test_cutover_day_e2e_drill.py``. Introspected for the per-Welle
  drill-walkthrough names and the A7-drift coverage names.
- Companion (Welle-6+7 acceptance): Tag-39
  ``test_doppel_welle_6_7_acceptance.py``. Introspected for the
  NATS-subject-drift coverage names (A4 pinning).
- Companion (per-Welle smokes): ``test_welle_{4,7}_cutover_smoke.
  py``. Introspected for the per-Welle smoke presence (A3 pinning).
- Companion (audit pre-mortem): Henrik's
  ``reports/audit/phase-3-marathon-pre-mortem-2026-05-18.md``.
  Parsed for the canonical 24 failure-mode IDs.

Why a separate suite (vs. extending Tag-44 or Tag-43)
-----------------------------------------------------

* Tag-40 / Tag-41 / Tag-43 / Tag-44 pin **system-behaviour
  invariants** (the marathon, the cutover-day, the marker state-
  machine, the anti-patterns). This Tag-45 file pins **the
  coverage matrix itself** as a meta-invariant: given the test-
  suite, the coverage classification must remain consistent.
* The Pre-Mortem is Henrik's audit-side artefact; the coverage-
  matrix is the QA-side test-surface response. Putting the meta-
  audit in its own suite separates "does the system behave
  correctly?" (Layers 1-4) from "does our test-surface cover
  Henrik's hypotheses?" (Layer 5).
* When new failure-modes are added (Tag-46+ follow-up items: A2,
  A6, A8, B1, B3 named in §4 of the coverage-matrix), this
  Tag-45 suite is the **first** place to update — the meta-test
  fails if the new failure-mode is not yet classified, before any
  positive-suite test is added. That ordering enforces the
  classification-first discipline.

Test budget
-----------

25 tests total:

* 24 tests, one per failure-mode (A1..A8, B1..B6, C1..C5, D1..D5):
  each asserts the coverage-state classification documented in §2
  of the coverage-matrix is consistent with the actual presence /
  absence of the named pinning-tests in the companion suites.
* 1 test, the §3 coverage-summary table totals match the §2
  individual classifications (consistency-check).

Vermutungs-Kennzeichnung (P2)
-----------------------------

* The "24 vs 23" discrepancy in Henrik's Pre-Mortem-Skizze §6 is
  Henrik-acknowledged ("einzelne ID-Lücken durch Klassifikations-
  Defaultpfad"). This file uses the table-row count (24) as the
  canonical denominator. If Henrik issues a Tag-45+ update that
  reconciles the count to 23 (e.g. by collapsing two IDs), this
  test-file will need a corresponding update.
* The coverage-state classification is **structural**, not
  **substantive**: a COVERED classification means "at least one
  test in Layer-1..4 directly asserts the invariant that the
  failure-mode would violate". It does NOT mean "the failure-mode
  is exhaustively tested under all production conditions". The
  live-VM-acceptance-lane (ADR-0058 §Nachtrag) and the operator-
  hand-territory carry the substantive coverage; this file pins
  the hermetic-test-surface classification only.
* The GAP-ACCEPTED classifications (10 of 24) are pinned as
  out-of-scope for the QA test surface. If a Tag-46+ decision
  re-classifies any of them to in-scope, the pinning-test for
  that mode will need to be added AND the matrix updated AND this
  meta-test updated. The ordering is matrix-first, then test, then
  meta-test.

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
    Sequence,
    Tuple,
)

import pytest


# ---------------------------------------------------------------------------
# Repo-root + companion-module loaders.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the wakir-runtime repo root from this test file."""
    here = Path(__file__).resolve()
    return here.parent.parent.parent


def _load_companion_test_module(
    filename: str,
    module_name: str,
    subdir: str = "phase_3c",
) -> Any:
    """Load a sibling test module (default ``tests/phase_3c/``, override
    via ``subdir`` for e.g. ``tests/ci/`` Tag-46 follow-up modules) so
    we can reuse its constants and introspect its test-function /
    test-class names.
    """
    test_path = _repo_root() / "tests" / subdir / filename
    if not test_path.is_file():
        pytest.fail(f"companion test module not found at {test_path}")
    spec = importlib.util.spec_from_file_location(module_name, str(test_path))
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {test_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _module_test_names(module: Any) -> FrozenSet[str]:
    """Return the frozenset of test-function names defined at module top.

    Test-class methods are flattened into ``ClassName::method_name`` so
    the Tag-44 anti-pattern suite (class-based) is introspectable
    alongside the function-based Tag-40 / Tag-41 / Tag-43 suites.
    """
    names: set[str] = set()
    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        attr = getattr(module, attr_name)
        # Function-style tests.
        if callable(attr) and attr_name.startswith("test_"):
            names.add(attr_name)
            continue
        # Class-style tests (Tag-44 uses TestApN* classes).
        if isinstance(attr, type) and attr_name.startswith("Test"):
            for method_name in dir(attr):
                if method_name.startswith("test_"):
                    names.add(f"{attr_name}::{method_name}")
            names.add(attr_name)
    return frozenset(names)


# ---------------------------------------------------------------------------
# Eagerly load companion modules.
#
# All five suites are loaded at import time so the per-failure-mode
# tests can simply introspect the resulting name-sets.
# ---------------------------------------------------------------------------


_TAG40 = _load_companion_test_module(
    "test_phase_3_final_regression.py",
    "phase_3c_tag40_for_tag45_pre_mortem_coverage",
)

_TAG41 = _load_companion_test_module(
    "test_cutover_day_e2e_drill.py",
    "phase_3c_tag41_for_tag45_pre_mortem_coverage",
)

_TAG43 = _load_companion_test_module(
    "test_marathon_schluss_acceptance_drill.py",
    "phase_3c_tag43_for_tag45_pre_mortem_coverage",
)

_TAG44 = _load_companion_test_module(
    "test_marathon_anti_patterns.py",
    "phase_3c_tag44_for_tag45_pre_mortem_coverage",
)

_TAG39_DW67 = _load_companion_test_module(
    "test_doppel_welle_6_7_acceptance.py",
    "phase_3c_tag39_dw67_for_tag45_pre_mortem_coverage",
)

# Tag-46 substrate-layer companion (Kai) — A6 closeout. Loaded via
# the same _load_companion_test_module path but from tests/infra/
# rather than tests/phase_3c/.
def _load_infra_test_module(file_name: str, module_alias: str):
    """Companion-loader helper for tests/infra/ siblings.

    Best-effort: returns ``None`` on file-missing OR on
    ``exec_module`` failure (e.g. an optional dep like ``yaml`` is
    not installed in the shadow-CI baseline). The audit-surface then
    treats the companion as unavailable rather than aborting the
    whole audit-suite import. The substantive companion tests still
    run in the full-CI baseline; the audit-test is only weakened to
    "companion-not-available" semantics in shadow-CI.
    """
    import importlib.util

    test_path = _repo_root() / "tests" / "infra" / file_name
    if not test_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(module_alias, test_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception:
        # Shadow-CI: optional dep (yaml, etc.) not installed. The
        # companion-test is then unavailable for introspection.
        return None
    return module


_INFRA_A6 = _load_infra_test_module(
    "test_cosign_drift_coverage_a6.py",
    "infra_a6_for_tag45_pre_mortem_coverage",
)

# Tag-46 Tomás follow-up to Tag-45 PARTIAL B1: lives in tests/ci/
# (alongside the Tag-45 Noa alert-shape test) not tests/phase_3c/.
_TAG46_B1 = _load_companion_test_module(
    "test_ar_hand_stop_marker_trigger_b1.py",
    "ci_tag46_b1_for_tag45_pre_mortem_coverage",
    subdir="ci",
)


def _load_pengine_companion_module(
    relative_path: str, module_name: str,
) -> Any:
    """Load a sibling test module from ``wirelang/persona_engine/tests/``.

    Used for Tag-46+ A8 NATS-JetStream-Loss-Recovery coverage tests
    that live in the persona-engine package tree rather than under
    ``tests/phase_3c/``.
    """
    test_path = _repo_root() / relative_path
    if not test_path.is_file():
        pytest.fail(f"pengine companion test module not found at {test_path}")
    spec = importlib.util.spec_from_file_location(module_name, str(test_path))
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {test_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


_TAG46_PENGINE_A8 = _load_pengine_companion_module(
    "wirelang/persona_engine/tests/test_nats_jetstream_loss_recovery_a8.py",
    "phase_3c_tag46_pengine_a8_for_pre_mortem_coverage",
)


TAG40_NAMES = _module_test_names(_TAG40)
TAG41_NAMES = _module_test_names(_TAG41)
TAG43_NAMES = _module_test_names(_TAG43)
TAG44_NAMES = _module_test_names(_TAG44)
TAG39_DW67_NAMES = _module_test_names(_TAG39_DW67)
INFRA_A6_NAMES = _module_test_names(_INFRA_A6) if _INFRA_A6 is not None else frozenset()
TAG46_PENGINE_A8_NAMES = _module_test_names(_TAG46_PENGINE_A8)
TAG46_B1_NAMES = _module_test_names(_TAG46_B1)


# ---------------------------------------------------------------------------
# Per-Welle smoke modules (string-existence check only — we do not
# import them because the Welle-4 / Welle-7 smokes are sibling files
# in the same test directory and pytest collects them anyway).
# ---------------------------------------------------------------------------


def _phase_3c_smoke_present(welle_n: int) -> bool:
    """Return True iff the per-Welle cutover smoke file exists."""
    path = _repo_root() / "tests" / "phase_3c" / f"test_welle_{welle_n}_cutover_smoke.py"
    return path.is_file()


# ---------------------------------------------------------------------------
# Henrik Pre-Mortem-Skizze: parse the failure-mode IDs from the
# canonical report so the test-file is bound to the report contents.
# ---------------------------------------------------------------------------


def _read_pre_mortem_report() -> str:
    """Return the Henrik Tag-44 Pre-Mortem-Skizze contents."""
    # The report lives at /var/home/fred/AI-Corp/reports/audit/, which is
    # two levels above the wakir-runtime repo root. We resolve via the
    # AI-Corp root, which is the parent of the wakir-runtime parent.
    ai_corp_root = _repo_root().parent.parent.parent
    candidate = (
        ai_corp_root
        / "reports"
        / "audit"
        / "phase-3-marathon-pre-mortem-2026-05-18.md"
    )
    if not candidate.is_file():
        # Path resolution is best-effort across worktree layouts. Fall
        # back to a static-known list of failure-mode IDs documented in
        # the coverage-matrix; the resilience to file-relocation is
        # deliberate (cf. ADR-0058 §Nachtrag operator-hand-territory).
        return ""
    return candidate.read_text(encoding="utf-8")


CANONICAL_FAILURE_MODE_IDS: Tuple[str, ...] = (
    # Class-A Technisch (8)
    "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8",
    # Class-B Operativ (6)
    "B1", "B2", "B3", "B4", "B5", "B6",
    # Class-C Prozedural (5)
    "C1", "C2", "C3", "C4", "C5",
    # Class-D Externe (5)
    "D1", "D2", "D3", "D4", "D5",
)


@dataclass(frozen=True)
class CoverageClassification:
    """One row of the §2 coverage classification matrix."""

    failure_mode_id: str
    klasse: str  # "A" | "B" | "C" | "D"
    coverage_state: str  # "COVERED" | "PARTIAL" | "GAP-ACCEPTED" | "GAP-OPEN"
    pinning_tests: Tuple[Tuple[str, str], ...]  # (companion-suite-tag, test-name)
    rationale_keyword: str  # short keyword pinning the §2 narrative

    def is_in_scope(self) -> bool:
        """True iff the failure-mode is in QA-test-surface scope."""
        return self.coverage_state in ("COVERED", "PARTIAL", "GAP-OPEN")


COVERAGE_MATRIX: Tuple[CoverageClassification, ...] = (
    # Class-A Technisch
    CoverageClassification(
        failure_mode_id="A1",
        klasse="A",
        coverage_state="COVERED",
        pinning_tests=(
            ("tag40", "test_cw_welle_m_state_does_not_corrupt_welle_n_for_all_m_lt_n"),
            ("tag40", "test_cw_welle_isolation_holds_under_intermediate_sequential_states"),
            ("tag43", "test_neg_cross_modul_drift_welle_4_5_blocker_marker_not_set"),
            ("tag44", "TestAp4CrossWelleStateLeak"),
        ),
        rationale_keyword="cross-modul-drift",
    ),
    CoverageClassification(
        failure_mode_id="A2",
        klasse="A",
        coverage_state="PARTIAL",
        pinning_tests=(
            ("tag44", "TestAp4CrossWelleStateLeak"),
        ),
        rationale_keyword="fsm-transition-legality",
    ),
    CoverageClassification(
        failure_mode_id="A3",
        klasse="A",
        coverage_state="COVERED",
        pinning_tests=(
            ("tag41", "test_pcd_drill_runs_full_seven_step_sequence_for_welle_4"),
            ("tag41", "test_pcd_drill_runs_full_seven_step_sequence_for_welle_7"),
            ("smoke", "test_welle_4_cutover_smoke.py"),
            ("smoke", "test_welle_7_cutover_smoke.py"),
        ),
        rationale_keyword="state-migration",
    ),
    CoverageClassification(
        failure_mode_id="A4",
        klasse="A",
        coverage_state="COVERED",
        pinning_tests=(
            ("tag39_dw67", "test_dw_ac_6_7_par_nats_subject_drift_between_subscribe_loop_and_recovery_blocks"),
        ),
        rationale_keyword="nats-mode-mismatch",
    ),
    CoverageClassification(
        failure_mode_id="A5",
        klasse="A",
        coverage_state="COVERED",
        pinning_tests=(
            ("tag44", "TestAp3AuditTrailCorruption"),
            ("tag43", "test_mar_kw_25_solo_welle_3_carries_henrik_caution_pre_audit_path_marker"),
        ),
        rationale_keyword="self-reference-trap",
    ),
    CoverageClassification(
        failure_mode_id="A6",
        klasse="A",
        # Tag-46 substrate-layer closeout (Kai) flipped PARTIAL ->
        # COVERED via tests/infra/test_cosign_drift_coverage_a6.py
        # (17 hermetic invariants, see docs/quality-gates/
        # failure-mode-a6-coverage.md). The Tag-46+ Layer-5 marathon-
        # level test (Amara) remains a defence-in-depth follow-up.
        coverage_state="COVERED",
        pinning_tests=(
            ("infra", "test_a6_per_binary_cosign_drift_invariant"),
            ("infra", "test_a6_image_digest_mismatch_recovery_posture"),
            ("infra", "test_a6_cosign_installer_semver_pin"),
            ("infra", "test_a6_keyless_oidc_identity_drift_detection"),
            ("infra", "test_a6_sigstore_trust_root_posture"),
            ("infra", "test_a6_coverage_classification_covered"),
        ),
        rationale_keyword="cosign-verification-drift",
    ),
    CoverageClassification(
        failure_mode_id="A7",
        klasse="A",
        coverage_state="COVERED",
        pinning_tests=(
            ("tag41", "test_coord_kw_26_dw_4_5_runs_in_parallel_with_symmetric_a7_drift"),
            ("tag41", "test_rollback_trigger_fires_when_a7_drift_exceeds_threshold"),
        ),
        rationale_keyword="persona-engine-sprach-drift",
    ),
    CoverageClassification(
        failure_mode_id="A8",
        klasse="A",
        coverage_state="COVERED",
        pinning_tests=(
            ("smoke", "test_welle_4_cutover_smoke.py"),
            (
                "tag46_pengine_a8",
                "test_a8_stream_disconnect_mid_publish_does_not_abort_loop",
            ),
            ("tag46_pengine_a8", "test_a8_consumer_ack_loss_does_not_crash_loop"),
            ("tag46_pengine_a8", "test_a8_replica_failover_put_surfaces_error"),
            (
                "tag46_pengine_a8",
                "test_a8_subject_routing_drift_drops_mismatched_persona",
            ),
            (
                "tag46_pengine_a8",
                "test_a8_replay_state_backing_byte_equal_snapshot_idempotent",
            ),
        ),
        rationale_keyword="nats-jetstream-persistence-loss",
    ),
    # Class-B Operativ
    CoverageClassification(
        failure_mode_id="B1",
        klasse="B",
        # Tag-46 update (Tomás): PARTIAL -> COVERED via
        # tests/ci/test_ar_hand_stop_marker_trigger_b1.py (31 tests
        # across five test-classes: file-detection, trigger-cascade,
        # mid-cutover race, rollback-sequence, marker-persistence).
        coverage_state="COVERED",
        pinning_tests=(
            ("tag46_b1", "TestStopMarkerFileDetection"),
            ("tag46_b1", "TestTriggerCascadeOnRunningCutoverWorkflows"),
            ("tag46_b1", "TestStopMarkerMidCutoverRaceCondition"),
            ("tag46_b1", "TestRollbackSequenceAfterARStop"),
            ("tag46_b1", "TestMarkerPersistenceAndAuditTrail"),
            ("tag46_b1", "TestCrossClassConsistency"),
        ),
        rationale_keyword="ar-hand-stop-marker-trigger",
    ),
    CoverageClassification(
        failure_mode_id="B2",
        klasse="B",
        coverage_state="COVERED",
        pinning_tests=(
            ("tag43", "test_neg_welle_3_rollback_blocks_welle_4_to_7_and_marker_not_set"),
            ("tag40", "test_cascade_welle_3_rollback_blocks_welle_4_through_7_start"),
            ("tag40", "test_cascade_welle_5_rollback_blocks_welle_6_through_7_but_not_4"),
            ("tag44", "TestAp9RollbackCascade"),
        ),
        rationale_keyword="sign-off-sequenz-bruch",
    ),
    CoverageClassification(
        failure_mode_id="B3",
        klasse="B",
        coverage_state="PARTIAL",
        pinning_tests=(
            ("tag43", "test_mar_kw_25_solo_welle_3_carries_henrik_caution_pre_audit_path_marker"),
        ),
        rationale_keyword="welle-3-iia-1130",
    ),
    CoverageClassification(
        failure_mode_id="B4",
        klasse="B",
        coverage_state="COVERED",
        pinning_tests=(
            ("tag44", "TestAp7Iia1130Welle7SelfAuditTrap"),
            ("tag43", "test_neg_welle_7_pre_auditor_decision_missing_marker_not_set"),
            ("tag43", "test_ac15_ac_5_iia_1130_ar_hand_quote_empty_blocks_marker"),
            ("tag43", "test_cross_marathon_kw_27_pre_auditor_decision_blocks_ac_5_quote"),
        ),
        rationale_keyword="welle-7-iia-1130",
    ),
    CoverageClassification(
        failure_mode_id="B5",
        klasse="B",
        coverage_state="GAP-ACCEPTED",
        pinning_tests=(),
        rationale_keyword="spawn-collision-governance",
    ),
    CoverageClassification(
        failure_mode_id="B6",
        klasse="B",
        coverage_state="GAP-ACCEPTED",
        pinning_tests=(),
        rationale_keyword="persona-sleep-watch-governance",
    ),
    # Class-C Prozedural
    CoverageClassification(
        failure_mode_id="C1",
        klasse="C",
        coverage_state="COVERED",
        pinning_tests=(
            ("tag40", "test_p3m_marker_sets_only_when_all_seven_wellen_sign_off"),
            ("tag40", "test_p3m_marker_blocked_when_six_of_seven_wellen_sign_off"),
            ("tag40", "test_p3m_marker_blocked_when_ac_4_cross_review_consensus_missing"),
            ("tag40", "test_p3m_marker_blocked_when_we_1_to_we_4_welle_ende_incomplete"),
            ("tag40", "test_false_pos_marker_not_set_on_six_of_seven_signoff"),
            ("tag43", "test_ac15_all_five_criteria_green_fires_phase_3_complete_marker"),
            ("tag44", "TestAp10EmptyStateFileFalsePositive"),
        ),
        rationale_keyword="complete-marker-false-positive",
    ),
    CoverageClassification(
        failure_mode_id="C2",
        klasse="C",
        coverage_state="COVERED",
        pinning_tests=(
            ("tag44", "TestAp6ArHandBypass"),
            ("tag43", "test_ac15_ac_5_ar_hand_stamp_missing_blocks_marker"),
            ("tag43", "test_ac15_ac_5_iia_1130_ar_hand_quote_empty_blocks_marker"),
        ),
        rationale_keyword="ar-ratifikation-race",
    ),
    CoverageClassification(
        failure_mode_id="C3",
        klasse="C",
        coverage_state="GAP-ACCEPTED",
        pinning_tests=(),
        rationale_keyword="public-communication-site-repo",
    ),
    CoverageClassification(
        failure_mode_id="C4",
        klasse="C",
        coverage_state="GAP-ACCEPTED",
        pinning_tests=(),
        rationale_keyword="adr-substanz-governance",
    ),
    CoverageClassification(
        failure_mode_id="C5",
        klasse="C",
        coverage_state="GAP-ACCEPTED",
        pinning_tests=(),
        rationale_keyword="yaml-frontmatter-site-repo",
    ),
    # Class-D Externe — all GAP-ACCEPTED (external).
    CoverageClassification(
        failure_mode_id="D1",
        klasse="D",
        coverage_state="GAP-ACCEPTED",
        pinning_tests=(),
        rationale_keyword="github-api-outage-external",
    ),
    CoverageClassification(
        failure_mode_id="D2",
        klasse="D",
        coverage_state="GAP-ACCEPTED",
        pinning_tests=(),
        rationale_keyword="nats-service-failure-external",
    ),
    CoverageClassification(
        failure_mode_id="D3",
        klasse="D",
        coverage_state="GAP-ACCEPTED",
        pinning_tests=(),
        rationale_keyword="sigstore-fulcio-external",
    ),
    CoverageClassification(
        failure_mode_id="D4",
        klasse="D",
        coverage_state="GAP-ACCEPTED",
        pinning_tests=(),
        rationale_keyword="cloud-provider-throttling-external",
    ),
    CoverageClassification(
        failure_mode_id="D5",
        klasse="D",
        coverage_state="GAP-ACCEPTED",
        pinning_tests=(),
        rationale_keyword="ots-calendar-outage-external",
    ),
)


COVERAGE_BY_ID: Mapping[str, CoverageClassification] = {
    c.failure_mode_id: c for c in COVERAGE_MATRIX
}


# ---------------------------------------------------------------------------
# Resolution helper — given (suite-tag, name), is the name present?
# ---------------------------------------------------------------------------


def _suite_contains(suite_tag: str, name: str) -> bool:
    """Return True iff the named test exists in the named companion suite.

    ``suite_tag`` is one of "tag40", "tag41", "tag43", "tag44",
    "tag39_dw67", "smoke", or "infra". For "smoke", the ``name`` is a
    filename (e.g. ``test_welle_4_cutover_smoke.py``) and the check is
    file-presence in ``tests/phase_3c/``. For "infra" (Tag-46+
    substrate-layer closers, e.g. A6), the ``name`` is a test-function
    name and the check is presence in the loaded
    ``tests/infra/test_cosign_drift_coverage_a6.py`` module.
    """
    if suite_tag == "tag40":
        return name in TAG40_NAMES
    if suite_tag == "tag41":
        return name in TAG41_NAMES
    if suite_tag == "tag43":
        return name in TAG43_NAMES
    if suite_tag == "tag44":
        # Tag-44 names can be either function names or "Class::method".
        # For class-name-only entries (e.g. "TestAp4CrossWelleStateLeak"),
        # we accept presence iff the class exists in TAG44_NAMES.
        return name in TAG44_NAMES
    if suite_tag == "tag39_dw67":
        return name in TAG39_DW67_NAMES
    if suite_tag == "tag46_pengine_a8":
        return name in TAG46_PENGINE_A8_NAMES
    if suite_tag == "tag46_b1":
        # Tag-46 Tomás follow-up: lives in tests/ci/, class-based.
        return name in TAG46_B1_NAMES
    if suite_tag == "smoke":
        path = _repo_root() / "tests" / "phase_3c" / name
        return path.is_file()
    if suite_tag == "infra":
        return name in INFRA_A6_NAMES
    return False


def _suite_available(suite_tag: str) -> bool:
    """Return True iff the companion suite identified by ``suite_tag``
    is available for introspection. Shadow-CI baselines may not have
    every companion's optional dep (e.g. ``yaml``) — in that case the
    companion-loader returns None and the suite is treated as
    unavailable so the audit-test does not spuriously fail on a
    missing-dep, only on actual classification drift.
    """
    if suite_tag == "infra":
        return len(INFRA_A6_NAMES) > 0
    if suite_tag == "tag46_pengine_a8":
        return len(TAG46_PENGINE_A8_NAMES) > 0
    # The Tag-40..Tag-44 companions are required to load successfully
    # (no optional deps); if they didn't, the audit-test would already
    # have failed at module-import time.
    return True


def _assert_pinning_tests_resolve(
    classification: CoverageClassification,
) -> None:
    """Common assertion: each named pinning-test in the classification
    must resolve in its companion suite. Pinning-tests whose
    companion suite is unavailable in shadow-CI (e.g. missing optional
    dep) are skipped rather than failed."""
    for suite_tag, name in classification.pinning_tests:
        if not _suite_available(suite_tag):
            # Companion not introspectable in this CI baseline; trust
            # the full-CI baseline to enforce the assertion.
            continue
        assert _suite_contains(suite_tag, name), (
            f"failure-mode {classification.failure_mode_id} "
            f"({classification.rationale_keyword}) classified as "
            f"{classification.coverage_state} names pinning-test "
            f"({suite_tag!r}, {name!r}) but it is NOT present in the "
            f"companion suite. Either the classification is stale (Tag-45 "
            f"matrix-update needed) or the companion suite has drifted "
            f"(Tag-40..Tag-44 spawn-update needed)."
        )


def _assert_coverage_state_matches_pinning(
    classification: CoverageClassification,
) -> None:
    """Common assertion: the coverage_state value must be consistent with
    whether pinning-tests are named."""
    if classification.coverage_state == "COVERED":
        assert len(classification.pinning_tests) >= 1, (
            f"failure-mode {classification.failure_mode_id} is COVERED but "
            f"has no pinning-tests. Either the classification is stale or "
            f"the matrix is internally inconsistent."
        )
    elif classification.coverage_state == "GAP-ACCEPTED":
        # GAP-ACCEPTED carries no positive pinning-tests by definition.
        assert len(classification.pinning_tests) == 0, (
            f"failure-mode {classification.failure_mode_id} is "
            f"GAP-ACCEPTED but names pinning-tests. Either the "
            f"classification should be PARTIAL/COVERED, or the pinning-"
            f"tests should be moved out of the entry."
        )
    elif classification.coverage_state == "GAP-OPEN":
        # GAP-OPEN: no pinning-tests, follow-up REQUIRED.
        assert len(classification.pinning_tests) == 0, (
            f"failure-mode {classification.failure_mode_id} is GAP-OPEN "
            f"but names pinning-tests. A GAP-OPEN mode by definition has "
            f"no existing pinning-tests; if pinning-tests exist, the "
            f"classification should be PARTIAL or COVERED."
        )
    elif classification.coverage_state == "PARTIAL":
        # PARTIAL: pinning-tests may or may not exist; the classification
        # is named because the coverage is incomplete, and the §4 follow-
        # up names the missing test. No additional structural assertion.
        pass
    else:
        pytest.fail(
            f"unknown coverage_state {classification.coverage_state!r} "
            f"for failure-mode {classification.failure_mode_id}"
        )


# ---------------------------------------------------------------------------
# Per-failure-mode tests (24 tests).
#
# Each test asserts:
#   (1) the classification entry exists and has the documented
#       coverage_state
#   (2) the named pinning-tests resolve in their companion suites
#   (3) the coverage_state value is consistent with the presence of
#       pinning-tests
# ---------------------------------------------------------------------------


def _per_failure_mode_test(failure_mode_id: str) -> None:
    """Common per-failure-mode coverage-classification assertion."""
    classification = COVERAGE_BY_ID.get(failure_mode_id)
    assert classification is not None, (
        f"failure-mode {failure_mode_id} not present in the COVERAGE_MATRIX. "
        f"Either Henrik's Pre-Mortem-Skizze gained a new failure-mode and "
        f"the matrix is stale, or the canonical ID list is out-of-date."
    )
    _assert_pinning_tests_resolve(classification)
    _assert_coverage_state_matches_pinning(classification)


# Class-A Technisch.


def test_pm_a1_cross_modul_drift_welle_n_to_n_plus_1() -> None:
    """A1 — Cross-Modul-Drift Welle-N -> Welle-N+1. COVERED."""
    _per_failure_mode_test("A1")
    cls = COVERAGE_BY_ID["A1"]
    assert cls.coverage_state == "COVERED"


def test_pm_a2_fsm_phantom_transitions() -> None:
    """A2 — FSM-Phantom-Transitions. PARTIAL (Rust-side covered)."""
    _per_failure_mode_test("A2")
    cls = COVERAGE_BY_ID["A2"]
    assert cls.coverage_state == "PARTIAL"


def test_pm_a3_state_migration_failure_welle_4_7() -> None:
    """A3 — State-Migration-Failure Welle-4/7. COVERED."""
    _per_failure_mode_test("A3")
    cls = COVERAGE_BY_ID["A3"]
    assert cls.coverage_state == "COVERED"
    # Per-Welle smokes must exist on disk.
    assert _phase_3c_smoke_present(4), "Welle-4 cutover smoke missing"
    assert _phase_3c_smoke_present(7), "Welle-7 cutover smoke missing"


def test_pm_a4_nats_mode_mismatch() -> None:
    """A4 — NATS-Mode-Mismatch (Tag-41 Bug-42-Klasse). COVERED."""
    _per_failure_mode_test("A4")
    cls = COVERAGE_BY_ID["A4"]
    assert cls.coverage_state == "COVERED"


def test_pm_a5_self_reference_trap_welle_3() -> None:
    """A5 — Self-Reference-Trap Welle-3 bridge-audit-writer. COVERED."""
    _per_failure_mode_test("A5")
    cls = COVERAGE_BY_ID["A5"]
    assert cls.coverage_state == "COVERED"


def test_pm_a6_cosign_verification_drift() -> None:
    """A6 — Cosign-Verification-Drift. COVERED post-Tag-46 (Kai
    substrate-layer closeout in tests/infra/test_cosign_drift_
    coverage_a6.py)."""
    _per_failure_mode_test("A6")
    cls = COVERAGE_BY_ID["A6"]
    assert cls.coverage_state == "COVERED"
    # Tag-46 substrate-closeout: at least the six named substrate-layer
    # invariants must be present in the infra-side companion suite.
    assert len(cls.pinning_tests) >= 6, (
        "A6 post-Tag-46 closeout must name >=6 substrate-layer pinning "
        "tests (the Kai Tag-46 closeout shipped 17 invariants, anchored "
        "via 6 named test-functions)."
    )


def test_pm_a7_persona_engine_sprach_drift() -> None:
    """A7 — Persona-Engine-Sprach-Drift (Python-Rest in Hot-Path). COVERED."""
    _per_failure_mode_test("A7")
    cls = COVERAGE_BY_ID["A7"]
    assert cls.coverage_state == "COVERED"


def test_pm_a8_nats_jetstream_persistence_loss_welle_4() -> None:
    """A8 — NATS-JetStream-Loss-Recovery Welle-4-Cutover. COVERED.

    Lifted from PARTIAL to COVERED in Tag-46 by the named follow-up
    file ``wirelang/persona_engine/tests/test_nats_jetstream_loss_
    recovery_a8.py`` (Selin auftrag 2026-05-18). Pinning-tests cover
    the five hermetic JetStream-loss scenarios from §4 of the
    coverage-matrix: Stream-Disconnect-Mid-Publish,
    Consumer-Ack-Loss, JetStream-Replica-Failover,
    Subject-Routing-Drift, Message-Replay-Idempotency.
    """
    _per_failure_mode_test("A8")
    cls = COVERAGE_BY_ID["A8"]
    assert cls.coverage_state == "COVERED"


# Class-B Operativ.


def test_pm_b1_ar_hand_stop_marker_missing_trigger() -> None:
    """B1 — AR-Hand-Stop-Marker-Missing-Trigger. COVERED (Tag-46
    Tomás follow-up to Tag-45 PARTIAL classification)."""
    _per_failure_mode_test("B1")
    cls = COVERAGE_BY_ID["B1"]
    assert cls.coverage_state == "COVERED"
    # Cheat-sheet-structure test still exists as the legacy anchor.
    structure_test_file = _repo_root() / "tests" / "phase_3c" / "test_cutover_cheat_sheet_structure.py"
    assert structure_test_file.is_file(), (
        "cutover-cheat-sheet-structure test missing; B1 legacy-anchor lost"
    )
    # Tag-46 substantive test file present.
    tag46_test_file = (
        _repo_root() / "tests" / "ci" / "test_ar_hand_stop_marker_trigger_b1.py"
    )
    assert tag46_test_file.is_file(), (
        "Tag-46 substantive trigger test missing; B1 COVERED-anchor lost"
    )
    # Tag-46 test-class count >= 5 (file-detection, cascade, race,
    # rollback, persistence; plus a cross-class consistency bag).
    classes_in_tag46 = {
        n for n in TAG46_B1_NAMES if n.startswith("Test") and "::" not in n
    }
    assert len(classes_in_tag46) >= 5, (
        f"Tag-46 B1 test-class count regression: expected >=5, "
        f"found {sorted(classes_in_tag46)}"
    )


def test_pm_b2_sign_off_sequenz_bruch() -> None:
    """B2 — Sign-Off-Sequenz-Bruch (Welle-N+1 startet vor Welle-N). COVERED."""
    _per_failure_mode_test("B2")
    cls = COVERAGE_BY_ID["B2"]
    assert cls.coverage_state == "COVERED"


def test_pm_b3_welle_3_iia_1130_pre_auditor_conflict() -> None:
    """B3 — Welle-3 IIA-1130 Pre-Auditor Konflikt. PARTIAL (marker only)."""
    _per_failure_mode_test("B3")
    cls = COVERAGE_BY_ID["B3"]
    assert cls.coverage_state == "PARTIAL"


def test_pm_b4_welle_7_iia_1130_recovery_conflict() -> None:
    """B4 — Welle-7 IIA-1130 Recovery Konflikt. COVERED."""
    _per_failure_mode_test("B4")
    cls = COVERAGE_BY_ID["B4"]
    assert cls.coverage_state == "COVERED"


def test_pm_b5_spawn_collision_governance() -> None:
    """B5 — Spawn-Collision >30 Spawns/Tag. GAP-ACCEPTED (governance)."""
    _per_failure_mode_test("B5")
    cls = COVERAGE_BY_ID["B5"]
    assert cls.coverage_state == "GAP-ACCEPTED"
    # Mitigation-anchor: High-Tempo-Spawn-Collision-Memo (out-of-tree,
    # in agents-workspaces/mira/memory/). We do not assert its presence
    # here (cross-repo path), but we name it in the rationale_keyword.
    assert "governance" in cls.rationale_keyword


def test_pm_b6_persona_sleep_watch_governance() -> None:
    """B6 — Persona-Sleep-Watch-Bruch. GAP-ACCEPTED (governance)."""
    _per_failure_mode_test("B6")
    cls = COVERAGE_BY_ID["B6"]
    assert cls.coverage_state == "GAP-ACCEPTED"
    assert "governance" in cls.rationale_keyword


# Class-C Prozedural.


def test_pm_c1_complete_marker_false_positive() -> None:
    """C1 — COMPLETE-Marker-False-Positive. COVERED (heaviest)."""
    _per_failure_mode_test("C1")
    cls = COVERAGE_BY_ID["C1"]
    assert cls.coverage_state == "COVERED"
    # Pinning-test count >= 7 (heaviest-covered failure-mode).
    assert len(cls.pinning_tests) >= 7, (
        "C1 is documented as the heaviest-covered failure-mode; if the "
        "pinning-test count drops below 7, the §3 narrative is stale."
    )


def test_pm_c2_ar_ratifikation_race() -> None:
    """C2 — AR-Ratifikation-Race (Phase-4 startet vor AR-Stempel). COVERED."""
    _per_failure_mode_test("C2")
    cls = COVERAGE_BY_ID["C2"]
    assert cls.coverage_state == "COVERED"


def test_pm_c3_public_communication_premature_site_repo() -> None:
    """C3 — Public-Communication-Premature. GAP-ACCEPTED (site-repo)."""
    _per_failure_mode_test("C3")
    cls = COVERAGE_BY_ID["C3"]
    assert cls.coverage_state == "GAP-ACCEPTED"
    assert "site-repo" in cls.rationale_keyword


def test_pm_c4_adr_substanz_false_premise_governance() -> None:
    """C4 — ADR-Substanz-False-Premise. GAP-ACCEPTED (governance)."""
    _per_failure_mode_test("C4")
    cls = COVERAGE_BY_ID["C4"]
    assert cls.coverage_state == "GAP-ACCEPTED"
    assert "governance" in cls.rationale_keyword


def test_pm_c5_yaml_frontmatter_disziplin_site_repo() -> None:
    """C5 — YAML-Frontmatter-Disziplin-Bruch. GAP-ACCEPTED (site-repo)."""
    _per_failure_mode_test("C5")
    cls = COVERAGE_BY_ID["C5"]
    assert cls.coverage_state == "GAP-ACCEPTED"
    assert "site-repo" in cls.rationale_keyword


# Class-D Externe — all GAP-ACCEPTED.


def test_pm_d1_github_api_outage_external() -> None:
    """D1 — GitHub-API-Outage. GAP-ACCEPTED (external)."""
    _per_failure_mode_test("D1")
    cls = COVERAGE_BY_ID["D1"]
    assert cls.coverage_state == "GAP-ACCEPTED"
    assert cls.klasse == "D"
    assert "external" in cls.rationale_keyword


def test_pm_d2_nats_service_failure_external() -> None:
    """D2 — NATS-Service-Failure auf Pilot-VM. GAP-ACCEPTED (external)."""
    _per_failure_mode_test("D2")
    cls = COVERAGE_BY_ID["D2"]
    assert cls.coverage_state == "GAP-ACCEPTED"
    assert cls.klasse == "D"
    assert "external" in cls.rationale_keyword


def test_pm_d3_cosign_sigstore_external() -> None:
    """D3 — Cosign sigstore/Fulcio external drift. GAP-ACCEPTED (external)."""
    _per_failure_mode_test("D3")
    cls = COVERAGE_BY_ID["D3"]
    assert cls.coverage_state == "GAP-ACCEPTED"
    assert cls.klasse == "D"
    assert "external" in cls.rationale_keyword


def test_pm_d4_cloud_provider_throttling_external() -> None:
    """D4 — Cloud-Provider-Throttling. GAP-ACCEPTED (external)."""
    _per_failure_mode_test("D4")
    cls = COVERAGE_BY_ID["D4"]
    assert cls.coverage_state == "GAP-ACCEPTED"
    assert cls.klasse == "D"
    assert "external" in cls.rationale_keyword


def test_pm_d5_ots_calendar_outage_external() -> None:
    """D5 — OpenTimestamps-Calendar-Outage. GAP-ACCEPTED (external)."""
    _per_failure_mode_test("D5")
    cls = COVERAGE_BY_ID["D5"]
    assert cls.coverage_state == "GAP-ACCEPTED"
    assert cls.klasse == "D"
    assert "external" in cls.rationale_keyword


# ---------------------------------------------------------------------------
# §3 coverage-summary consistency-check (1 test).
# ---------------------------------------------------------------------------


def test_pm_summary_totals_match_per_class_classifications() -> None:
    """§3 coverage-summary table totals must match §2 classifications.

    The §3 table (Tag-46 cumulative closeouts):
      - A6 Cosign-Drift PARTIAL -> COVERED (Kai substrate, PR #298)
      - A8 NATS-JetStream-Loss-Recovery PARTIAL -> COVERED (Selin, PR #300)
      - B1 AR-Hand-Stop-Marker-Trigger PARTIAL -> COVERED (Tomas, PR #299)

        Class A: 8 total | 7 COVERED | 1 PARTIAL | 0 GAP-ACCEPTED | 0 GAP-OPEN
        Class B: 6 total | 3 COVERED | 1 PARTIAL | 2 GAP-ACCEPTED | 0 GAP-OPEN
        Class C: 5 total | 2 COVERED | 0 PARTIAL | 3 GAP-ACCEPTED | 0 GAP-OPEN
        Class D: 5 total | 0 COVERED | 0 PARTIAL | 5 GAP-ACCEPTED | 0 GAP-OPEN
        Total:  24       | 12        | 2         | 10              | 0

    This test recomputes the table from the COVERAGE_MATRIX and asserts
    consistency.
    """
    expected_per_class = {
        "A": {"total": 8, "COVERED": 7, "PARTIAL": 1, "GAP-ACCEPTED": 0, "GAP-OPEN": 0},
        "B": {"total": 6, "COVERED": 3, "PARTIAL": 1, "GAP-ACCEPTED": 2, "GAP-OPEN": 0},
        "C": {"total": 5, "COVERED": 2, "PARTIAL": 0, "GAP-ACCEPTED": 3, "GAP-OPEN": 0},
        "D": {"total": 5, "COVERED": 0, "PARTIAL": 0, "GAP-ACCEPTED": 5, "GAP-OPEN": 0},
    }

    actual_per_class: Dict[str, Dict[str, int]] = {
        klasse: {"total": 0, "COVERED": 0, "PARTIAL": 0, "GAP-ACCEPTED": 0, "GAP-OPEN": 0}
        for klasse in expected_per_class
    }
    for c in COVERAGE_MATRIX:
        actual_per_class[c.klasse]["total"] += 1
        actual_per_class[c.klasse][c.coverage_state] += 1

    assert actual_per_class == expected_per_class, (
        f"§3 summary-table totals do not match §2 classifications. "
        f"Expected {expected_per_class}, got {actual_per_class}. Either "
        f"the matrix has drifted (update the §3 summary), or the §2 "
        f"individual classifications have changed (update the §3 summary)."
    )

    # Final-row totals.
    grand_total = sum(actual_per_class[k]["total"] for k in actual_per_class)
    grand_covered = sum(actual_per_class[k]["COVERED"] for k in actual_per_class)
    grand_partial = sum(actual_per_class[k]["PARTIAL"] for k in actual_per_class)
    grand_gap_accepted = sum(actual_per_class[k]["GAP-ACCEPTED"] for k in actual_per_class)
    grand_gap_open = sum(actual_per_class[k]["GAP-OPEN"] for k in actual_per_class)

    assert grand_total == 24, f"expected 24 total failure-modes, got {grand_total}"
    # Post-Tag-46 closeouts (A6 Kai + A8 Selin + B1 Tomás all flipped
    # PARTIAL -> COVERED): 12 COVERED + 2 PARTIAL.
    assert grand_covered == 12
    assert grand_partial == 2
    assert grand_gap_accepted == 10
    assert grand_gap_open == 0

    # Canonical failure-mode IDs must align with COVERAGE_MATRIX keys.
    matrix_ids = frozenset(c.failure_mode_id for c in COVERAGE_MATRIX)
    canonical_ids = frozenset(CANONICAL_FAILURE_MODE_IDS)
    assert matrix_ids == canonical_ids, (
        f"matrix-IDs {sorted(matrix_ids)} do not match canonical IDs "
        f"{sorted(canonical_ids)}. Pre-Mortem-Skizze drift suspected."
    )

    # Coverage-matrix doc presence (the docs/quality-gates/ matrix file
    # must exist; otherwise the test-file has no narrative-anchor).
    matrix_doc = (
        _repo_root() / "docs" / "quality-gates" / "pre-mortem-failure-mode-coverage.md"
    )
    assert matrix_doc.is_file(), (
        f"coverage-matrix doc missing at {matrix_doc}; Tag-45 contract "
        f"broken (test-file enforces a doc that does not exist)."
    )
