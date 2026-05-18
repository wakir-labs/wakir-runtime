# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Phase-3-Marathon-Schluss-Acceptance-Live-Drill — end-to-end sequenced
cutover-marathon over the four-week ADR-0066 cadence (KW-24 -> KW-27),
chaining the per-Welle Cutover-Mittwoch drills, the per-KW sign-off
aggregations, the inter-KW quiet-windows, and the Phase-3-COMPLETE-
marker trigger into a single hermetic acceptance suite — plus the
Phase-3-Marathon-Bilanz-Trigger that fires once the marker is set.

Auftrag-Anker
-------------

- Tag-43 Amara Auftrag — Phase-3-Marathon-Schluss-Acceptance-Live-Drill
  (Continuous-Mode, Aufsichtsrat 2026-05-18). Where the Tag-40
  ``test_phase_3_final_regression.py`` pins the *aggregate* marker
  state-machine contract and the Tag-41
  ``test_cutover_day_e2e_drill.py`` pins the *per-day* Cutover-
  Mittwoch walkthrough, this Tag-43 file pins the *end-to-end
  marathon-sequence*: replaying the entire KW-24 -> KW-27 cadence
  in one drill, threading the per-Welle drill outputs into per-KW
  sign-off bundles, threading the per-KW bundles into the Phase-3-
  COMPLETE-marker AC-1..AC-5 conjunction (per
  ``.github/workflows/phase-3-complete-marker.yml``), and threading
  the green marker into the Phase-3-Marathon-Bilanz-Trigger (Noa-
  pendant for Tag-43 Bilanz-Generator).
- ADR-0066 §Beschluss — KW-24 Doppel-Welle-1+2 (parallel),
  KW-25 Solo-Welle-3 (Henrik-Caution, Pre-Audit-Path),
  KW-26 Doppel-Welle-4+5 (symmetric A7-Drift),
  KW-27 Doppel-Welle-6+7 (Schluss-Acceptance + IIA-1130-Welle-7-
  Pre-Auditor-Decision-Gate).
- ADR-0065 §Verifikations-Plan — per-Welle AC-1..AC-5 + Welle-Ende
  WE-1..WE-4. Each Welle must close AC-1..AC-5 before its sign-off
  is admissible into the per-KW bundle.
- Phase-3-COMPLETE-Marker-Workflow (``.github/workflows/phase-3-
  complete-marker.yml``) — the five conjunctive AC-1..AC-5
  acceptance criteria the workflow's emit-step is gated on:

  * AC-1: seven Welle-Sign-Offs in {green, yellow_henrik_hand_approval}
  * AC-2: phase-3c-welle-{1..7}-validation.yml all success on main
  * AC-3: phase-3{a,b,c}-closure.json present (3a=15, 3b=9, 3c=7)
  * AC-4: Henrik R-A1..R-A6 ratification (state/henrik-phase-3-
    complete-ratification.json with aggregate_verdict="ratified")
  * AC-5: AR-Hand stamp (state/ar-hand-phase-3-complete-stamp.json
    with ar_hand_ratification=True and non-empty ar_hand_quote;
    IIA-1130 independence anchor)

- ``docs/quality-gates/phase-3-marathon-schluss-acceptance.md``
  (Amara, this PR) — the Phase-3-Marathon-Schluss-Acceptance
  Definition-of-Done document this test-file enforces.

Cross-spawn-Konsistenz (Tag-43)
-------------------------------

- Companion (per-day walkthrough): ``test_cutover_day_e2e_drill.py``
  (Tag-41). This Tag-43 file consumes the per-day ``DrillSlot``
  records (re-imported via the Cutover-Day module) when assembling
  the marathon-sequence; one Cutover-Mittwoch slot is one node in
  the marathon-sequence DAG.
- Companion (marker state-machine): ``test_phase_3_final_regression.py``
  (Tag-40). This Tag-43 file uses the
  :class:`Phase3CompleteMarkerStateMachine` re-imported from the
  Tag-40 module as the marker-oracle once the marathon-sequence
  collapses to the seven sign-off-markers + WE-1..WE-4 gates.
- Companion (Welle-6+7 acceptance): ``test_doppel_welle_6_7_acceptance.py``
  (Tag-39). The IIA-1130 Welle-7-Pre-Auditor-Decision gate this
  file enforces mirrors the Tag-39 §IIA-1130 contract.
- Tag-43 Tomás Phase-3-COMPLETE-Marker-Workflow-Substanz: the AC-1..
  AC-5 gating logic in this file mirrors the workflow's emit-step
  ``if:`` predicate; the marker-fire-event surfaced by this drill is
  the trigger the workflow consumes in production.
- Tag-43 Noa Phase-3-Bilanz-Generator: the Bilanz-Trigger contract
  this file enforces (``BilanzTrigger.fires_on_complete_marker``)
  mirrors the Noa-side input-event schema; pre-Noa-spawn this file
  carries the contract-anchor.
- Tag-43 Henrik Welle-7-Pre-Auditor-Decision Sample (companion
  audit-spec): the ``Welle7PreAuditorDecision`` shape this file
  carries surfaces the AR-Hand-Pre-Auditor-decision artefact Henrik's
  Welle-7-cutover-day audit-sample consumes (IIA-1130 anchor).

Why a separate suite (vs. extending Tag-40 / Tag-41)
----------------------------------------------------

* Tag-40 ``test_phase_3_final_regression.py`` gates the *static*
  marker state-machine: given seven sign-off-records, does the
  marker fire? It does **not** thread the marathon-sequence; it
  treats the seven markers as a flat dictionary.
* Tag-41 ``test_cutover_day_e2e_drill.py`` gates the *per-day*
  Cutover-Mittwoch walkthrough: does one Cutover-Mittwoch produce
  a correctly-shaped sign-off-record? It does **not** thread the
  per-day records into per-KW bundles or the Phase-3-COMPLETE-
  marker AC-1..AC-5 conjunction.
* This Tag-43 suite is the *sequenced end-to-end* glue: replay
  KW-24 -> KW-27 in chronological order, thread per-day records
  into per-KW bundles, thread the bundles into the AC-1..AC-5
  conjunction, fire the marker, fire the Bilanz-Trigger. The
  three suites form the three layers of the Phase-3-Acceptance
  pyramid (marker logic, per-day production, marathon-sequence
  orchestration).

Test budget
-----------

This file carries **27 tests** across seven marathon-axes:

