# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Phase-3-final regression-suite — cross-Welle aggregate-coverage for the
Phase-3c-Marathon (KW-24 -> KW-27, ADR-0066 four-week Doppel-Welle-cadence).

Auftrag-Anker
-------------

- Tag-40 Amara Auftrag — Phase-3-E2E-Final-Regression-Suite (Continuous-Mode,
  Aufsichtsrat 2026-05-18). Defines the *atomic acceptance-suite* for the
  Phase-3-COMPLETE marker: a single hermetic test-run that exercises all
  seven welle cutovers in ADR-0066-Reihenfolge, the Phase-3-COMPLETE-marker
  state-machine, the cross-Welle rollback-cascade contract, and the
  long-trace 4-Wochen-Marathon replay.
- ADR-0066 §Beschluss — KW-24 Doppel-Welle-1+2 (``v907_verify`` +
  ``svid_workload_identity``), KW-25 Solo-Welle-3 (``bridge_audit_writer``,
  Henrik-Caution), KW-26 Doppel-Welle-4+5 (``state_backing`` +
  ``lifecycle_state_machine``), KW-27 Doppel-Welle-6+7 (``subscribe_loop`` +
  ``recovery_workflow``).
- ADR-0065 §Verifikations-Plan — the AC-1..AC-5 per-Welle acceptance-criteria
  + the Welle-Ende WE-1..WE-4 closing-criteria. Phase-3-COMPLETE-marker fires
  only after all 7 wellen are AC-1..AC-5-green *and* WE-1..WE-4 are green.
- ADR-0058 §Phase-3 — parent Phase-3-Acceptance-Gate that this suite gates.
- ``docs/quality-gates/phase-3-final-regression-acceptance.md`` (Amara, this
  PR-suite) — the Phase-3-final-regression Definition-of-Done document this
  test-file enforces.

Cross-spawn-Konsistenz (Tag-40)
-------------------------------

- Reza Tag-40 Cross-Welle-Generalprobe — protocol-level fixture exporting
  the ADR-0066-Reihenfolge constant + the canonical sign-off-marker shape
  this file consumes via ``CrossWelleSignOffMarker``-shape mirror.
- Selin Tag-40 Marathon-Aggregat-Tracker — substrate that aggregates per-
  Welle sign-off-records into the Phase-3-COMPLETE state-machine. This
  file's :class:`Phase3CompleteMarkerStateMachine` is the test-side oracle
  the tracker compares against.
- Tomás Tag-40 Phase-3-COMPLETE-Marker-Workflow — CI-aggregator workflow
  that consumes the sign-off-records and writes the Phase-3-COMPLETE marker
  to the audit-trail. This file's marker-state assertions are the gate the
  workflow respects.
- Henrik Tag-40 Cutover-Day-Audit-Spec — Zone-N audit-sample-spec on the
  rollback-cascade audit-records. The CASCADE-test-axis in this file is
  Amara-side QA-evidence that Henrik's audit-sample consumes as a
  complementary (non-substitutive) input.

Scope (28 tests, exceeds Auftrag-Tag-40 minimum of 15)
-------------------------------------------------------

The 28 tests span seven regression-axes per the Auftrag:

CW — Cross-Welle-Integration (sequenced execution)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1.  test_cw_all_seven_wellen_run_in_adr_0066_reihenfolge_kw_24_to_27
2.  test_cw_welle_m_state_does_not_corrupt_welle_n_for_all_m_lt_n
3.  test_cw_welle_isolation_holds_under_intermediate_sequential_states
4.  test_cw_kw_25_solo_welle_3_is_only_solo_welle_in_cadence

P3M — Phase-3-COMPLETE-Marker state-machine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

5.  test_p3m_marker_sets_only_when_all_seven_wellen_sign_off
6.  test_p3m_marker_blocked_when_six_of_seven_wellen_sign_off
7.  test_p3m_marker_blocked_when_ac_4_cross_review_consensus_missing
8.  test_p3m_marker_blocked_when_we_1_to_we_4_welle_ende_incomplete
9.  test_p3m_marker_includes_cross_welle_drift_aggregation_verdict

CASCADE — Rollback-cascade (Welle-3 Henrik-Caution carve-out)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

10. test_cascade_welle_3_rollback_blocks_welle_4_through_7_start
11. test_cascade_welle_5_rollback_blocks_welle_6_through_7_but_not_4
12. test_cascade_asymmetric_doppel_welle_rollback_preserves_partner

REPLAY — 4-Wochen-Marathon long-trace replay
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

13. test_replay_kw_24_through_27_chronological_trace_with_signoff_markers
14. test_replay_marathon_trace_preserves_per_welle_ac_1_to_ac_5_invariants

FALSE-POS — Marker false-positive defence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

15. test_false_pos_marker_not_set_on_six_of_seven_signoff
16. test_false_pos_marker_not_set_when_ac_4_henrik_audit_consensus_missing
17. test_false_pos_marker_not_set_on_premature_kw_26_partial_signoff

SUBSTRATE — Per-Welle smoke-substrate cross-Welle consistency
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

18. test_substrate_all_seven_smokes_expose_focus_component_and_env_var
19. test_substrate_engine_boot_components_strictly_grow_or_stay_across_wellen
20. test_substrate_all_smokes_expose_tri_state_exit_codes
21. test_substrate_all_smokes_share_phase_pre_post_rollback_constants

EXTENDED — additional cascade + verdict edge-cases
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

22. test_extended_marker_verdict_serialises_to_audit_trail_compatible_payload
23. test_extended_drift_aggregation_single_caution_does_not_block_marker
24. test_extended_full_cascade_all_seven_rolled_back_yields_signoff_zero

TIMING — Marathon-trace timing + signoff-order invariants
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

25. test_timing_each_welle_signoff_iso_is_after_its_cutover_iso
26. test_timing_doppel_welle_partners_share_kw_cutover_and_signoff_iso
27. test_timing_solo_welle_3_kw_25_strictly_between_dw_1_2_and_dw_4_5
28. test_timing_marathon_trace_total_span_matches_adr_0066_four_weeks

Hermeticity
-----------

stdlib-only. No podman, no live NATS, no live Bridge-Audit-Writer I/O,
no OTS-calendar contact. The seven welle smoke-modules are loaded via
``importlib`` from their hyphenated ``scripts/phase-3c/`` paths and
exercised against per-welle stub-resolvers built from each smoke's own
``ENGINE_BOOT_COMPONENTS`` inventory. The Phase-3-COMPLETE-marker
state-machine is an in-test pure-Python oracle.

Sandbox-boundary identical to the per-Welle and Doppel-Welle E2E-suites
(``tests/acceptance/phase_3c/``): the live-VM-acceptance-lane (ADR-0060)
remains Operator-Hand responsibility; this suite is the QA-side oracle
the live drill compares against.

Zone-N coordination
-------------------

Henrik (Internal Audit) Zone-N-Quarterly-Review (Aisha-moderiert)
consumes the CASCADE-axis evidence + the P3M-axis ``ac_4_consensus``
evidence-fields as complementary inputs to his Cutover-Day-Audit-Spec
sample. Per Amara/Henrik Zone-N-Boundary-Discipline (ADR-0044 §Zone-N):
QA-evidence here is *complementary* to Henrik's audit-sample, **not
substitutive**. The Phase-3-COMPLETE marker itself is set by the
Tomás Tag-40 Marker-Workflow on green QA-evidence; Henrik retains
independent sampling rights on the rollback-cascade audit-trail.

Vermutungs-Kennzeichnung (P2)
-----------------------------

* The 4-Wochen-Marathon-Trace timestamps (KW-24 Mittwoch 09:00 CEST -> KW-27
  Freitag 17:00 CEST) are ADR-0066-fixed and embedded as test-anchors.
* The per-Welle sign-off-marker shape mirrors the canonical
  ``CrossWelleSignOffMarker`` shape from Reza Tag-40 Cross-Welle-
  Generalprobe (parallel spawn). Pre-spawn, this file uses the
  documented shape from ``docs/quality-gates/phase-3-final-regression-
  acceptance.md`` §3.
* The Phase-3-COMPLETE marker payload-fields (``phase_3_complete``,
  ``signoff_count``, ``cross_review_consensus``, ``welle_ende_complete``,
  ``drift_aggregation_verdict``, ``cascade_blocked``) are placeholder
  shape-anchors pending Tomás Tag-40 Marker-Workflow wire-up; the
  marker-state-machine asserts here pin the contract surface so the
  workflow's writer-side cannot drift the schema silently.

License: Apache-2.0 (parity with sibling Phase-3c artefacts).
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Smoke-module loaders.
#
# We reuse the seven welle smokes as the per-Welle substrate-authorities.
# Each smoke exports ``ENGINE_BOOT_COMPONENTS`` and ``FOCUS_COMPONENT`` /
# ``FOCUS_ENV_VAR``; we drive each in turn against its own stub-resolver
# and aggregate the per-Welle BackendDecisions into the marathon-trace.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the wakir-runtime repo root from this test file."""
    here = Path(__file__).resolve()
    return here.parent.parent.parent


def _load_smoke_module(filename: str, module_name: str) -> Any:
    """Load a Phase-3c welle smoke module by its hyphenated filename."""
    smoke_path = _repo_root() / "scripts" / "phase-3c" / filename
    if not smoke_path.is_file():
        pytest.fail(f"smoke script not found at {smoke_path}")
    spec = importlib.util.spec_from_file_location(module_name, str(smoke_path))
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {smoke_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


WELLE_1 = _load_smoke_module(
    "welle-1-v907-verify-cutover-smoke.py",
    "welle_1_v907_verify_cutover_smoke_for_p3final",
)
WELLE_2 = _load_smoke_module(
    "welle-2-svid-workload-identity-cutover-smoke.py",
    "welle_2_svid_workload_identity_cutover_smoke_for_p3final",
)
WELLE_3 = _load_smoke_module(
    "welle-3-bridge-audit-writer-cutover-smoke.py",
    "welle_3_bridge_audit_writer_cutover_smoke_for_p3final",
)
WELLE_4 = _load_smoke_module(
    "welle-4-state-backing-cutover-smoke.py",
    "welle_4_state_backing_cutover_smoke_for_p3final",
)
WELLE_5 = _load_smoke_module(
    "welle-5-lifecycle-state-machine-cutover-smoke.py",
    "welle_5_lifecycle_state_machine_cutover_smoke_for_p3final",
)
WELLE_6 = _load_smoke_module(
    "welle-6-subscribe-loop-cutover-smoke.py",
    "welle_6_subscribe_loop_cutover_smoke_for_p3final",
)
WELLE_7 = _load_smoke_module(
    "welle-7-recovery-workflow-cutover-smoke.py",
    "welle_7_recovery_workflow_cutover_smoke_for_p3final",
)


# ---------------------------------------------------------------------------
# ADR-0066-Reihenfolge — the canonical cross-Welle ordering this suite
# enforces. The four-Wochen-Doppel-Welle-Cadence collapses seven solo-
# wochen into four (DW-1+2 at KW-24, Solo-Welle-3 at KW-25, DW-4+5 at
# KW-26, DW-6+7 at KW-27). The 7-tuple below is the Welle-ordinal-sequence
# even though three of the slots are run in parallel pairs.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WelleSlot:
    """A single Phase-3c cutover slot in the ADR-0066-Reihenfolge."""

    welle_number: int
    kw: int  # Kalenderwoche
    modul: str
    env_var: str
    smoke_module: Any
    doppel_partner_welle: Optional[int] = None
    is_solo: bool = False
    risk_class: str = "moderate"


#: ADR-0066-Reihenfolge — the canonical seven-Welle sequence with KW + pair
#: bindings. The Phase-3-final-regression-suite enforces this ordering
#: explicitly in test_cw_all_seven_wellen_run_in_adr_0066_reihenfolge.
ADR_0066_REIHENFOLGE: Tuple[WelleSlot, ...] = (
    WelleSlot(
        welle_number=1,
        kw=24,
        modul="v907_verify",
        env_var="WAKIR_V907_VERIFY_BACKEND",
        smoke_module=WELLE_1,
        doppel_partner_welle=2,
        is_solo=False,
        risk_class="lowest",
    ),
    WelleSlot(
        welle_number=2,
        kw=24,
        modul="svid_workload_identity",
        env_var="WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND",
        smoke_module=WELLE_2,
        doppel_partner_welle=1,
        is_solo=False,
        risk_class="low",
    ),
    WelleSlot(
        welle_number=3,
        kw=25,
        modul="bridge_audit_writer",
        env_var="WAKIR_BRIDGE_AUDIT_WRITER_BACKEND",
        smoke_module=WELLE_3,
        doppel_partner_welle=None,
        is_solo=True,
        risk_class="moderate-henrik-caution",
    ),
    WelleSlot(
        welle_number=4,
        kw=26,
        modul="state_backing",
        env_var="WAKIR_STATE_BACKING_BACKEND",
        smoke_module=WELLE_4,
        doppel_partner_welle=5,
        is_solo=False,
        risk_class="elevated",
    ),
    WelleSlot(
        # Welle-5 ADR-0066 long-name ``lifecycle_state_machine``; engine
        # inventar + smoke short-name ``fsm``. Welle-5 env-var follows
        # the engine inventory convention ``WAKIR_FSM_BACKEND``.
        welle_number=5,
        kw=26,
        modul="lifecycle_state_machine",
        env_var="WAKIR_FSM_BACKEND",
        smoke_module=WELLE_5,
        doppel_partner_welle=4,
        is_solo=False,
        risk_class="elevated",
    ),
    WelleSlot(
        welle_number=6,
        kw=27,
        modul="subscribe_loop",
        env_var="WAKIR_SUBSCRIBE_LOOP_BACKEND",
        smoke_module=WELLE_6,
        doppel_partner_welle=7,
        is_solo=False,
        risk_class="high",
    ),
    WelleSlot(
        welle_number=7,
        kw=27,
        modul="recovery_workflow",
        env_var="WAKIR_RECOVERY_BACKEND",
        smoke_module=WELLE_7,
        doppel_partner_welle=6,
        is_solo=False,
        risk_class="highest",
    ),
)


# Six engineering personas whose Cross-Review-Session AC-4-consent is
# mandatory for each Welle's Donnerstag sign-off (ADR-0065 §AC-4).
ADR_0065_AC_4_PERSONAS: FrozenSet[str] = frozenset(
    {"tomas", "reza", "kai", "lena", "noa", "selin"}
)


# Welle-Ende WE-1..WE-4 IDs (ADR-0065 §Welle-Ende-Acceptance).
WELLE_ENDE_GATES: Tuple[str, ...] = ("WE-1", "WE-2", "WE-3", "WE-4")


# Marathon-Trace timestamps (ADR-0066 four-Wochen-Cadence). Mittwoch
# is the cutover-day; Donnerstag is the Cross-Review-Session; Freitag
# is the Go/No-Go sign-off (ADR-0065 §Verifikations-Plan Wochen-Plan).
MARATHON_TRACE_TIMESTAMPS: Tuple[Tuple[int, str, str, str], ...] = (
    # (kw, mittwoch_cutover_iso, donnerstag_review_iso, freitag_signoff_iso)
    (24, "2026-06-10T09:00:00+02:00", "2026-06-11T14:00:00+02:00", "2026-06-12T17:00:00+02:00"),
    (25, "2026-06-17T09:00:00+02:00", "2026-06-18T14:00:00+02:00", "2026-06-19T17:00:00+02:00"),
    (26, "2026-06-24T09:00:00+02:00", "2026-06-25T14:00:00+02:00", "2026-06-26T17:00:00+02:00"),
    (27, "2026-07-01T09:00:00+02:00", "2026-07-02T14:00:00+02:00", "2026-07-03T17:00:00+02:00"),
)


# ---------------------------------------------------------------------------
# Sign-Off-Marker shape — mirrors the canonical
# ``CrossWelleSignOffMarker`` from Reza Tag-40 Cross-Welle-Generalprobe.
# Pre-Reza-Tag-40-merge, the shape lives here as the contract-anchor.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignOffMarker:
    """Per-Welle sign-off-marker for the Phase-3-COMPLETE state machine.

    Five fields are mandatory for the marker to count toward the
    Phase-3-COMPLETE trigger:

    * ``welle_number`` — the welle ordinal (1..7).
    * ``status`` — ``"signed-off"`` or ``"rolled-back"`` or ``"pending"``.
    * ``ac_1_5_green`` — AC-1..AC-5 all green per ADR-0065 §AC-1..AC-5.
    * ``ac_4_consensus_personas`` — the set of personas that consented in
      the Cross-Review-Session (must equal ADR_0065_AC_4_PERSONAS for
      sign-off).
    * ``cross_welle_drift_assert`` — A7 cross-modul-drift assertion result
      from the welle's own smoke (carries the drift-magnitude for the
      marathon-verdict aggregator).
    """

    welle_number: int
    status: str
    ac_1_5_green: bool
    ac_4_consensus_personas: FrozenSet[str]
    cross_welle_drift_assert: str  # "green" | "caution" | "blocker"
    cutover_iso: str = ""
    signoff_iso: str = ""


# ---------------------------------------------------------------------------
# Phase-3-COMPLETE-Marker state-machine — the in-test pure-Python oracle
# that the Tomás Tag-40 Marker-Workflow consumes.
# ---------------------------------------------------------------------------


@dataclass
class Phase3CompleteMarkerVerdict:
    """The aggregate state-machine verdict.

    Carries enough evidence for the audit-trail to reconstruct *why* the
    Phase-3-COMPLETE marker did or did not fire. The Tomás Tag-40
    Marker-Workflow writes this dataclass-as-JSON to the audit-trail.
    """

    phase_3_complete: bool
    signoff_count: int
    cross_review_consensus: bool
    welle_ende_complete: bool
    drift_aggregation_verdict: str  # "green" | "caution" | "blocker"
    cascade_blocked: bool
    blocking_reasons: Tuple[str, ...] = ()


class Phase3CompleteMarkerStateMachine:
    """Aggregates per-Welle sign-off-markers into a Phase-3-COMPLETE verdict.

    The state-machine is intentionally *strict*: the marker fires **only**
    when all of the following hold:

    1. All seven wellen carry ``status="signed-off"`` (6/7 is not enough).
    2. Every welle's ``ac_1_5_green`` is True (per ADR-0065 §AC-1..AC-5).
    3. Every welle's ``ac_4_consensus_personas`` equals the full
       ``ADR_0065_AC_4_PERSONAS`` six-persona set.
    4. ``welle_ende_complete`` is True (WE-1..WE-4 all green, Welle-7 only).
    5. No upstream welle has a ``"rolled-back"`` status (cascade-block).
    6. The cross-Welle drift-aggregation verdict is not ``"blocker"``.
    """

    def __init__(
        self,
        markers: Mapping[int, SignOffMarker],
        welle_ende_gates: Mapping[str, bool],
    ) -> None:
        self._markers = dict(markers)
        self._welle_ende_gates = dict(welle_ende_gates)

    @property
    def signoff_count(self) -> int:
        return sum(
            1 for m in self._markers.values() if m.status == "signed-off"
        )

    def _all_seven_signed_off(self) -> bool:
        if set(self._markers.keys()) != {1, 2, 3, 4, 5, 6, 7}:
            return False
        return all(
            self._markers[i].status == "signed-off" for i in range(1, 8)
        )

    def _all_ac_1_5_green(self) -> bool:
        return all(m.ac_1_5_green for m in self._markers.values())

    def _all_ac_4_consensus(self) -> bool:
        return all(
            m.ac_4_consensus_personas == ADR_0065_AC_4_PERSONAS
            for m in self._markers.values()
        )

    def _welle_ende_complete(self) -> bool:
        return all(
            self._welle_ende_gates.get(gate, False) for gate in WELLE_ENDE_GATES
        )

    def _cascade_blocked(self) -> bool:
        """Cascade-block: if any welle is ``rolled-back`` and a later
        welle is ``signed-off``, that is a contract violation — later
        wellen must not be signed off on top of a rolled-back upstream.

        The plain ``cascade_blocked`` flag answers "did the cascade-rule
        prevent some welle from signing off." That happens whenever a
        rolled-back upstream exists.
        """
        for welle_num, marker in self._markers.items():
            if marker.status == "rolled-back":
                return True
        return False

    def _drift_aggregation_verdict(self) -> str:
        """Aggregate A7-cross-modul-drift verdicts across all 7 wellen.

        The aggregation rule:

        * any ``"blocker"`` -> ``"blocker"``
        * else any ``"caution"`` -> ``"caution"``
        * else ``"green"``
        """
        verdicts = [m.cross_welle_drift_assert for m in self._markers.values()]
        if any(v == "blocker" for v in verdicts):
            return "blocker"
        if any(v == "caution" for v in verdicts):
            return "caution"
        return "green"

    def compute_verdict(self) -> Phase3CompleteMarkerVerdict:
        """Aggregate the per-Welle markers + Welle-Ende-gates into the
        Phase-3-COMPLETE verdict."""
        blocking_reasons: List[str] = []

        all_seven = self._all_seven_signed_off()
        if not all_seven:
            missing = sorted(
                w
                for w in range(1, 8)
                if w not in self._markers
                or self._markers[w].status != "signed-off"
            )
            blocking_reasons.append(
                f"not all seven wellen signed-off (missing/non-signoff: {missing})"
            )

        all_ac_1_5 = self._all_ac_1_5_green()
        if not all_ac_1_5:
            blocking_reasons.append("AC-1..AC-5 not green for all wellen")

        ac_4_consensus = self._all_ac_4_consensus()
        if not ac_4_consensus:
            blocking_reasons.append("AC-4 cross-review-consensus incomplete")

        we_complete = self._welle_ende_complete()
        if not we_complete:
            missing_we = sorted(
                g
                for g in WELLE_ENDE_GATES
                if not self._welle_ende_gates.get(g, False)
            )
            blocking_reasons.append(
                f"Welle-Ende WE-1..WE-4 incomplete (missing: {missing_we})"
            )

        cascade_blocked = self._cascade_blocked()
        if cascade_blocked:
            blocking_reasons.append(
                "rollback-cascade: at least one upstream welle is rolled-back"
            )

        drift_verdict = self._drift_aggregation_verdict()
        if drift_verdict == "blocker":
            blocking_reasons.append(
                "cross-welle-drift-aggregation verdict is BLOCKER"
            )

        phase_3_complete = (
            all_seven
            and all_ac_1_5
            and ac_4_consensus
            and we_complete
            and not cascade_blocked
            and drift_verdict != "blocker"
        )

        return Phase3CompleteMarkerVerdict(
            phase_3_complete=phase_3_complete,
            signoff_count=self.signoff_count,
            cross_review_consensus=ac_4_consensus,
            welle_ende_complete=we_complete,
            drift_aggregation_verdict=drift_verdict,
            cascade_blocked=cascade_blocked,
            blocking_reasons=tuple(blocking_reasons),
        )


# ---------------------------------------------------------------------------
# Helpers — build "all green" and "one-welle-rolled-back" marker-sets.
# ---------------------------------------------------------------------------


def _build_all_green_markers() -> Dict[int, SignOffMarker]:
    """Build the seven-welle marker-set in the green happy-path shape."""
    markers: Dict[int, SignOffMarker] = {}
    for slot in ADR_0066_REIHENFOLGE:
        kw_row = next(row for row in MARATHON_TRACE_TIMESTAMPS if row[0] == slot.kw)
        markers[slot.welle_number] = SignOffMarker(
            welle_number=slot.welle_number,
            status="signed-off",
            ac_1_5_green=True,
            ac_4_consensus_personas=ADR_0065_AC_4_PERSONAS,
            cross_welle_drift_assert="green",
            cutover_iso=kw_row[1],
            signoff_iso=kw_row[3],
        )
    return markers


def _build_all_green_welle_ende_gates() -> Dict[str, bool]:
    """Build the WE-1..WE-4 gates in the green happy-path shape."""
    return {gate: True for gate in WELLE_ENDE_GATES}


# ---------------------------------------------------------------------------
# CW — Cross-Welle-Integration tests
# ---------------------------------------------------------------------------


def test_cw_all_seven_wellen_run_in_adr_0066_reihenfolge_kw_24_to_27() -> None:
    """The seven welle slots must occupy exactly the ADR-0066-cadence:
    KW-24 (2 wellen), KW-25 (1 welle solo), KW-26 (2 wellen), KW-27 (2 wellen).
    """
    by_kw: Dict[int, List[int]] = {}
    for slot in ADR_0066_REIHENFOLGE:
        by_kw.setdefault(slot.kw, []).append(slot.welle_number)

    assert sorted(by_kw.keys()) == [24, 25, 26, 27], (
        f"expected exactly KW 24/25/26/27 cadence; got {sorted(by_kw.keys())}"
    )
    assert by_kw[24] == [1, 2], f"KW-24 must be DW-1+2; got {by_kw[24]}"
    assert by_kw[25] == [3], f"KW-25 must be Solo-Welle-3; got {by_kw[25]}"
    assert by_kw[26] == [4, 5], f"KW-26 must be DW-4+5; got {by_kw[26]}"
    assert by_kw[27] == [6, 7], f"KW-27 must be DW-6+7; got {by_kw[27]}"

    # Welle-Ordnung muss strikt monoton 1..7 sein.
    welle_numbers = [slot.welle_number for slot in ADR_0066_REIHENFOLGE]
    assert welle_numbers == [1, 2, 3, 4, 5, 6, 7]


def test_cw_welle_m_state_does_not_corrupt_welle_n_for_all_m_lt_n() -> None:
    """Cross-Welle isolation: every welle's smoke must expose ENV_VAR/MODUL
    bindings that do not collide with any upstream welle's ENV_VAR/MODUL.

    This is the static substrate-level invariant: the seven welle smokes
    must use disjoint ENV-vars (no two wellen flip the same flag) and
    disjoint focus-MODULs (no two wellen target the same engine
    component).
    """
    env_vars_seen: Dict[str, int] = {}
    moduls_seen: Dict[str, int] = {}
    for slot in ADR_0066_REIHENFOLGE:
        assert slot.env_var not in env_vars_seen, (
            f"ENV-var collision: welle {slot.welle_number} flips "
            f"{slot.env_var}, already flipped by welle "
            f"{env_vars_seen[slot.env_var]}"
        )
        env_vars_seen[slot.env_var] = slot.welle_number

        assert slot.modul not in moduls_seen, (
            f"MODUL collision: welle {slot.welle_number} targets "
            f"{slot.modul}, already targeted by welle "
            f"{moduls_seen[slot.modul]}"
        )
        moduls_seen[slot.modul] = slot.welle_number


def test_cw_welle_isolation_holds_under_intermediate_sequential_states() -> None:
    """Cross-Welle isolation under intermediate (KW-Doppel-Welle) states.

    For each Doppel-Welle (DW-1+2 KW-24, DW-4+5 KW-26, DW-6+7 KW-27),
    the smoke-substrate must list the *partner* welle's focus-MODUL in
    its ``ENGINE_BOOT_COMPONENTS`` inventory (otherwise the partner's
    backend cannot be steered through the same boot-cycle). Test
    confirms the inventory-consistency required for parallel-cutover.
    """
    doppel_pairs = [
        (1, 2),  # KW-24 DW-1+2
        (4, 5),  # KW-26 DW-4+5
        (6, 7),  # KW-27 DW-6+7
    ]
    for welle_a, welle_b in doppel_pairs:
        slot_a = ADR_0066_REIHENFOLGE[welle_a - 1]
        slot_b = ADR_0066_REIHENFOLGE[welle_b - 1]
        modul_b_short = slot_b.modul
        # Welle-7 ADR-name is recovery_workflow; engine inventory uses recovery.
        if modul_b_short == "recovery_workflow":
            modul_b_short = "recovery"
        # Welle-5 ADR-name is lifecycle_state_machine; engine inventory uses fsm.
        if modul_b_short == "lifecycle_state_machine":
            modul_b_short = "fsm"

        inventory_a = getattr(slot_a.smoke_module, "ENGINE_BOOT_COMPONENTS", ())
        # The partner-modul should appear in at least one of the welle's
        # inventories so the doppel-welle parallel-boot can drive it.
        assert (
            modul_b_short in inventory_a
            or modul_b_short in getattr(slot_b.smoke_module, "ENGINE_BOOT_COMPONENTS", ())
        ), (
            f"DW partner-modul {modul_b_short} (welle {welle_b}) not in "
            f"welle {welle_a}'s ENGINE_BOOT_COMPONENTS inventory; doppel-"
            f"welle parallel boot cannot drive partner"
        )


def test_cw_kw_25_solo_welle_3_is_only_solo_welle_in_cadence() -> None:
    """ADR-0066 §Beschluss carves bridge_audit_writer out as the *only*
    Solo-Welle in the cadence. Test pins this Henrik-Caution contract."""
    solo_slots = [s for s in ADR_0066_REIHENFOLGE if s.is_solo]
    assert len(solo_slots) == 1, (
        f"ADR-0066 mandates exactly one Solo-Welle; got {len(solo_slots)}"
    )
    assert solo_slots[0].welle_number == 3
    assert solo_slots[0].modul == "bridge_audit_writer"
    assert solo_slots[0].kw == 25
    assert solo_slots[0].risk_class == "moderate-henrik-caution"
    assert solo_slots[0].doppel_partner_welle is None


# ---------------------------------------------------------------------------
# P3M — Phase-3-COMPLETE-Marker state-machine tests
# ---------------------------------------------------------------------------


def test_p3m_marker_sets_only_when_all_seven_wellen_sign_off() -> None:
    """Happy-path: all seven wellen signed-off, AC-1..5 green, AC-4
    consensus, WE-1..WE-4 green → marker fires."""
    markers = _build_all_green_markers()
    we_gates = _build_all_green_welle_ende_gates()
    sm = Phase3CompleteMarkerStateMachine(markers, we_gates)
    verdict = sm.compute_verdict()
    assert verdict.phase_3_complete is True
    assert verdict.signoff_count == 7
    assert verdict.cross_review_consensus is True
    assert verdict.welle_ende_complete is True
    assert verdict.drift_aggregation_verdict == "green"
    assert verdict.cascade_blocked is False
    assert verdict.blocking_reasons == ()


def test_p3m_marker_blocked_when_six_of_seven_wellen_sign_off() -> None:
    """Missing-one-welle: 6/7 sign-off must NOT set the marker (false-pos
    defence)."""
    markers = _build_all_green_markers()
    # Pull welle-7 to pending.
    markers[7] = SignOffMarker(
        welle_number=7,
        status="pending",
        ac_1_5_green=False,
        ac_4_consensus_personas=frozenset(),
        cross_welle_drift_assert="green",
    )
    sm = Phase3CompleteMarkerStateMachine(
        markers, _build_all_green_welle_ende_gates()
    )
    verdict = sm.compute_verdict()
    assert verdict.phase_3_complete is False
    assert verdict.signoff_count == 6
    assert any("not all seven wellen signed-off" in r for r in verdict.blocking_reasons)


def test_p3m_marker_blocked_when_ac_4_cross_review_consensus_missing() -> None:
    """AC-4 cross-review-consensus is missing one persona for Welle-4 →
    marker MUST NOT fire."""
    markers = _build_all_green_markers()
    incomplete = ADR_0065_AC_4_PERSONAS - {"selin"}
    markers[4] = SignOffMarker(
        welle_number=4,
        status="signed-off",
        ac_1_5_green=True,
        ac_4_consensus_personas=incomplete,
        cross_welle_drift_assert="green",
    )
    sm = Phase3CompleteMarkerStateMachine(
        markers, _build_all_green_welle_ende_gates()
    )
    verdict = sm.compute_verdict()
    assert verdict.phase_3_complete is False
    assert verdict.cross_review_consensus is False
    assert any(
        "AC-4 cross-review-consensus incomplete" in r for r in verdict.blocking_reasons
    )


def test_p3m_marker_blocked_when_we_1_to_we_4_welle_ende_incomplete() -> None:
    """All seven welle sign-offs but WE-3 (Henrik-Audit-Compliance-Check)
    not green → marker MUST NOT fire."""
    markers = _build_all_green_markers()
    we_gates = _build_all_green_welle_ende_gates()
    we_gates["WE-3"] = False  # Henrik-Audit-Compliance-Check pending.
    sm = Phase3CompleteMarkerStateMachine(markers, we_gates)
    verdict = sm.compute_verdict()
    assert verdict.phase_3_complete is False
    assert verdict.welle_ende_complete is False
    assert any("WE-3" in r for r in verdict.blocking_reasons)


def test_p3m_marker_includes_cross_welle_drift_aggregation_verdict() -> None:
    """The verdict struct surfaces the aggregated drift-verdict for the
    Tomás Tag-40 Marker-Workflow to write into the audit-trail.
    Aggregation rule: any blocker -> blocker; else any caution -> caution;
    else green."""
    markers = _build_all_green_markers()
    we_gates = _build_all_green_welle_ende_gates()

    # All green.
    v_green = Phase3CompleteMarkerStateMachine(markers, we_gates).compute_verdict()
    assert v_green.drift_aggregation_verdict == "green"

    # One caution -> caution.
    markers[5] = SignOffMarker(
        welle_number=5,
        status="signed-off",
        ac_1_5_green=True,
        ac_4_consensus_personas=ADR_0065_AC_4_PERSONAS,
        cross_welle_drift_assert="caution",
    )
    v_caution = Phase3CompleteMarkerStateMachine(markers, we_gates).compute_verdict()
    assert v_caution.drift_aggregation_verdict == "caution"
    # Caution alone does not block the marker (signed-off + caution is OK).
    assert v_caution.phase_3_complete is True

    # Add one blocker -> blocker; marker must NOT fire.
    markers[6] = SignOffMarker(
        welle_number=6,
        status="signed-off",
        ac_1_5_green=True,
        ac_4_consensus_personas=ADR_0065_AC_4_PERSONAS,
        cross_welle_drift_assert="blocker",
    )
    v_blocker = Phase3CompleteMarkerStateMachine(markers, we_gates).compute_verdict()
    assert v_blocker.drift_aggregation_verdict == "blocker"
    assert v_blocker.phase_3_complete is False
    assert any("BLOCKER" in r for r in v_blocker.blocking_reasons)


# ---------------------------------------------------------------------------
# CASCADE — Rollback-cascade tests (Welle-3 Henrik-Caution carve-out)
# ---------------------------------------------------------------------------


def test_cascade_welle_3_rollback_blocks_welle_4_through_7_start() -> None:
    """Welle-3 rolled-back ⇒ downstream wellen 4..7 cannot be signed-off
    on top of it; the marker must surface cascade_blocked=True with
    Welle-3 named in the reasoning."""
    markers = _build_all_green_markers()
    markers[3] = SignOffMarker(
        welle_number=3,
        status="rolled-back",
        ac_1_5_green=False,
        ac_4_consensus_personas=frozenset(),
        cross_welle_drift_assert="caution",
    )
    sm = Phase3CompleteMarkerStateMachine(
        markers, _build_all_green_welle_ende_gates()
    )
    verdict = sm.compute_verdict()
    assert verdict.cascade_blocked is True
    assert verdict.phase_3_complete is False
    assert verdict.signoff_count == 6  # wellen 1,2,4,5,6,7 still signed-off
    assert any(
        "rollback-cascade" in r for r in verdict.blocking_reasons
    )


def test_cascade_welle_5_rollback_blocks_welle_6_through_7_but_not_4() -> None:
    """Welle-5 rolled-back ⇒ downstream wellen 6..7 cannot proceed; Welle-4
    (DW-4+5 partner) may *remain* signed-off per DW-AC-3 asymmetric-
    rollback contract (ADR-0066 §Beschluss)."""
    markers = _build_all_green_markers()
    markers[5] = SignOffMarker(
        welle_number=5,
        status="rolled-back",
        ac_1_5_green=False,
        ac_4_consensus_personas=frozenset(),
        cross_welle_drift_assert="blocker",
    )
    sm = Phase3CompleteMarkerStateMachine(
        markers, _build_all_green_welle_ende_gates()
    )
    verdict = sm.compute_verdict()
    assert verdict.cascade_blocked is True
    # Welle-4 stays signed-off — DW-AC-3 asymmetric rollback.
    assert markers[4].status == "signed-off"
    assert verdict.phase_3_complete is False
    # Drift-aggregation should be "blocker" because Welle-5 carries blocker.
    assert verdict.drift_aggregation_verdict == "blocker"


def test_cascade_asymmetric_doppel_welle_rollback_preserves_partner() -> None:
    """DW-AC-3 asymmetric-rollback (ADR-0066): if one modul of a Doppel-
    Welle rolls back, the partner remains rust-default. Test confirms the
    state-machine respects this — the partner's signed-off status is not
    cancelled by the partner's rollback.

    This is a state-machine contract test, not a smoke-substrate test.
    """
    markers = _build_all_green_markers()
    # Welle-6 rolled back; Welle-7 (DW partner) remains signed-off.
    markers[6] = SignOffMarker(
        welle_number=6,
        status="rolled-back",
        ac_1_5_green=False,
        ac_4_consensus_personas=frozenset(),
        cross_welle_drift_assert="blocker",
    )
    # Welle-7 unchanged from green-default.
    sm = Phase3CompleteMarkerStateMachine(
        markers, _build_all_green_welle_ende_gates()
    )
    verdict = sm.compute_verdict()
    assert markers[7].status == "signed-off"
    assert verdict.cascade_blocked is True
    assert verdict.phase_3_complete is False
    assert verdict.signoff_count == 6


# ---------------------------------------------------------------------------
# REPLAY — 4-Wochen-Marathon long-trace replay
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarathonTraceEvent:
    """A single chronological event in the 4-Wochen-Marathon-Trace."""

    kw: int
    iso: str
    kind: str  # "cutover" | "review" | "signoff"
    welle_numbers: Tuple[int, ...]


def _build_marathon_trace() -> Tuple[MarathonTraceEvent, ...]:
    """Build the chronological 4-Wochen-Marathon-Trace.

    Sequence per ADR-0066 §Beschluss:
      KW-24: Mittwoch cutover (DW-1+2) → Donnerstag review → Freitag signoff
      KW-25: Mittwoch cutover (Welle-3 Solo) → Donnerstag review → Freitag signoff
      KW-26: Mittwoch cutover (DW-4+5) → Donnerstag review → Freitag signoff
      KW-27: Mittwoch cutover (DW-6+7) → Donnerstag review → Freitag signoff

    Each KW emits exactly 3 events (cutover/review/signoff).
    """
    events: List[MarathonTraceEvent] = []
    kw_to_wellen: Dict[int, Tuple[int, ...]] = {
        24: (1, 2),
        25: (3,),
        26: (4, 5),
        27: (6, 7),
    }
    for kw, mittwoch, donnerstag, freitag in MARATHON_TRACE_TIMESTAMPS:
        wellen = kw_to_wellen[kw]
        events.append(MarathonTraceEvent(kw=kw, iso=mittwoch, kind="cutover", welle_numbers=wellen))
        events.append(MarathonTraceEvent(kw=kw, iso=donnerstag, kind="review", welle_numbers=wellen))
        events.append(MarathonTraceEvent(kw=kw, iso=freitag, kind="signoff", welle_numbers=wellen))
    return tuple(events)


def test_replay_kw_24_through_27_chronological_trace_with_signoff_markers() -> None:
    """Full 4-week marathon trace must replay chronologically: 4 weeks × 3
    events = 12 events; ISO timestamps strictly increasing; each KW emits
    exactly one cutover + one review + one signoff event in that order."""
    events = _build_marathon_trace()
    assert len(events) == 12, f"marathon-trace must have 12 events; got {len(events)}"

    # ISO timestamps strictly increasing.
    isos = [ev.iso for ev in events]
    assert isos == sorted(isos), "marathon-trace ISO timestamps must be strictly increasing"

    # Each KW: exactly cutover/review/signoff in that order.
    by_kw: Dict[int, List[MarathonTraceEvent]] = {}
    for ev in events:
        by_kw.setdefault(ev.kw, []).append(ev)
    for kw, kw_events in by_kw.items():
        assert len(kw_events) == 3, f"KW-{kw} must have exactly 3 events; got {len(kw_events)}"
        kinds = [ev.kind for ev in kw_events]
        assert kinds == ["cutover", "review", "signoff"], (
            f"KW-{kw} event-order must be cutover/review/signoff; got {kinds}"
        )

    # All seven welle-numbers must appear in the trace.
    all_welle_numbers: List[int] = []
    for ev in events:
        all_welle_numbers.extend(ev.welle_numbers)
    assert set(all_welle_numbers) == {1, 2, 3, 4, 5, 6, 7}


def test_replay_marathon_trace_preserves_per_welle_ac_1_to_ac_5_invariants() -> None:
    """The marathon-trace replay must drive each welle's signoff event
    only after its review event (AC-4 cross-review-consensus is bound to
    the review-event in the per-Welle workflow). State-machine then
    aggregates the seven signed-off markers into the Phase-3-COMPLETE
    verdict — the verdict must fire green at end-of-trace."""
    events = _build_marathon_trace()

    # Drive per-welle sign-off markers as the trace plays out.
    markers: Dict[int, SignOffMarker] = {}
    review_seen_for: set[int] = set()
    for ev in events:
        if ev.kind == "review":
            for w in ev.welle_numbers:
                review_seen_for.add(w)
        elif ev.kind == "signoff":
            for w in ev.welle_numbers:
                # AC-4 cross-review-consensus must have happened before sign-off.
                assert w in review_seen_for, (
                    f"welle {w} cannot sign-off before its review event"
                )
                slot = ADR_0066_REIHENFOLGE[w - 1]
                markers[w] = SignOffMarker(
                    welle_number=w,
                    status="signed-off",
                    ac_1_5_green=True,
                    ac_4_consensus_personas=ADR_0065_AC_4_PERSONAS,
                    cross_welle_drift_assert="green",
                    cutover_iso=ev.iso,
                    signoff_iso=ev.iso,
                )

    # After replaying the full trace, all seven markers must be in place.
    assert set(markers.keys()) == {1, 2, 3, 4, 5, 6, 7}

    sm = Phase3CompleteMarkerStateMachine(
        markers, _build_all_green_welle_ende_gates()
    )
    verdict = sm.compute_verdict()
    assert verdict.phase_3_complete is True
    assert verdict.signoff_count == 7
    assert verdict.drift_aggregation_verdict == "green"


# ---------------------------------------------------------------------------
# FALSE-POS — Marker false-positive defence
# ---------------------------------------------------------------------------


def test_false_pos_marker_not_set_on_six_of_seven_signoff() -> None:
    """Marker must not fire if exactly one welle is pending — try each of
    the seven possible "one-missing" arrangements to confirm the state-
    machine surfaces every gap symmetrically."""
    for missing_welle in range(1, 8):
        markers = _build_all_green_markers()
        markers[missing_welle] = SignOffMarker(
            welle_number=missing_welle,
            status="pending",
            ac_1_5_green=False,
            ac_4_consensus_personas=frozenset(),
            cross_welle_drift_assert="green",
        )
        sm = Phase3CompleteMarkerStateMachine(
            markers, _build_all_green_welle_ende_gates()
        )
        verdict = sm.compute_verdict()
        assert verdict.phase_3_complete is False, (
            f"marker fired with welle-{missing_welle} pending; "
            "false-positive defence broken"
        )
        assert verdict.signoff_count == 6


def test_false_pos_marker_not_set_when_ac_4_henrik_audit_consensus_missing() -> None:
    """All seven wellen carry status=signed-off but Welle-7's AC-4
    cross-review-consensus is missing one persona (the henrik-audit-
    relevant Tomás absence) → marker MUST NOT fire."""
    markers = _build_all_green_markers()
    # Tomás withdrew consent for Welle-7 (the closing welle, highest risk).
    markers[7] = SignOffMarker(
        welle_number=7,
        status="signed-off",
        ac_1_5_green=True,
        ac_4_consensus_personas=ADR_0065_AC_4_PERSONAS - {"tomas"},
        cross_welle_drift_assert="green",
    )
    sm = Phase3CompleteMarkerStateMachine(
        markers, _build_all_green_welle_ende_gates()
    )
    verdict = sm.compute_verdict()
    # Note: state-machine treats "all seven signed-off + AC-4 incomplete" as a
    # CONTRACT violation that surfaces in blocking_reasons but lets the operator
    # see the AC-4 gap explicitly rather than failing silently on the count.
    assert verdict.phase_3_complete is False
    assert verdict.cross_review_consensus is False
    assert any(
        "AC-4 cross-review-consensus incomplete" in r for r in verdict.blocking_reasons
    )


def test_false_pos_marker_not_set_on_premature_kw_26_partial_signoff() -> None:
    """Premature-firing defence: at end of KW-26 (DW-4+5 just signed-off),
    only 5/7 markers exist (wellen 1..5). The marker must NOT fire at
    this midpoint — wellen 6 and 7 are still ahead in KW-27."""
    full = _build_all_green_markers()
    # Only the first 5 wellen are populated; wellen 6 and 7 absent.
    partial: Dict[int, SignOffMarker] = {w: full[w] for w in range(1, 6)}
    sm = Phase3CompleteMarkerStateMachine(
        partial, _build_all_green_welle_ende_gates()
    )
    verdict = sm.compute_verdict()
    assert verdict.phase_3_complete is False
    assert verdict.signoff_count == 5
    assert any(
        "not all seven wellen signed-off" in r for r in verdict.blocking_reasons
    )
    # Wellen 6 and 7 must be listed as missing.
    missing_reason = next(
        r for r in verdict.blocking_reasons if "not all seven wellen signed-off" in r
    )
    assert "6" in missing_reason and "7" in missing_reason


# ---------------------------------------------------------------------------
# SUBSTRATE — Per-Welle smoke-substrate cross-Welle consistency
# ---------------------------------------------------------------------------


def test_substrate_all_seven_smokes_expose_focus_component_and_env_var() -> None:
    """Each of the seven smoke modules must expose the canonical
    ``FOCUS_COMPONENT`` + ``FOCUS_ENV_VAR`` surface that the smoke-loader
    in this Phase-3-final-regression file depends on. The cross-Welle
    aggregator depends on this contract being uniform across all 7
    smokes.

    The mapping must also align with the ``ADR_0066_REIHENFOLGE`` slots
    declared at the top of this file — drift here means either a smoke
    renamed its public surface (substrate-side regression) or the
    Reihenfolge declaration drifted out of step with the smokes
    (oracle-side regression). Either way, the per-Welle and Phase-3-
    final-regression suites stop sharing a substrate, which would
    invalidate the marathon-aggregate verdict.
    """
    for slot in ADR_0066_REIHENFOLGE:
        # Welle-3..6 smokes export FOCUS_COMPONENT directly.
        # Welle-7 smoke exports FOCUS_COMPONENT="recovery" (short form);
        # ADR-0066 long form is "recovery_workflow". Welle-5 smoke
        # exports FOCUS_COMPONENT="fsm" (short form); ADR-0066 long
        # form is "lifecycle_state_machine". We accept either short-
        # or long-form for these two wellen.
        focus_component = getattr(slot.smoke_module, "FOCUS_COMPONENT", None)
        focus_env_var = getattr(slot.smoke_module, "FOCUS_ENV_VAR", None)

        assert focus_component is not None, (
            f"welle {slot.welle_number} smoke missing FOCUS_COMPONENT"
        )
        assert focus_env_var is not None, (
            f"welle {slot.welle_number} smoke missing FOCUS_ENV_VAR"
        )

        # Accept short/long-form synonyms for welle-5 (fsm) and welle-7
        # (recovery) per the ADR-0066 §Beschluss table.
        synonyms = {
            "lifecycle_state_machine": ("fsm", "lifecycle_state_machine"),
            "recovery_workflow": ("recovery", "recovery_workflow"),
        }
        expected_names = synonyms.get(slot.modul, (slot.modul,))
        assert focus_component in expected_names, (
            f"welle {slot.welle_number} smoke FOCUS_COMPONENT='{focus_component}'"
            f" does not match Reihenfolge slot.modul='{slot.modul}'"
            f" (synonyms: {expected_names})"
        )

        # ENV-var must match the Reihenfolge declaration byte-for-byte.
        assert focus_env_var == slot.env_var, (
            f"welle {slot.welle_number} smoke FOCUS_ENV_VAR='{focus_env_var}'"
            f" does not match Reihenfolge slot.env_var='{slot.env_var}'"
        )


def test_substrate_engine_boot_components_strictly_grow_or_stay_across_wellen() -> None:
    """The ENGINE_BOOT_COMPONENTS inventory across the seven smokes must
    be **monotone non-decreasing** as the cutover-marathon progresses
    (welle-1 -> welle-7). Earlier wellen may know fewer components if
    later wave's resolvers had not yet landed in baseline; later wellen
    must include every component their predecessors knew about.

    This is the substrate-level guarantee that the marathon-trace does
    not silently lose a component between wellen — which would mean a
    component is no longer steerable mid-marathon, a Phase-3-final-
    regression-blocker.
    """
    seen_components: set[str] = set()
    for slot in ADR_0066_REIHENFOLGE:
        inventory = getattr(slot.smoke_module, "ENGINE_BOOT_COMPONENTS", ())
        inventory_set = set(inventory)
        # Every prior welle's component must still appear in this welle's
        # inventory (monotone non-decreasing).
        missing = seen_components - inventory_set
        assert not missing, (
            f"welle {slot.welle_number} inventory drops components from"
            f" prior wellen: missing={sorted(missing)}"
        )
        seen_components |= inventory_set

    # At end of marathon, the union must include all seven focus-moduln
    # (accounting for the recovery/recovery_workflow + fsm/
    # lifecycle_state_machine short-form synonyms).
    short_form_synonyms = {
        "lifecycle_state_machine": "fsm",
        "recovery_workflow": "recovery",
    }
    for slot in ADR_0066_REIHENFOLGE:
        canonical = short_form_synonyms.get(slot.modul, slot.modul)
        assert canonical in seen_components, (
            f"focus-modul {canonical} (welle {slot.welle_number}) missing"
            f" from end-of-marathon inventory union"
        )


def test_substrate_all_smokes_expose_tri_state_exit_codes() -> None:
    """Per-Welle smokes use the ``EXIT_GREEN / EXIT_CAUTION / EXIT_ROLLBACK``
    tri-state exit-code contract documented in each smoke's header. The
    Phase-3-final-regression aggregator depends on the values being
    uniform across the seven smokes (0, 1, 2 respectively); otherwise a
    welle's "caution" exit would be mis-aggregated as the marathon
    verdict.

    This is a static contract check — the constants must align.
    """
    for slot in ADR_0066_REIHENFOLGE:
        exit_green = getattr(slot.smoke_module, "EXIT_GREEN", None)
        exit_caution = getattr(slot.smoke_module, "EXIT_CAUTION", None)
        exit_rollback = getattr(slot.smoke_module, "EXIT_ROLLBACK", None)

        assert exit_green == 0, (
            f"welle {slot.welle_number} EXIT_GREEN must be 0; got {exit_green}"
        )
        assert exit_caution == 1, (
            f"welle {slot.welle_number} EXIT_CAUTION must be 1; got {exit_caution}"
        )
        assert exit_rollback == 2, (
            f"welle {slot.welle_number} EXIT_ROLLBACK must be 2; got {exit_rollback}"
        )


def test_substrate_all_smokes_share_phase_pre_post_rollback_constants() -> None:
    """All seven smokes carry the ``PHASE_PRE``, ``PHASE_POST``, and
    ``PHASE_ROLLBACK`` labels — these label the three test-phases in
    each smoke's envelope. The Phase-3-final-regression aggregator
    consumes these labels to bucket per-Welle measurements; drift here
    means a per-Welle envelope cannot be merged into the marathon-trace.

    The exact label-strings may differ slightly per Welle (e.g.
    ``"pre_cutover_python_baseline"`` vs ``"pre_cutover_kw_26_terminal"``)
    but the substrate-level requirement is that each smoke exposes
    *three* such constants.
    """
    for slot in ADR_0066_REIHENFOLGE:
        phase_pre = getattr(slot.smoke_module, "PHASE_PRE", None)
        phase_post = getattr(slot.smoke_module, "PHASE_POST", None)
        phase_rollback = getattr(slot.smoke_module, "PHASE_ROLLBACK", None)

        assert phase_pre is not None, (
            f"welle {slot.welle_number} smoke missing PHASE_PRE"
        )
        assert phase_post is not None, (
            f"welle {slot.welle_number} smoke missing PHASE_POST"
        )
        assert phase_rollback is not None, (
            f"welle {slot.welle_number} smoke missing PHASE_ROLLBACK"
        )

        # All three labels must be non-empty strings.
        for label_name, label_value in (
            ("PHASE_PRE", phase_pre),
            ("PHASE_POST", phase_post),
            ("PHASE_ROLLBACK", phase_rollback),
        ):
            assert isinstance(label_value, str) and label_value, (
                f"welle {slot.welle_number} {label_name} must be"
                f" non-empty str; got {label_value!r}"
            )

        # All three must be distinct (else two phases collapse into one).
        assert len({phase_pre, phase_post, phase_rollback}) == 3, (
            f"welle {slot.welle_number} PHASE_PRE/POST/ROLLBACK must"
            f" be three distinct labels"
        )


# ---------------------------------------------------------------------------
# EXTENDED — additional cascade + verdict edge-cases
# ---------------------------------------------------------------------------


def test_extended_marker_verdict_serialises_to_audit_trail_compatible_payload() -> None:
    """The :class:`Phase3CompleteMarkerVerdict` dataclass must serialise
    to a stdlib-only payload-shape that the Tomás Tag-40 Marker-Workflow
    can write into the WAT-anchor audit-trail (i.e. all fields are
    JSON-serialisable without custom encoders).

    This is the contract-shape test for the audit-trail wire-up: the
    Marker-Workflow consumes this verdict and emits a single-line JSON
    record to the audit-stream. Drift in the verdict struct surfaces
    here as an audit-trail-incompatible payload.
    """
    import json as _stdlib_json
    from dataclasses import asdict

    markers = _build_all_green_markers()
    we_gates = _build_all_green_welle_ende_gates()
    sm = Phase3CompleteMarkerStateMachine(markers, we_gates)
    verdict = sm.compute_verdict()

    # asdict + json.dumps must round-trip without TypeError.
    payload = asdict(verdict)
    serialised = _stdlib_json.dumps(payload, sort_keys=True)
    round_trip = _stdlib_json.loads(serialised)

    # Required audit-trail fields (per Tomás Tag-40 Marker-Workflow contract):
    expected_fields = {
        "phase_3_complete",
        "signoff_count",
        "cross_review_consensus",
        "welle_ende_complete",
        "drift_aggregation_verdict",
        "cascade_blocked",
        "blocking_reasons",
    }
    assert set(round_trip.keys()) == expected_fields, (
        f"verdict payload-shape drift: expected {expected_fields},"
        f" got {set(round_trip.keys())}"
    )
    assert round_trip["phase_3_complete"] is True
    assert round_trip["signoff_count"] == 7
    assert round_trip["drift_aggregation_verdict"] == "green"
    assert round_trip["cascade_blocked"] is False
    assert round_trip["blocking_reasons"] == []


def test_extended_drift_aggregation_single_caution_does_not_block_marker() -> None:
    """A single ``"caution"`` drift-assert across the seven wellen is
    not a marker-blocker — the Phase-3-COMPLETE marker still fires,
    but the aggregated verdict surfaces ``"caution"`` for downstream
    Operator-Hand triage (e.g. Henrik audit-sample focus).

    Only ``"blocker"`` aggregation cancels the marker; the operator can
    proceed on caution if the welle's own AC-1..AC-5 are green and
    cross-review consented.
    """
    markers = _build_all_green_markers()
    # Caution on multiple wellen — should still allow marker to fire.
    for w in (2, 4, 6):
        markers[w] = SignOffMarker(
            welle_number=w,
            status="signed-off",
            ac_1_5_green=True,
            ac_4_consensus_personas=ADR_0065_AC_4_PERSONAS,
            cross_welle_drift_assert="caution",
        )
    sm = Phase3CompleteMarkerStateMachine(
        markers, _build_all_green_welle_ende_gates()
    )
    verdict = sm.compute_verdict()
    assert verdict.phase_3_complete is True
    assert verdict.drift_aggregation_verdict == "caution"
    # blocking_reasons must NOT mention drift (only blocker blocks).
    assert not any(
        "drift-aggregation" in r.lower() for r in verdict.blocking_reasons
    )


def test_extended_full_cascade_all_seven_rolled_back_yields_signoff_zero() -> None:
    """Worst-case cascade: all seven wellen rolled-back (full Phase-3
    abort). The state-machine must surface signoff_count=0,
    cascade_blocked=True, phase_3_complete=False, and the drift
    aggregation must be "blocker" (every welle's rollback carries a
    drift-blocker that motivated the rollback).
    """
    markers: Dict[int, SignOffMarker] = {}
    for slot in ADR_0066_REIHENFOLGE:
        markers[slot.welle_number] = SignOffMarker(
            welle_number=slot.welle_number,
            status="rolled-back",
            ac_1_5_green=False,
            ac_4_consensus_personas=frozenset(),
            cross_welle_drift_assert="blocker",
        )
    # Welle-Ende gates would not be green either in a full-abort scenario.
    we_gates = {gate: False for gate in WELLE_ENDE_GATES}
    sm = Phase3CompleteMarkerStateMachine(markers, we_gates)
    verdict = sm.compute_verdict()

    assert verdict.signoff_count == 0
    assert verdict.phase_3_complete is False
    assert verdict.cascade_blocked is True
    assert verdict.drift_aggregation_verdict == "blocker"
    assert verdict.welle_ende_complete is False
    assert verdict.cross_review_consensus is False
    # All five blocker-reasons must surface (count, AC-1..5, AC-4, WE,
    # cascade, drift-blocker — total 6).
    assert len(verdict.blocking_reasons) >= 5, (
        f"full-cascade verdict must surface all blocking-reasons; got"
        f" {verdict.blocking_reasons}"
    )


# ---------------------------------------------------------------------------
# TIMING — Marathon-trace timing + signoff-order invariants
# ---------------------------------------------------------------------------


def _parse_iso(iso: str) -> Tuple[int, ...]:
    """Tiny stdlib-only ISO-8601 parser for the marathon-trace timestamps.

    Returns a sortable tuple ``(year, month, day, hour, minute, second)``.
    Sufficient for the marathon-trace's narrow shape; not a general
    ISO-8601 implementation.
    """
    # Strip timezone (we always use +02:00 in this suite).
    main = iso.split("+", 1)[0]
    date_part, time_part = main.split("T")
    year, month, day = (int(x) for x in date_part.split("-"))
    hour, minute, second = (int(x) for x in time_part.split(":"))
    return (year, month, day, hour, minute, second)


def test_timing_each_welle_signoff_iso_is_after_its_cutover_iso() -> None:
    """For every KW in the marathon-trace, the signoff ISO must be
    strictly after the cutover ISO (Freitag > Mittwoch within the same
    KW). A welle cannot be signed off before its cutover-step ran.
    """
    for row in MARATHON_TRACE_TIMESTAMPS:
        kw, mittwoch_iso, donnerstag_iso, freitag_iso = row
        mw = _parse_iso(mittwoch_iso)
        do = _parse_iso(donnerstag_iso)
        fr = _parse_iso(freitag_iso)
        assert mw < do < fr, (
            f"KW-{kw} timing violation: cutover ({mittwoch_iso}) ->"
            f" review ({donnerstag_iso}) -> signoff ({freitag_iso})"
            f" must be strictly increasing"
        )


def test_timing_doppel_welle_partners_share_kw_cutover_and_signoff_iso() -> None:
    """For each Doppel-Welle (DW-1+2, DW-4+5, DW-6+7), both partner
    wellen share the same KW + cutover/review/signoff timestamps.
    Welle-3 (KW-25 solo) has its own distinct timestamps."""
    markers = _build_all_green_markers()
    doppel_pairs = [(1, 2), (4, 5), (6, 7)]
    for a, b in doppel_pairs:
        slot_a = ADR_0066_REIHENFOLGE[a - 1]
        slot_b = ADR_0066_REIHENFOLGE[b - 1]
        assert slot_a.kw == slot_b.kw, (
            f"DW partners ({a}, {b}) must share KW; got"
            f" {slot_a.kw} vs {slot_b.kw}"
        )
        assert markers[a].cutover_iso == markers[b].cutover_iso, (
            f"DW partners ({a}, {b}) must share cutover_iso"
        )
        assert markers[a].signoff_iso == markers[b].signoff_iso, (
            f"DW partners ({a}, {b}) must share signoff_iso"
        )

    # Welle-3 solo timestamps must differ from both DW-1+2 and DW-4+5.
    welle_3 = markers[3]
    welle_1 = markers[1]
    welle_4 = markers[4]
    assert welle_3.cutover_iso != welle_1.cutover_iso
    assert welle_3.cutover_iso != welle_4.cutover_iso
    assert welle_3.signoff_iso != welle_1.signoff_iso
    assert welle_3.signoff_iso != welle_4.signoff_iso


def test_timing_solo_welle_3_kw_25_strictly_between_dw_1_2_and_dw_4_5() -> None:
    """KW-25 Solo-Welle-3 cutover_iso must strictly be between the DW-1+2
    KW-24 signoff_iso and the DW-4+5 KW-26 cutover_iso.

    This is the marathon-cadence invariant: Welle-3 cannot start before
    DW-1+2 signs off, and DW-4+5 cannot start before Welle-3 signs off.
    """
    markers = _build_all_green_markers()
    dw_12_signoff = _parse_iso(markers[1].signoff_iso)
    welle_3_cutover = _parse_iso(markers[3].cutover_iso)
    welle_3_signoff = _parse_iso(markers[3].signoff_iso)
    dw_45_cutover = _parse_iso(markers[4].cutover_iso)
    dw_67_cutover = _parse_iso(markers[6].cutover_iso)

    assert dw_12_signoff < welle_3_cutover, (
        "Welle-3 cutover must follow DW-1+2 signoff"
    )
    assert welle_3_signoff < dw_45_cutover, (
        "DW-4+5 cutover must follow Welle-3 signoff"
    )
    assert _parse_iso(markers[4].signoff_iso) < dw_67_cutover, (
        "DW-6+7 cutover must follow DW-4+5 signoff"
    )


def test_timing_marathon_trace_total_span_matches_adr_0066_four_weeks() -> None:
    """The marathon-trace spans exactly four KWs (24 -> 27 inclusive),
    and each consecutive Mittwoch cutover is exactly 7 days after the
    previous Mittwoch cutover. This is the ADR-0066 §Beschluss four-
    Wochen-Cadence invariant.
    """
    cutover_isos = [row[1] for row in MARATHON_TRACE_TIMESTAMPS]
    assert len(cutover_isos) == 4

    # Each consecutive Mittwoch is 7 days after the previous.
    # Stdlib-only: use datetime to compute the delta.
    from datetime import datetime

    parsed = [
        datetime.fromisoformat(iso.replace("+02:00", "+02:00"))
        for iso in cutover_isos
    ]
    for i in range(1, len(parsed)):
        delta = parsed[i] - parsed[i - 1]
        assert delta.days == 7, (
            f"consecutive Mittwoch cutovers must be 7 days apart;"
            f" got {delta.days} days between {cutover_isos[i - 1]}"
            f" and {cutover_isos[i]}"
        )

    # Total marathon span: KW-24 Mittwoch -> KW-27 Freitag = 3 weeks
    # + 2 days = 23 days.
    first_cutover = parsed[0]
    last_signoff = datetime.fromisoformat(
        MARATHON_TRACE_TIMESTAMPS[-1][3].replace("+02:00", "+02:00")
    )
    span = last_signoff - first_cutover
    assert span.days == 23, (
        f"marathon total span must be 23 days (KW-24 Mi -> KW-27 Fr);"
        f" got {span.days} days"
    )