MAR — Marathon-Sequence end-to-end (5 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1.  test_mar_full_marathon_kw_24_through_27_runs_in_chronological_order
2.  test_mar_kw_24_doppel_welle_1_2_runs_in_parallel_with_shared_signoff_iso
3.  test_mar_kw_25_solo_welle_3_carries_henrik_caution_pre_audit_path_marker
4.  test_mar_kw_26_doppel_welle_4_5_carries_symmetric_a7_drift_assertion
5.  test_mar_kw_27_doppel_welle_6_7_carries_iia_1130_pre_auditor_decision_gate

AC15 — Phase-3-COMPLETE AC-1..AC-5 conjunction (5 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

6.  test_ac15_all_five_criteria_green_fires_phase_3_complete_marker
7.  test_ac15_ac_1_six_of_seven_signoffs_blocks_marker
8.  test_ac15_ac_4_henrik_ratification_missing_blocks_marker
9.  test_ac15_ac_5_ar_hand_stamp_missing_blocks_marker
10. test_ac15_ac_5_iia_1130_ar_hand_quote_empty_blocks_marker

NEG — Anti-False-Positive Negative-Tests (5 tests, per Auftrag §2)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

11. test_neg_welle_3_rollback_blocks_welle_4_to_7_and_marker_not_set
12. test_neg_welle_7_pre_auditor_decision_missing_marker_not_set
13. test_neg_cross_modul_drift_welle_4_5_blocker_marker_not_set
14. test_neg_six_of_seven_signoffs_marker_not_set
15. test_neg_kw_26_partial_signoff_in_doppel_welle_marker_not_set

BIL — Phase-3-Marathon-Bilanz-Trigger (3 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

16. test_bil_bilanz_trigger_fires_on_complete_marker_green
17. test_bil_bilanz_trigger_does_not_fire_when_marker_not_set
18. test_bil_bilanz_trigger_payload_carries_kw_24_to_27_marathon_summary

DOC — Documentation contract (2 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

19. test_doc_definition_of_done_file_exists_and_documents_marathon_sequence
20. test_doc_definition_of_done_references_ac_1_to_ac_5_conjunction

CROSS — Cross-suite contract-lock-step (4 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

21. test_cross_marathon_signoff_markers_match_tag_40_marker_state_machine
22. test_cross_marathon_per_kw_bundles_align_with_tag_41_cutover_day_drill_schedule
23. test_cross_marathon_signoff_isos_match_tag_40_marathon_trace_timestamps
24. test_cross_marathon_kw_27_pre_auditor_decision_blocks_ac_5_quote

CONJ — AC-1..AC-5 conjunction truth-table walk (3 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

25. test_conj_only_all_five_green_yields_all_five_green_property
26. test_conj_any_single_failing_criterion_blocks_marker
27. test_conj_failing_criteria_tuple_contains_exactly_the_failing_ids

Vermutungs-Kennzeichnung (P2)
-----------------------------

* The Phase-3-COMPLETE-marker AC-1..AC-5 contract is fixed by the
  Tomás Tag-40 ``.github/workflows/phase-3-complete-marker.yml``
  workflow; this file mirrors the contract surface but does not
  fire the live marker.
* The Bilanz-Trigger schema is a pre-Noa-spawn contract-anchor; the
  Noa Tag-43 Bilanz-Generator will consume the same
  ``BilanzTrigger`` shape when wired up.
* The Welle-7-Pre-Auditor-Decision-Gate is the IIA-1130 anchor per
  Henrik's Tag-39 Welle-6+7-Pre-Audit-Bundle; the Pre-Auditor-
  Decision artefact lives at ``state/welle-7-pre-auditor-
  decision.json`` and the AR-Hand-quote at
  ``state/ar-hand-phase-3-complete-stamp.json``.

License: Apache-2.0 (parity with sibling Phase-3c artefacts).
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import (
    Any,
    Dict,
    FrozenSet,
    List,
    Mapping,
    Optional,
    Tuple,
)

import pytest


# ---------------------------------------------------------------------------
# Companion-module loaders.
#
# We import the Tag-40 final-regression module (marker state-machine + slot
# definitions) and the Tag-41 cutover-day-drill module (per-day walkthrough
# slots + simulator) directly so this file's marathon-sequence stays in
# lock-step with the per-day and per-marker contracts.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the wakir-runtime repo root from this test file."""
    here = Path(__file__).resolve()
    return here.parent.parent.parent


def _load_companion_test_module(filename: str, module_name: str) -> Any:
    """Load a sibling phase_3c test module so we can reuse its constants."""
    test_path = _repo_root() / "tests" / "phase_3c" / filename
    if not test_path.is_file():
        pytest.fail(f"companion test module not found at {test_path}")
    spec = importlib.util.spec_from_file_location(module_name, str(test_path))
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {test_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# Tag-40 final-regression: marker state-machine + ADR-0066-Reihenfolge.
_TAG40 = _load_companion_test_module(
    "test_phase_3_final_regression.py",
    "phase_3c_tag40_final_regression_for_tag43_marathon",
)
# Tag-41 cutover-day: per-day drill slots + simulator.
_TAG41 = _load_companion_test_module(
    "test_cutover_day_e2e_drill.py",
    "phase_3c_tag41_cutover_day_for_tag43_marathon",
)


ADR_0066_REIHENFOLGE = _TAG40.ADR_0066_REIHENFOLGE
ADR_0065_AC_4_PERSONAS: FrozenSet[str] = _TAG40.ADR_0065_AC_4_PERSONAS
WELLE_ENDE_GATES: Tuple[str, ...] = _TAG40.WELLE_ENDE_GATES
MARATHON_TRACE_TIMESTAMPS = _TAG40.MARATHON_TRACE_TIMESTAMPS
SignOffMarker = _TAG40.SignOffMarker
Phase3CompleteMarkerStateMachine = _TAG40.Phase3CompleteMarkerStateMachine
Phase3CompleteMarkerVerdict = _TAG40.Phase3CompleteMarkerVerdict

CUTOVER_DAY_DRILL_SCHEDULE = _TAG41.CUTOVER_DAY_DRILL_SCHEDULE


# ---------------------------------------------------------------------------
# Marathon-Schluss-Acceptance — the Tag-43 contract surface.
#
# This file's contract surface is the *sequence* of four KW-bundles, each
# bundle carrying one or two welle sign-offs, threaded into the Phase-3-
# COMPLETE-marker AC-1..AC-5 conjunction. We model the contract as
# (1) a per-KW-bundle dataclass, (2) a marathon-sequence dataclass, and
# (3) the Phase-3-COMPLETE-AC-1..AC-5 dataclass plus its predicate.
# ---------------------------------------------------------------------------


#: KW -> wellen-numbers binding (mirrors ADR-0066 §Wochen-Plan).
KW_TO_WELLEN: Mapping[int, Tuple[int, ...]] = {
    24: (1, 2),
    25: (3,),
    26: (4, 5),
    27: (6, 7),
}


@dataclass(frozen=True)
class Welle7PreAuditorDecision:
    """The IIA-1130 Pre-Auditor-Decision artefact for Welle-7.

    Per Henrik Tag-39 Welle-6+7-Pre-Audit-Bundle: the Welle-7 cutover-
    day requires an AR-Hand-Pre-Auditor decision before sign-off,
    because Welle-7 sign-off triggers the Phase-3-COMPLETE-marker
    workflow — if Internal Audit ratified marker-setting, that would
    impair IIA-1130 independence. The AR-Hand-Pre-Auditor decision is
    the substitute control.
    """

    decision_present: bool
    decision_id: str = ""
    ar_hand_signature: str = ""
    iia_1130_independence_anchor: str = ""


@dataclass(frozen=True)
class PerKwSignOffBundle:
    """One KW's worth of sign-off-records produced by the marathon drill.

    Each KW emits exactly the welle sign-offs listed in
    :data:`KW_TO_WELLEN`. A bundle is "green" if every welle in the
    KW signed off (``status="signed-off"``), AC-1..AC-5 are green,
    and (KW-27 only) the Welle-7-Pre-Auditor-Decision is present.
    """

    kw: int
    cutover_iso: str
    review_iso: str
    signoff_iso: str
    markers: Tuple[SignOffMarker, ...]
    welle_7_pre_auditor_decision: Optional[Welle7PreAuditorDecision] = None

    @property
    def is_green(self) -> bool:
        if not self.markers:
            return False
        if any(m.status != "signed-off" for m in self.markers):
            return False
        if any(not m.ac_1_5_green for m in self.markers):
            return False
        if any(
            m.ac_4_consensus_personas != ADR_0065_AC_4_PERSONAS
            for m in self.markers
        ):
            return False
        # KW-27 must carry the Welle-7-Pre-Auditor-Decision (IIA-1130).
        if self.kw == 27:
            pad = self.welle_7_pre_auditor_decision
            if pad is None or not pad.decision_present:
                return False
        return True


@dataclass(frozen=True)
class MarathonSequence:
    """The full four-KW marathon-sequence (KW-24 -> KW-27)."""

    bundles: Tuple[PerKwSignOffBundle, ...]

    @property
    def all_markers(self) -> Dict[int, SignOffMarker]:
        out: Dict[int, SignOffMarker] = {}
        for bundle in self.bundles:
            for marker in bundle.markers:
                out[marker.welle_number] = marker
        return out

    @property
    def is_chronological(self) -> bool:
        kws = [b.kw for b in self.bundles]
        isos = [b.cutover_iso for b in self.bundles]
        return kws == sorted(kws) and isos == sorted(isos)


# ---------------------------------------------------------------------------
# Phase-3-COMPLETE AC-1..AC-5 — mirrors the workflow emit-gate predicate.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HenrikRatification:
    """AC-4 anchor: Henrik Tag-39 audit-spec R-A1..R-A6 mitigation.

    Mirrors ``state/henrik-phase-3-complete-ratification.json``.
    """

    aggregate_verdict: str  # "ratified" | "blocked"
    r_a_mitigation_status: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ArHandStamp:
    """AC-5 anchor: AR-Hand final ratification (IIA-1130 independence).

    Mirrors ``state/ar-hand-phase-3-complete-stamp.json``.
    """

    ar_hand_ratification: bool
    ar_hand_quote: str = ""


@dataclass(frozen=True)
class Phase3CompleteAC1To5:
    """The five conjunctive AC-1..AC-5 acceptance criteria the Phase-3-
    COMPLETE-marker-workflow emit-step is gated on (per
    ``.github/workflows/phase-3-complete-marker.yml``)."""

    ac_1_welle_signoff_count: int  # number of green welle sign-offs (0..7)
    ac_2_validation_workflows_all_success: bool  # phase-3c-welle-{1..7}-validation.yml
    ac_3_phase_3abc_closure_present: bool  # phase-3{a,b,c}-closure.json
    ac_4_henrik_ratification: HenrikRatification
    ac_5_ar_hand_stamp: ArHandStamp

    @property
    def ac_1_green(self) -> bool:
        return self.ac_1_welle_signoff_count == 7

    @property
    def ac_2_green(self) -> bool:
        return self.ac_2_validation_workflows_all_success

    @property
    def ac_3_green(self) -> bool:
        return self.ac_3_phase_3abc_closure_present

    @property
    def ac_4_green(self) -> bool:
        return self.ac_4_henrik_ratification.aggregate_verdict == "ratified"

    @property
    def ac_5_green(self) -> bool:
        stamp = self.ac_5_ar_hand_stamp
        return stamp.ar_hand_ratification and bool(stamp.ar_hand_quote.strip())

    @property
    def all_five_green(self) -> bool:
        return (
            self.ac_1_green
            and self.ac_2_green
            and self.ac_3_green
            and self.ac_4_green
            and self.ac_5_green
        )

    def failing_criteria(self) -> Tuple[str, ...]:
        out: List[str] = []
        if not self.ac_1_green:
            out.append("AC-1")
        if not self.ac_2_green:
            out.append("AC-2")
        if not self.ac_3_green:
            out.append("AC-3")
        if not self.ac_4_green:
            out.append("AC-4")
        if not self.ac_5_green:
            out.append("AC-5")
        return tuple(out)


# ---------------------------------------------------------------------------
# Bilanz-Trigger — Tag-43 Noa-pendant Bilanz-Generator input-event.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BilanzTrigger:
    """Phase-3-Marathon-Bilanz-Trigger input-event.

    Fires once the Phase-3-COMPLETE-marker is set green; carries the
    KW-24 -> KW-27 marathon-summary payload the Noa Tag-43 Bilanz-
    Generator consumes. Pre-Noa-spawn this dataclass is the contract
    anchor; post-spawn it remains the canonical input-event schema.
    """

    fires: bool
    marker_iso: str = ""
    kw_24_signoff_iso: str = ""
    kw_25_signoff_iso: str = ""
    kw_26_signoff_iso: str = ""
    kw_27_signoff_iso: str = ""
    welle_signoff_count: int = 0
    blocking_reasons: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Marathon-sequence builders — green happy-path and per-axis perturbations.
# ---------------------------------------------------------------------------


def _build_marker(
    welle_number: int,
    *,
    status: str = "signed-off",
    ac_1_5_green: bool = True,
    consensus: FrozenSet[str] = ADR_0065_AC_4_PERSONAS,
    drift: str = "green",
    cutover_iso: str = "",
    signoff_iso: str = "",
) -> SignOffMarker:
    """Helper that builds a SignOffMarker with green-happy-path defaults."""
    return SignOffMarker(
        welle_number=welle_number,
        status=status,
        ac_1_5_green=ac_1_5_green,
        ac_4_consensus_personas=consensus,
        cross_welle_drift_assert=drift,
        cutover_iso=cutover_iso,
        signoff_iso=signoff_iso,
    )


def _build_green_bundle(kw: int) -> PerKwSignOffBundle:
    """Build one KW's all-green sign-off bundle."""
    kw_row = next(row for row in MARATHON_TRACE_TIMESTAMPS if row[0] == kw)
    welle_numbers = KW_TO_WELLEN[kw]
    markers = tuple(
        _build_marker(
            w,
            cutover_iso=kw_row[1],
            signoff_iso=kw_row[3],
        )
        for w in welle_numbers
    )
    pad: Optional[Welle7PreAuditorDecision] = None
    if kw == 27:
        pad = Welle7PreAuditorDecision(
            decision_present=True,
            decision_id="welle-7-pre-auditor-decision-2026-07-01",
            ar_hand_signature="ar-hand-pre-audit-stamp-kw-27",
            iia_1130_independence_anchor="internal-audit-not-marker-actor",
        )
    return PerKwSignOffBundle(
        kw=kw,
        cutover_iso=kw_row[1],
        review_iso=kw_row[2],
        signoff_iso=kw_row[3],
        markers=markers,
        welle_7_pre_auditor_decision=pad,
    )


def _build_green_marathon() -> MarathonSequence:
    """Build the full KW-24..KW-27 marathon-sequence in the happy-path."""
    return MarathonSequence(
        bundles=tuple(_build_green_bundle(kw) for kw in (24, 25, 26, 27))
    )


def _build_green_ac_1_to_5(marathon: MarathonSequence) -> Phase3CompleteAC1To5:
    """Build the AC-1..AC-5 envelope for an all-green marathon."""
    signoff_count = sum(
        1
        for m in marathon.all_markers.values()
        if m.status == "signed-off"
    )
    return Phase3CompleteAC1To5(
        ac_1_welle_signoff_count=signoff_count,
        ac_2_validation_workflows_all_success=True,
        ac_3_phase_3abc_closure_present=True,
        ac_4_henrik_ratification=HenrikRatification(
            aggregate_verdict="ratified",
            r_a_mitigation_status={
                f"R-A{i}": "mitigated" for i in range(1, 7)
            },
        ),
        ac_5_ar_hand_stamp=ArHandStamp(
            ar_hand_ratification=True,
            ar_hand_quote=(
                "Aufsichtsrat ratifiziert Phase-3-COMPLETE; "
                "Internal Audit setzt den Marker nicht "
                "(IIA-1130-Independence-Anchor)."
            ),
        ),
    )


def _fire_bilanz_trigger(
    marathon: MarathonSequence,
    ac15: Phase3CompleteAC1To5,
    *,
    marker_iso: str = "",
) -> BilanzTrigger:
    """Pure-fn: derive the Bilanz-Trigger from the marathon + AC-1..AC-5.

    Mirrors the Noa Tag-43 Bilanz-Generator input-derivation rule:
    the trigger fires only if AC-1..AC-5 are all green.
    """
    if not ac15.all_five_green:
        return BilanzTrigger(
            fires=False,
            blocking_reasons=ac15.failing_criteria(),
        )

    bundle_by_kw = {b.kw: b for b in marathon.bundles}
    welle_signoff_count = sum(
        1
        for m in marathon.all_markers.values()
        if m.status == "signed-off"
    )
    return BilanzTrigger(
        fires=True,
        marker_iso=marker_iso,
        kw_24_signoff_iso=bundle_by_kw[24].signoff_iso,
        kw_25_signoff_iso=bundle_by_kw[25].signoff_iso,
        kw_26_signoff_iso=bundle_by_kw[26].signoff_iso,
        kw_27_signoff_iso=bundle_by_kw[27].signoff_iso,
        welle_signoff_count=welle_signoff_count,
    )


def _run_marker_state_machine(
    marathon: MarathonSequence,
) -> Phase3CompleteMarkerVerdict:
    """Reduce the marathon-sequence into the Tag-40 marker state-machine."""
    we_gates: Dict[str, bool] = {gate: True for gate in WELLE_ENDE_GATES}
    sm = Phase3CompleteMarkerStateMachine(marathon.all_markers, we_gates)
    return sm.compute_verdict()


# ===========================================================================
# MAR — Marathon-Sequence end-to-end (5 tests)
# ===========================================================================


def test_mar_full_marathon_kw_24_through_27_runs_in_chronological_order() -> None:
    """The marathon-sequence must replay KW-24 -> KW-27 chronologically:
    four KW-bundles in monotonically-increasing cutover-ISO order, each
    KW carrying its ADR-0066 welle-count (KW-24 -> 2, KW-25 -> 1, KW-26 -> 2,
    KW-27 -> 2), seven sign-off-markers total."""
    marathon = _build_green_marathon()

    # Four KW-bundles.
    assert len(marathon.bundles) == 4, (
        f"marathon must carry 4 KW-bundles; got {len(marathon.bundles)}"
    )

    # Chronological.
    assert marathon.is_chronological, (
        "marathon-sequence KW-order or cutover-ISO-order is not chronological"
    )

    # KW-ordering exactly 24/25/26/27.
    kws = [b.kw for b in marathon.bundles]
    assert kws == [24, 25, 26, 27], f"KW-ordering must be 24/25/26/27; got {kws}"

    # Per-KW welle-counts match ADR-0066 cadence.
    welle_counts = [len(b.markers) for b in marathon.bundles]
    assert welle_counts == [2, 1, 2, 2], (
        f"per-KW welle-count must be [2,1,2,2]; got {welle_counts}"
    )

    # Total markers across the marathon: exactly seven, one per welle.
    all_markers = marathon.all_markers
    assert set(all_markers.keys()) == {1, 2, 3, 4, 5, 6, 7}, (
        f"marathon must aggregate exactly the seven welle-markers; "
        f"got {sorted(all_markers.keys())}"
    )


def test_mar_kw_24_doppel_welle_1_2_runs_in_parallel_with_shared_signoff_iso() -> None:
    """KW-24 is a Doppel-Welle slot (Welle-1 + Welle-2 parallel). Both
    markers must share the same cutover-ISO + signoff-ISO (per ADR-0066
    Wochen-Plan: parallel cutover, shared review-Donnerstag, shared
    sign-off-Freitag)."""
    marathon = _build_green_marathon()
    kw_24_bundle = next(b for b in marathon.bundles if b.kw == 24)

    # Two welle in KW-24, partners 1+2.
    welle_numbers = sorted(m.welle_number for m in kw_24_bundle.markers)
    assert welle_numbers == [1, 2], f"KW-24 must be DW-1+2; got {welle_numbers}"

    # Shared cutover-ISO and signoff-ISO.
    cutover_isos = {m.cutover_iso for m in kw_24_bundle.markers}
    signoff_isos = {m.signoff_iso for m in kw_24_bundle.markers}
    assert len(cutover_isos) == 1, (
        f"KW-24 DW partners must share cutover-ISO; got {cutover_isos}"
    )
    assert len(signoff_isos) == 1, (
        f"KW-24 DW partners must share signoff-ISO; got {signoff_isos}"
    )


def test_mar_kw_25_solo_welle_3_carries_henrik_caution_pre_audit_path_marker() -> None:
    """KW-25 is the Solo-Welle-3 slot (bridge_audit_writer, Henrik-Caution
    pre-audit-path per ADR-0066 §Wochen-Plan Pt-2). The bundle must carry
    exactly one welle-marker (Welle-3) and the underlying ADR-0066-slot
    must list ``is_solo=True`` and ``risk_class="moderate-henrik-caution"``.
    """
    marathon = _build_green_marathon()
    kw_25_bundle = next(b for b in marathon.bundles if b.kw == 25)

    assert len(kw_25_bundle.markers) == 1, (
        f"KW-25 must be solo-Welle; got {len(kw_25_bundle.markers)} markers"
    )
    assert kw_25_bundle.markers[0].welle_number == 3, (
        f"KW-25 must be Welle-3; got Welle-{kw_25_bundle.markers[0].welle_number}"
    )

    welle_3_slot = ADR_0066_REIHENFOLGE[2]
    assert welle_3_slot.is_solo is True, "Welle-3 must be solo per ADR-0066"
    assert welle_3_slot.risk_class == "moderate-henrik-caution", (
        f"Welle-3 must carry the Henrik-Caution risk-class; "
        f"got {welle_3_slot.risk_class!r}"
    )


def test_mar_kw_26_doppel_welle_4_5_carries_symmetric_a7_drift_assertion() -> None:
    """KW-26 is the Doppel-Welle-4+5 slot (state_backing + lifecycle_state_
    machine). Both markers must carry an A7-cross-modul-drift assertion;
    in the all-green happy-path both must equal ``"green"`` (symmetric A7-
    drift expectation per ADR-0066 §Wochen-Plan Pt-3)."""
    marathon = _build_green_marathon()
    kw_26_bundle = next(b for b in marathon.bundles if b.kw == 26)

    welle_numbers = sorted(m.welle_number for m in kw_26_bundle.markers)
    assert welle_numbers == [4, 5], f"KW-26 must be DW-4+5; got {welle_numbers}"

    # Symmetric A7-drift: both partners report identical verdict (green here).
    drift_verdicts = {m.cross_welle_drift_assert for m in kw_26_bundle.markers}
    assert len(drift_verdicts) == 1, (
        f"KW-26 DW partners must report symmetric A7-drift; got {drift_verdicts}"
    )
    assert drift_verdicts == {"green"}, (
        f"happy-path A7-drift must be green; got {drift_verdicts}"
    )


def test_mar_kw_27_doppel_welle_6_7_carries_iia_1130_pre_auditor_decision_gate() -> None:
    """KW-27 is the Phase-3-Schluss-slot (Doppel-Welle-6+7). The bundle
    must carry the Welle-7-Pre-Auditor-Decision artefact (IIA-1130
    anchor): Internal Audit does not set the Phase-3-COMPLETE-marker;
    the AR-Hand-Pre-Auditor decision is the substitute control."""
    marathon = _build_green_marathon()
    kw_27_bundle = next(b for b in marathon.bundles if b.kw == 27)

    welle_numbers = sorted(m.welle_number for m in kw_27_bundle.markers)
    assert welle_numbers == [6, 7], f"KW-27 must be DW-6+7; got {welle_numbers}"

    # IIA-1130 Pre-Auditor-Decision artefact must be present.
    pad = kw_27_bundle.welle_7_pre_auditor_decision
    assert pad is not None, (
        "KW-27 must carry the Welle-7-Pre-Auditor-Decision (IIA-1130 anchor)"
    )
    assert pad.decision_present is True
    assert pad.decision_id != "", "Pre-Auditor-Decision must have a decision_id"
    assert pad.ar_hand_signature != "", (
        "Pre-Auditor-Decision must carry an AR-Hand signature"
    )
    assert pad.iia_1130_independence_anchor != "", (
        "Pre-Auditor-Decision must surface the IIA-1130 independence anchor"
    )


# ===========================================================================
# AC15 — Phase-3-COMPLETE AC-1..AC-5 conjunction (5 tests)
# ===========================================================================


def test_ac15_all_five_criteria_green_fires_phase_3_complete_marker() -> None:
    """Happy-path: marathon green + AC-1..AC-5 all green => marker fires.

    Mirrors the workflow emit-step ``if:`` predicate (per
    ``.github/workflows/phase-3-complete-marker.yml`` §Emit-step):
    the marker emits only on the Boolean conjunction of AC-1..AC-5.
    """
    marathon = _build_green_marathon()
    ac15 = _build_green_ac_1_to_5(marathon)

    assert ac15.all_five_green is True, (
        f"all-green marathon should yield AC-1..AC-5 all-green; "
        f"failing: {ac15.failing_criteria()}"
    )
    assert ac15.failing_criteria() == (), (
        "happy-path: failing-criteria tuple must be empty"
    )

    # Marker state-machine confirms the seven sign-offs.
    verdict = _run_marker_state_machine(marathon)
    assert verdict.phase_3_complete is True, (
        f"happy-path marathon must fire marker; reasons: {verdict.blocking_reasons}"
    )
    assert verdict.signoff_count == 7


def test_ac15_ac_1_six_of_seven_signoffs_blocks_marker() -> None:
    """AC-1 requires all seven welle-sign-offs. Drop Welle-6's sign-off
    to pending; AC-1 must surface as failing and the marker must not fire.
    """
    marathon = _build_green_marathon()
    # Mutate the KW-27 bundle: flip Welle-6 to pending.
    kw_27_bundle = marathon.bundles[3]
    new_markers = tuple(
        replace(
            m, status="pending", ac_1_5_green=False, ac_4_consensus_personas=frozenset()
        )
        if m.welle_number == 6
        else m
        for m in kw_27_bundle.markers
    )
    new_kw_27 = replace(kw_27_bundle, markers=new_markers)
    perturbed = MarathonSequence(
        bundles=marathon.bundles[:3] + (new_kw_27,)
    )
    ac15 = _build_green_ac_1_to_5(perturbed)

    assert ac15.ac_1_green is False, (
        f"AC-1 must fail with 6/7 sign-offs; signoff-count={ac15.ac_1_welle_signoff_count}"
    )
    assert "AC-1" in ac15.failing_criteria()
    assert ac15.all_five_green is False
    assert _run_marker_state_machine(perturbed).phase_3_complete is False


def test_ac15_ac_4_henrik_ratification_missing_blocks_marker() -> None:
    """AC-4 requires Henrik's R-A1..R-A6 ratification (aggregate_verdict=
    ``"ratified"``). Flip to ``"blocked"``; AC-4 must surface as failing."""
    marathon = _build_green_marathon()
    ac15_green = _build_green_ac_1_to_5(marathon)
    perturbed = replace(
        ac15_green,
        ac_4_henrik_ratification=HenrikRatification(
            aggregate_verdict="blocked",
            r_a_mitigation_status={
                **{f"R-A{i}": "mitigated" for i in range(1, 6)},
                "R-A6": "open",
            },
        ),
    )

    assert perturbed.ac_4_green is False
    assert "AC-4" in perturbed.failing_criteria()
    assert perturbed.all_five_green is False

    bilanz = _fire_bilanz_trigger(marathon, perturbed)
    assert bilanz.fires is False, (
        "Bilanz-Trigger must not fire when AC-4 is missing"
    )
    assert "AC-4" in bilanz.blocking_reasons


def test_ac15_ac_5_ar_hand_stamp_missing_blocks_marker() -> None:
    """AC-5 requires the AR-Hand stamp (IIA-1130 anchor: AR-Hand
    ratifies, not Internal Audit). Flip ar_hand_ratification to False;
    AC-5 must surface as failing."""
    marathon = _build_green_marathon()
    ac15_green = _build_green_ac_1_to_5(marathon)
    perturbed = replace(
        ac15_green,
        ac_5_ar_hand_stamp=ArHandStamp(
            ar_hand_ratification=False,
            ar_hand_quote="Aufsichtsrat ratifiziert NICHT.",
        ),
    )

    assert perturbed.ac_5_green is False
    assert "AC-5" in perturbed.failing_criteria()
    assert perturbed.all_five_green is False

    bilanz = _fire_bilanz_trigger(marathon, perturbed)
    assert bilanz.fires is False
    assert "AC-5" in bilanz.blocking_reasons


def test_ac15_ac_5_iia_1130_ar_hand_quote_empty_blocks_marker() -> None:
    """IIA-1130 independence anchor: AR-Hand-stamp must carry a non-empty
    ``ar_hand_quote`` (per workflow §AC-5 + Henrik Spec §3 Pt-5: "no
    implicit marker setting by Internal Audit"). Flip the quote to empty
    => AC-5 must fail even with ar_hand_ratification=True."""
    marathon = _build_green_marathon()
    ac15_green = _build_green_ac_1_to_5(marathon)
    perturbed = replace(
        ac15_green,
        ac_5_ar_hand_stamp=ArHandStamp(
            ar_hand_ratification=True,
            ar_hand_quote="   ",  # whitespace-only: empty after strip
        ),
    )

    assert perturbed.ac_5_green is False, (
        "AC-5 must require a non-empty ar_hand_quote (IIA-1130 anchor)"
    )
    assert "AC-5" in perturbed.failing_criteria()


# ===========================================================================
# NEG — Anti-Phase-3-COMPLETE-False-Positive (5 tests, per Auftrag §2)
# ===========================================================================


def test_neg_welle_3_rollback_blocks_welle_4_to_7_and_marker_not_set() -> None:
    """If Welle-3 rolls back, cascade-block contract: Welle-4..7 must not
    sign off on a rolled-back upstream, and the marker must not fire."""
    marathon = _build_green_marathon()

    # KW-25: flip Welle-3 to rolled-back.
    kw_25_bundle = marathon.bundles[1]
    new_markers_25 = tuple(
        replace(m, status="rolled-back") for m in kw_25_bundle.markers
    )
    new_kw_25 = replace(kw_25_bundle, markers=new_markers_25)

    # KW-26 + KW-27: downstream wellen must be in pending (not signed-off).
    def _flip_to_pending(bundle: PerKwSignOffBundle) -> PerKwSignOffBundle:
        new_markers = tuple(
            replace(
                m,
                status="pending",
                ac_1_5_green=False,
                ac_4_consensus_personas=frozenset(),
            )
            for m in bundle.markers
        )
        return replace(bundle, markers=new_markers)

    new_kw_26 = _flip_to_pending(marathon.bundles[2])
    new_kw_27 = _flip_to_pending(marathon.bundles[3])

    perturbed = MarathonSequence(
        bundles=(marathon.bundles[0], new_kw_25, new_kw_26, new_kw_27)
    )

    # State-machine: cascade_blocked + marker not fired.
    verdict = _run_marker_state_machine(perturbed)
    assert verdict.cascade_blocked is True, (
        "rollback-cascade must surface cascade_blocked=True"
    )
    assert verdict.phase_3_complete is False, (
        "marker must not fire when an upstream welle rolled back"
    )

    # AC-1 conjunction also fails because welle-4..7 are pending.
    ac15 = _build_green_ac_1_to_5(perturbed)
    assert ac15.ac_1_green is False
    assert "AC-1" in ac15.failing_criteria()


def test_neg_welle_7_pre_auditor_decision_missing_marker_not_set() -> None:
    """If the IIA-1130 Welle-7-Pre-Auditor-Decision is missing, the KW-27
    bundle must surface ``is_green=False`` and the AC-5 AR-Hand-quote (the
    surrogate surface in the Phase-3-COMPLETE workflow) cannot be set; the
    marker must not fire."""
    marathon = _build_green_marathon()
    kw_27_bundle = marathon.bundles[3]

    # Drop the Welle-7-Pre-Auditor-Decision.
    new_kw_27 = replace(
        kw_27_bundle,
        welle_7_pre_auditor_decision=None,
    )
    perturbed = MarathonSequence(
        bundles=marathon.bundles[:3] + (new_kw_27,)
    )

    assert perturbed.bundles[3].is_green is False, (
        "KW-27 bundle missing Pre-Auditor-Decision must surface is_green=False"
    )

    # AC-5 in the workflow gates on the AR-Hand-quote, which itself is
    # contingent on the Welle-7-Pre-Auditor-Decision having been issued.
    ac15_green = _build_green_ac_1_to_5(perturbed)
    iia_1130_ac5 = replace(
        ac15_green,
        ac_5_ar_hand_stamp=ArHandStamp(
            ar_hand_ratification=False,
            ar_hand_quote="",
        ),
    )
    assert iia_1130_ac5.ac_5_green is False
    assert iia_1130_ac5.all_five_green is False
    bilanz = _fire_bilanz_trigger(perturbed, iia_1130_ac5)
    assert bilanz.fires is False
    assert "AC-5" in bilanz.blocking_reasons


def test_neg_cross_modul_drift_welle_4_5_blocker_marker_not_set() -> None:
    """If the symmetric A7-drift assertion on KW-26 (Welle-4+5) reports
    ``"blocker"``, the marker state-machine's drift-aggregation verdict
    must be ``"blocker"`` and the marker must not fire."""
    marathon = _build_green_marathon()
    kw_26_bundle = marathon.bundles[2]
    new_markers_26 = tuple(
        replace(m, cross_welle_drift_assert="blocker")
        for m in kw_26_bundle.markers
    )
    new_kw_26 = replace(kw_26_bundle, markers=new_markers_26)
    perturbed = MarathonSequence(
        bundles=marathon.bundles[:2] + (new_kw_26,) + marathon.bundles[3:]
    )

    verdict = _run_marker_state_machine(perturbed)
    assert verdict.drift_aggregation_verdict == "blocker", (
        f"drift-aggregation must be blocker; got {verdict.drift_aggregation_verdict}"
    )
    assert verdict.phase_3_complete is False
    assert any(
        "drift" in reason.lower() for reason in verdict.blocking_reasons
    ), f"blocking_reasons must mention drift; got {verdict.blocking_reasons}"


def test_neg_six_of_seven_signoffs_marker_not_set() -> None:
    """Plain symmetric defence: every single missing sign-off (any one of
    the seven) must keep the marker dark. Walks all seven possible "one-
    missing" arrangements."""
    marathon = _build_green_marathon()
    for missing_welle in range(1, 8):
        perturbed_bundles: List[PerKwSignOffBundle] = []
        for bundle in marathon.bundles:
            new_markers = tuple(
                replace(
                    m,
                    status="pending",
                    ac_1_5_green=False,
                    ac_4_consensus_personas=frozenset(),
                )
                if m.welle_number == missing_welle
                else m
                for m in bundle.markers
            )
            perturbed_bundles.append(replace(bundle, markers=new_markers))
        perturbed = MarathonSequence(bundles=tuple(perturbed_bundles))

        verdict = _run_marker_state_machine(perturbed)
        assert verdict.phase_3_complete is False, (
            f"marker fired with welle-{missing_welle} missing; "
            f"false-positive defence broken"
        )
        ac15 = _build_green_ac_1_to_5(perturbed)
        assert ac15.ac_1_green is False, (
            f"AC-1 must fail with welle-{missing_welle} missing; "
            f"signoff-count={ac15.ac_1_welle_signoff_count}"
        )
        bilanz = _fire_bilanz_trigger(perturbed, ac15)
        assert bilanz.fires is False


def test_neg_kw_26_partial_signoff_in_doppel_welle_marker_not_set() -> None:
    """Partial Doppel-Welle sign-off: only Welle-4 signs off in KW-26,
    Welle-5 stays pending. The bundle must surface is_green=False, the
    marker must not fire."""
    marathon = _build_green_marathon()
    kw_26_bundle = marathon.bundles[2]
    new_markers_26 = tuple(
        replace(
            m,
            status="pending",
            ac_1_5_green=False,
            ac_4_consensus_personas=frozenset(),
        )
        if m.welle_number == 5
        else m
        for m in kw_26_bundle.markers
    )
    new_kw_26 = replace(kw_26_bundle, markers=new_markers_26)
    perturbed = MarathonSequence(
        bundles=marathon.bundles[:2] + (new_kw_26,) + marathon.bundles[3:]
    )

    assert perturbed.bundles[2].is_green is False, (
        "KW-26 bundle with partial DW sign-off must surface is_green=False"
    )

    verdict = _run_marker_state_machine(perturbed)
    assert verdict.phase_3_complete is False
    assert verdict.signoff_count == 6


# ===========================================================================
# BIL — Phase-3-Marathon-Bilanz-Trigger (3 tests)
# ===========================================================================


def test_bil_bilanz_trigger_fires_on_complete_marker_green() -> None:
    """Bilanz-Trigger fires once AC-1..AC-5 are all green (marker condition)."""
    marathon = _build_green_marathon()
    ac15 = _build_green_ac_1_to_5(marathon)
    bilanz = _fire_bilanz_trigger(
        marathon, ac15, marker_iso="2026-07-06T12:00:00+02:00"
    )

    assert bilanz.fires is True, (
        f"Bilanz-Trigger must fire when AC-1..AC-5 all green; "
        f"got blocking={bilanz.blocking_reasons}"
    )
    assert bilanz.welle_signoff_count == 7
    assert bilanz.marker_iso == "2026-07-06T12:00:00+02:00"
    assert bilanz.blocking_reasons == ()


def test_bil_bilanz_trigger_does_not_fire_when_marker_not_set() -> None:
    """Bilanz-Trigger MUST NOT fire when the marker conditions are not met
    (any AC-1..AC-5 failing); blocking_reasons surfaces the failing AC IDs.
    """
    marathon = _build_green_marathon()
    ac15_green = _build_green_ac_1_to_5(marathon)

    # Walk each AC and confirm the trigger refuses to fire.
    perturbations: List[Phase3CompleteAC1To5] = [
        replace(ac15_green, ac_1_welle_signoff_count=6),
        replace(ac15_green, ac_2_validation_workflows_all_success=False),
        replace(ac15_green, ac_3_phase_3abc_closure_present=False),
        replace(
            ac15_green,
            ac_4_henrik_ratification=HenrikRatification(
                aggregate_verdict="blocked"
            ),
        ),
        replace(
            ac15_green,
            ac_5_ar_hand_stamp=ArHandStamp(
                ar_hand_ratification=False,
                ar_hand_quote="",
            ),
        ),
    ]
    expected_failing = ["AC-1", "AC-2", "AC-3", "AC-4", "AC-5"]
    for perturbed, expected_ac in zip(perturbations, expected_failing):
        bilanz = _fire_bilanz_trigger(marathon, perturbed)
        assert bilanz.fires is False, (
            f"Bilanz-Trigger must not fire when {expected_ac} fails"
        )
        assert expected_ac in bilanz.blocking_reasons, (
            f"Bilanz-Trigger blocking-reasons must surface {expected_ac}; "
            f"got {bilanz.blocking_reasons}"
        )


def test_bil_bilanz_trigger_payload_carries_kw_24_to_27_marathon_summary() -> None:
    """The Bilanz-Trigger payload must carry every KW-signoff-ISO so the
    Noa Tag-43 Bilanz-Generator can render the marathon-summary timeline."""
    marathon = _build_green_marathon()
    ac15 = _build_green_ac_1_to_5(marathon)
    bilanz = _fire_bilanz_trigger(
        marathon, ac15, marker_iso="2026-07-06T12:00:00+02:00"
    )

    # All four KW signoff-ISOs present and non-empty.
    isos = [
        bilanz.kw_24_signoff_iso,
        bilanz.kw_25_signoff_iso,
        bilanz.kw_26_signoff_iso,
        bilanz.kw_27_signoff_iso,
    ]
    for kw, iso in zip([24, 25, 26, 27], isos):
        assert iso, f"Bilanz-Trigger must carry KW-{kw} signoff-ISO"

    # Chronologically increasing across the four KWs.
    assert isos == sorted(isos), (
        f"Bilanz-Trigger KW signoff-ISOs must be chronologically increasing; "
        f"got {isos}"
    )

    # Marker-ISO must follow the last (KW-27) signoff-ISO.
    assert bilanz.marker_iso > bilanz.kw_27_signoff_iso, (
        f"marker-ISO must be after KW-27 sign-off; "
        f"marker={bilanz.marker_iso} kw_27={bilanz.kw_27_signoff_iso}"
    )


# ===========================================================================
# DOC — Documentation contract (2 tests)
# ===========================================================================


_DOC_PATH = (
    _repo_root() / "docs" / "quality-gates"
    / "phase-3-marathon-schluss-acceptance.md"
)


def test_doc_definition_of_done_file_exists_and_documents_marathon_sequence() -> None:
    """The Tag-43 Definition-of-Done doc must exist and document the
    four-KW marathon-sequence (KW-24..KW-27) as the contract surface."""
    assert _DOC_PATH.is_file(), (
        f"Tag-43 Marathon-Schluss-Acceptance Definition-of-Done file "
        f"missing at {_DOC_PATH}"
    )
    text = _DOC_PATH.read_text(encoding="utf-8")
    for needle in ("KW-24", "KW-25", "KW-26", "KW-27", "marathon"):
        assert needle in text, (
            f"Definition-of-Done doc must reference {needle!r}"
        )


def test_doc_definition_of_done_references_ac_1_to_ac_5_conjunction() -> None:
    """The Definition-of-Done doc must reference every AC-1..AC-5 by ID
    plus the IIA-1130 Welle-7-Pre-Auditor-Decision anchor."""
    text = _DOC_PATH.read_text(encoding="utf-8")
    for needle in ("AC-1", "AC-2", "AC-3", "AC-4", "AC-5", "IIA-1130"):
        assert needle in text, (
            f"Definition-of-Done doc must reference {needle!r}"
        )


# ===========================================================================
# CROSS — Cross-suite contract-lock-step (4 tests)
#
# These tests pin the contract surface between this Tag-43 marathon suite
# and the Tag-40 final-regression / Tag-41 cutover-day-drill companion
# suites. Drift detection: if a sibling suite's canonical constant shifts,
# these tests fail loud.
# ===========================================================================


def test_cross_marathon_signoff_markers_match_tag_40_marker_state_machine() -> None:
    """The marathon-sequence aggregated markers must drive the Tag-40
    Phase3CompleteMarkerStateMachine to phase_3_complete=True (happy path).

    This is the load-bearing cross-suite contract: the Tag-43 marathon-
    sequence output IS the input to the Tag-40 state-machine. If either
    surface drifts, this test fails.
    """
    marathon = _build_green_marathon()
    all_markers = marathon.all_markers

    # The Tag-40 SignOffMarker dataclass must accept every marker shape.
    for welle_number, marker in all_markers.items():
        assert isinstance(marker, SignOffMarker), (
            f"Welle-{welle_number} marker is not a Tag-40 SignOffMarker: "
            f"{type(marker)!r}"
        )
        # Marker must satisfy the Tag-40 contract surface fields.
        assert marker.welle_number == welle_number
        assert marker.status == "signed-off"
        assert marker.ac_1_5_green is True
        assert marker.ac_4_consensus_personas == ADR_0065_AC_4_PERSONAS

    # Reduce through the Tag-40 state-machine: marker must fire.
    we_gates: Dict[str, bool] = {gate: True for gate in WELLE_ENDE_GATES}
    sm = Phase3CompleteMarkerStateMachine(all_markers, we_gates)
    verdict = sm.compute_verdict()
    assert verdict.phase_3_complete is True
    assert verdict.signoff_count == 7
    assert verdict.cross_review_consensus is True
    assert verdict.welle_ende_complete is True
    assert verdict.cascade_blocked is False
    assert verdict.drift_aggregation_verdict == "green"


def test_cross_marathon_per_kw_bundles_align_with_tag_41_cutover_day_drill_schedule() -> None:
    """Every welle in the marathon-sequence must be present in the Tag-41
    CUTOVER_DAY_DRILL_SCHEDULE (the per-day walkthrough slots). This pins
    the contract surface between the marathon-sequence orchestration and
    the per-day drill: the seven wellen must appear in both."""
    marathon = _build_green_marathon()
    marathon_welle_numbers: set[int] = set()
    for bundle in marathon.bundles:
        for marker in bundle.markers:
            marathon_welle_numbers.add(marker.welle_number)

    drill_welle_numbers = {
        slot.welle_number for slot in CUTOVER_DAY_DRILL_SCHEDULE
    }

    assert marathon_welle_numbers == {1, 2, 3, 4, 5, 6, 7}
    assert drill_welle_numbers == {1, 2, 3, 4, 5, 6, 7}
    assert marathon_welle_numbers == drill_welle_numbers, (
        f"Tag-43 marathon-sequence and Tag-41 cutover-day-drill must "
        f"cover identical welle-sets; marathon={marathon_welle_numbers}, "
        f"drill={drill_welle_numbers}"
    )


def test_cross_marathon_signoff_isos_match_tag_40_marathon_trace_timestamps() -> None:
    """The per-KW signoff-Freitag-ISOs in the marathon-sequence must match
    the canonical Tag-40 MARATHON_TRACE_TIMESTAMPS table.

    This is the cross-spawn-Konsistenz anchor: if Tag-40 shifts the
    KW-Cadence timestamps, this Tag-43 file MUST surface the drift.
    """
    marathon = _build_green_marathon()
    by_kw_marathon = {b.kw: b for b in marathon.bundles}
    by_kw_tag40 = {row[0]: row for row in MARATHON_TRACE_TIMESTAMPS}

    for kw in (24, 25, 26, 27):
        bundle = by_kw_marathon[kw]
        tag40_row = by_kw_tag40[kw]
        assert bundle.cutover_iso == tag40_row[1], (
            f"KW-{kw} cutover-ISO drift: marathon={bundle.cutover_iso!r}, "
            f"Tag-40-canonical={tag40_row[1]!r}"
        )
        assert bundle.review_iso == tag40_row[2], (
            f"KW-{kw} review-ISO drift: marathon={bundle.review_iso!r}, "
            f"Tag-40-canonical={tag40_row[2]!r}"
        )
        assert bundle.signoff_iso == tag40_row[3], (
            f"KW-{kw} signoff-ISO drift: marathon={bundle.signoff_iso!r}, "
            f"Tag-40-canonical={tag40_row[3]!r}"
        )


def test_cross_marathon_kw_27_pre_auditor_decision_blocks_ac_5_quote() -> None:
    """Threading the IIA-1130 contract end-to-end: if the Welle-7 Pre-
    Auditor-Decision is *not present*, the AR-Hand-quote cannot be set
    (because AR-Hand only stamps post-Pre-Auditor-Decision per Henrik
    Tag-39 §IIA-1130 audit-spec). Hence in the perturbed marathon, AC-5
    must surface as failing.

    This is the *substantive* IIA-1130 cross-suite anchor: the Welle-7
    Pre-Auditor-Decision artefact gates the AR-Hand stamp; the AR-Hand
    stamp gates AC-5; AC-5 gates the marker; the marker gates the
    Bilanz-Trigger. The full chain must fail when the Pre-Auditor-
    Decision is missing.
    """
    marathon = _build_green_marathon()

    # Drop the Pre-Auditor-Decision on KW-27.
    perturbed_kw_27 = replace(
        marathon.bundles[3],
        welle_7_pre_auditor_decision=None,
    )
    perturbed = MarathonSequence(
        bundles=marathon.bundles[:3] + (perturbed_kw_27,),
    )

    # Without the Pre-Auditor-Decision, the AR-Hand stamp cannot ratify
    # (workflow-level): we model that by emitting an AC-5 with
    # ar_hand_ratification=False.
    ac15_green = _build_green_ac_1_to_5(perturbed)
    ac15_post_iia_1130 = replace(
        ac15_green,
        ac_5_ar_hand_stamp=ArHandStamp(
            ar_hand_ratification=False,
            ar_hand_quote="",
        ),
    )

    assert perturbed.bundles[3].is_green is False
    assert ac15_post_iia_1130.ac_5_green is False
    assert "AC-5" in ac15_post_iia_1130.failing_criteria()

    bilanz = _fire_bilanz_trigger(perturbed, ac15_post_iia_1130)
    assert bilanz.fires is False
    assert "AC-5" in bilanz.blocking_reasons


# ===========================================================================
# CONJ — AC-1..AC-5 conjunction truth-table walk (3 tests)
#
# These tests pin the conjunctive predicate logic exhaustively: only the
# all-green vector yields all_five_green=True; every other vector yields
# all_five_green=False; failing_criteria() surfaces exactly the failing
# IDs (no false positives, no false negatives).
# ===========================================================================


def test_conj_only_all_five_green_yields_all_five_green_property() -> None:
    """Conjunctive predicate: the all_five_green property is True iff
    every one of the five AC properties is True. Walk: build the canonical
    all-green envelope, confirm True; flip any one of the five inputs,
    confirm False."""
    marathon = _build_green_marathon()
    green = _build_green_ac_1_to_5(marathon)
    assert green.all_five_green is True

    # Flip AC-1.
    p1 = replace(green, ac_1_welle_signoff_count=0)
    assert p1.all_five_green is False

    # Flip AC-2.
    p2 = replace(green, ac_2_validation_workflows_all_success=False)
    assert p2.all_five_green is False

    # Flip AC-3.
    p3 = replace(green, ac_3_phase_3abc_closure_present=False)
    assert p3.all_five_green is False

    # Flip AC-4.
    p4 = replace(
        green,
        ac_4_henrik_ratification=HenrikRatification(
            aggregate_verdict="blocked"
        ),
    )
    assert p4.all_five_green is False

    # Flip AC-5.
    p5 = replace(
        green,
        ac_5_ar_hand_stamp=ArHandStamp(
            ar_hand_ratification=False, ar_hand_quote=""
        ),
    )
    assert p5.all_five_green is False


def test_conj_any_single_failing_criterion_blocks_marker() -> None:
    """For every single AC failing in isolation, the Bilanz-Trigger must
    refuse to fire. Mirrors the workflow emit-step ``if:`` predicate's
    short-circuit-on-any-false-input behaviour."""
    marathon = _build_green_marathon()
    green = _build_green_ac_1_to_5(marathon)

    singletons = [
        ("AC-1", replace(green, ac_1_welle_signoff_count=3)),
        ("AC-2", replace(green, ac_2_validation_workflows_all_success=False)),
        ("AC-3", replace(green, ac_3_phase_3abc_closure_present=False)),
        (
            "AC-4",
            replace(
                green,
                ac_4_henrik_ratification=HenrikRatification(
                    aggregate_verdict="blocked"
                ),
            ),
        ),
        (
            "AC-5",
            replace(
                green,
                ac_5_ar_hand_stamp=ArHandStamp(
                    ar_hand_ratification=False, ar_hand_quote=""
                ),
            ),
        ),
    ]
    for ac_id, perturbed in singletons:
        bilanz = _fire_bilanz_trigger(marathon, perturbed)
        assert bilanz.fires is False, (
            f"Bilanz-Trigger must not fire when {ac_id} is the lone failure"
        )
        assert bilanz.blocking_reasons == (ac_id,), (
            f"failing-criteria for lone-{ac_id} must be ({ac_id},); "
            f"got {bilanz.blocking_reasons}"
        )


def test_conj_failing_criteria_tuple_contains_exactly_the_failing_ids() -> None:
    """Multi-failure case: flip AC-1 + AC-4 + AC-5; failing_criteria()
    must surface exactly those three IDs, in deterministic order."""
    marathon = _build_green_marathon()
    green = _build_green_ac_1_to_5(marathon)
    perturbed = replace(
        green,
        ac_1_welle_signoff_count=5,
        ac_4_henrik_ratification=HenrikRatification(
            aggregate_verdict="blocked"
        ),
        ac_5_ar_hand_stamp=ArHandStamp(
            ar_hand_ratification=False, ar_hand_quote=""
        ),
    )

    failing = perturbed.failing_criteria()
    assert failing == ("AC-1", "AC-4", "AC-5"), (
        f"failing_criteria must surface exactly the three failing IDs in "
        f"AC-1..AC-5 order; got {failing}"
    )
    assert perturbed.all_five_green is False
    assert perturbed.ac_2_green is True  # untouched
    assert perturbed.ac_3_green is True  # untouched

    bilanz = _fire_bilanz_trigger(marathon, perturbed)
    assert bilanz.fires is False
    assert bilanz.blocking_reasons == failing
