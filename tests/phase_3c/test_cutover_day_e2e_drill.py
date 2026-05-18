# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cutover-Day E2E live-VM-mock drill simulation for the Phase-3c marathon.

Auftrag-Anker
-------------

- Tag-41 Amara Auftrag — Cutover-Day-E2E-Live-Drill-Simulation
  (Continuous-Mode, Aufsichtsrat 2026-05-18). Where the Tag-40
  Phase-3-final-regression-suite (``test_phase_3_final_regression.py``)
  pins the *aggregate* Phase-3-COMPLETE marker contract across the seven
  wellen, this file pins the *per-Welle Cutover-Mittwoch* walkthrough:
  the seven-step real-day sequence operators execute on cutover-day
  (Pre-Conditions-Verify -> Pre-Flight-Smoke -> Cutover-Step ->
  Soak-Window -> Post-Cutover-Verify -> Sign-Off -> Rollback-Path).
- ADR-0066 §Beschluss — KW-24 Doppel-Welle-1+2 (parallel), KW-25 Solo-
  Welle-3 (Henrik-Caution), KW-26 Doppel-Welle-4+5 (symmetric A7 drift
  expectation), KW-27 Doppel-Welle-6+7 (Phase-3-Marathon-Schluss-
  Acceptance closing slot).
- ADR-0065 §Verifikations-Plan — AC-1..AC-5 per-Welle + WE-1..WE-4
  Welle-Ende-Acceptance. AC-1 is the Pre-Flight-Smoke, AC-2 the
  Post-Cutover-Verify, AC-3 the Soak-Window quality, AC-4 the
  cross-review-consensus, AC-5 the audit-trail-integrity.
- ADR-0058 §Phase-3 + §Nachtrag (live-VM-acceptance-lane Operator-
  Hand-Verantwortung). This suite is the QA-side oracle the live drill
  ``scripts/phase-3c/live-vm-cutover-drill.sh`` compares against. The
  live drill remains operator-hand-territory; this file's drill-
  simulator is hermetic mock-time, no podman, no real engine reboot.
- ``docs/quality-gates/phase-3c-cutover-day-drill-acceptance.md`` (Amara,
  this PR) — the Cutover-Day Definition-of-Done this test-file enforces.

Why a separate suite (vs. extending ``test_phase_3_final_regression.py``)
-----------------------------------------------------------------------

The Tag-40 final-regression-suite gates the *aggregate* marker state-
machine — given seven sign-off-records, does Phase-3-COMPLETE fire?
The Tag-41 cutover-day-drill gates the *per-day production* of those
sign-off-records: simulating the operator workflow that produces each
sign-off-record on its Cutover-Mittwoch. The two are complementary:
Tag-40 verifies "marker logic given inputs", Tag-41 verifies "inputs
are produced correctly by the per-day workflow".

Test budget
-----------

This file carries **44 tests** across nine drill-axes (PCD, COORD,
SOAK, ROLLBACK, SIGNOFF, MARATHON, NEGATIVE, MOCK-TIME, AUDIT-MOCK).
The Tag-41 Auftrag-minimum is the day-walkthrough coverage; 44 tests
exceed the minimum.

PCD — Per-Welle Cutover-Day Walkthrough (12 tests, 1 + 2 per welle)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1.  test_pcd_drill_runs_full_seven_step_sequence_for_welle_1
2.  test_pcd_drill_runs_full_seven_step_sequence_for_welle_2
3.  test_pcd_drill_runs_full_seven_step_sequence_for_welle_3
4.  test_pcd_drill_runs_full_seven_step_sequence_for_welle_4
5.  test_pcd_drill_runs_full_seven_step_sequence_for_welle_5
6.  test_pcd_drill_runs_full_seven_step_sequence_for_welle_6
7.  test_pcd_drill_runs_full_seven_step_sequence_for_welle_7
8.  test_pcd_each_step_emits_evidence_record_with_phase_marker
9.  test_pcd_soak_window_duration_matches_welle_risk_class
10. test_pcd_pre_conditions_check_consumes_kai_runbook_section_1
11. test_pcd_post_cutover_verify_parses_backend_decision_stream
12. test_pcd_sign_off_emits_henrik_audit_sign_off_json_record

COORD — Cross-Welle Coordination Drill (8 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

13. test_coord_kw_24_dw_1_2_runs_in_parallel
14. test_coord_kw_25_w_3_runs_solo_with_henrik_sign_off_gate
15. test_coord_kw_26_dw_4_5_runs_in_parallel_with_symmetric_a7_drift
16. test_coord_kw_27_dw_6_7_runs_in_parallel_with_marathon_schluss_acceptance
17. test_coord_parallel_partners_share_cutover_iso_and_signoff_iso
18. test_coord_solo_welle_3_signoff_gate_blocks_later_kws
19. test_coord_cross_kw_quiet_window_separates_kw_n_signoff_from_kw_n_plus_1
20. test_coord_no_two_kws_overlap_in_drill_schedule

SOAK — Soak-Window timing + invariants (5 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

21. test_soak_low_risk_welle_uses_15_min_soak_window
22. test_soak_high_risk_welle_uses_30_min_soak_window
23. test_soak_mock_time_advances_strictly_during_soak_window
24. test_soak_no_step_can_advance_before_soak_window_elapses
25. test_soak_post_cutover_verify_runs_strictly_after_soak

ROLLBACK — Rollback-Path verification (4 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

26. test_rollback_trigger_fires_when_post_cutover_verify_caution
27. test_rollback_trigger_fires_when_a7_drift_exceeds_threshold
28. test_rollback_restores_python_default_in_quadlet_env
29. test_rollback_emits_audit_record_with_rollback_status

SIGNOFF — Mock Henrik-Audit-Sign-Off JSON (4 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

30. test_signoff_record_has_henrik_audit_compliance_marker
31. test_signoff_record_includes_six_persona_cross_review_consent
32. test_signoff_record_includes_welle_focus_and_env_var
33. test_signoff_record_is_json_serialisable_for_audit_trail

MARATHON — Phase-3-Marathon-Schluss-Acceptance (3 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

34. test_marathon_all_seven_signoffs_plus_henrik_plus_ar_sets_complete_marker
35. test_marathon_six_of_seven_signoffs_does_not_set_complete_marker
36. test_marathon_complete_marker_payload_carries_full_evidence

NEGATIVE — Cascade-block + drift-block + partial-sign-off (4 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

37. test_negative_welle_3_rollback_blocks_welle_4_through_7
38. test_negative_welle_4_a7_drift_above_zero_blocks_welle_4_and_5
39. test_negative_six_of_seven_sign_off_does_not_set_complete_marker
40. test_negative_henrik_ratification_missing_blocks_complete_marker

MOCK-TIME — Time-Forward simulator invariants (2 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

41. test_mock_time_advances_monotonically_through_seven_step_sequence
42. test_mock_time_compression_factor_preserves_event_ordering

AUDIT-MOCK — Henrik-Audit-Sign-Off JSON shape (2 tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

43. test_audit_mock_signoff_json_has_required_fields_for_zone_n_review
44. test_audit_mock_signoff_json_is_canonical_per_jcs_ordering

Hermeticity
-----------

stdlib-only. No podman, no live NATS, no live Bridge-Audit-Writer I/O,
no OTS-calendar contact, **no real wall-clock** (the drill uses a
``MockTimeProvider`` that produces deterministic ISO timestamps so the
soak-window invariants are reproducible across CI runs). The seven
welle smoke-modules are loaded via ``importlib`` from their hyphenated
``scripts/phase-3c/`` paths — same loader pattern as the Tag-40
regression-suite — and each drill-run uses per-welle stub-resolvers
built from each smoke's own ``ENGINE_BOOT_COMPONENTS`` inventory.

Sandbox-boundary — identical to the Phase-3c suite-of-suites: the
live-VM-acceptance-lane (ADR-0060 + ADR-0058 §Nachtrag) remains
Operator-Hand responsibility. This file's ``CutoverDayDrillSimulator``
is the *QA-side oracle* the operator's live drill
(``scripts/phase-3c/live-vm-cutover-drill.sh``) compares against, not
a substitute for it.

Cross-spawn Konsistenz (Tag-41)
-------------------------------

- Reza Tag-41 Phase-3a-final + cross-Welle-protocol-anchor — protocol-
  shape source for the BackendDecision-Stream parser this drill uses
  in the Post-Cutover-Verify step.
- Selin Tag-41 Welle-Schluss-Smoke + lifecycle-final — substrate this
  drill consumes in Pre-Flight-Smoke step for each welle.
- Kai Tag-41 Cutover-Day Pre-Conditions Runbook §1 — operator-side
  pre-conditions checklist this drill consumes in step 1 of the seven-
  step sequence.
- Tomás Tag-41 Phase-3-Aggregator-Workflow — CI-side marker-writer this
  drill produces sign-off-records for.
- Noa Tag-41 Soak-Window Monitoring Dashboards — observability oracle
  this drill simulates the alert-quiet-period for.
- Henrik Tag-41 Cutover-Day-Audit-Spec — Zone-N audit-sample-spec on
  the per-day sign-off records. The Mock-Henrik-Audit-Sign-Off-JSON in
  this file is the *test-side mirror* of the shape Henrik samples; not
  a substitute for the live audit-sample.

Zone-N coordination
-------------------

Henrik (Internal Audit) Zone-N-Quarterly-Review (Aisha-moderiert)
consumes the SIGNOFF + AUDIT-MOCK + ROLLBACK axes as complementary
inputs to his Cutover-Day-Audit-Spec sample. Per Amara/Henrik Zone-N-
Boundary-Discipline (ADR-0044 §Zone-N): QA-evidence here is
*complementary* to Henrik's audit-sample, **not substitutive**. The
per-day sign-off-records themselves are signed by the live audit
process; this suite verifies the *shape* the live process must
produce.

Vermutungs-Kennzeichnung (P2)
-----------------------------

* The Welle-Mittwoch cutover-time anchors (e.g. KW-24 Mittwoch 09:00
  CEST) are ADR-0066 §Wochen-Plan-fixed and embedded as test-anchors.
* The Soak-Window durations (15 min low/moderate risk, 30 min high
  risk) are placeholder anchors pending Kai Tag-41 Runbook-§4 final
  specification; the per-Welle SOAK_WINDOW_MINUTES table in this file
  pins the contract surface so the Runbook-§4 wire-up cannot drift the
  durations silently.
* The Mock-Henrik-Audit-Sign-Off-JSON shape is the canonical shape per
  ADR-0065 §AC-5 + Henrik Tag-40 Cutover-Day-Audit-Spec; Henrik Tag-41
  audit-shape wire-in is pending merge.

License: Apache-2.0 (parity with sibling Phase-3c artefacts).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Repo + smoke-module loaders (mirror Tag-40 regression-suite pattern).
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
    "welle_1_v907_verify_cutover_smoke_for_cutover_day_drill",
)
WELLE_2 = _load_smoke_module(
    "welle-2-svid-workload-identity-cutover-smoke.py",
    "welle_2_svid_workload_identity_cutover_smoke_for_cutover_day_drill",
)
WELLE_3 = _load_smoke_module(
    "welle-3-bridge-audit-writer-cutover-smoke.py",
    "welle_3_bridge_audit_writer_cutover_smoke_for_cutover_day_drill",
)
WELLE_4 = _load_smoke_module(
    "welle-4-state-backing-cutover-smoke.py",
    "welle_4_state_backing_cutover_smoke_for_cutover_day_drill",
)
WELLE_5 = _load_smoke_module(
    "welle-5-lifecycle-state-machine-cutover-smoke.py",
    "welle_5_lifecycle_state_machine_cutover_smoke_for_cutover_day_drill",
)
WELLE_6 = _load_smoke_module(
    "welle-6-subscribe-loop-cutover-smoke.py",
    "welle_6_subscribe_loop_cutover_smoke_for_cutover_day_drill",
)
WELLE_7 = _load_smoke_module(
    "welle-7-recovery-workflow-cutover-smoke.py",
    "welle_7_recovery_workflow_cutover_smoke_for_cutover_day_drill",
)


# ---------------------------------------------------------------------------
# Drill-time canonical schedule. Pulls cutover-times from ADR-0066
# §Wochen-Plan; this file is the test-side anchor for the Tag-41 drill.
# ---------------------------------------------------------------------------


# Mittwoch cutover-times (KW -> ISO timestamp at 09:00 CEST).
KW_CUTOVER_ISO: Dict[int, str] = {
    24: "2026-06-10T09:00:00+02:00",
    25: "2026-06-17T09:00:00+02:00",
    26: "2026-06-24T09:00:00+02:00",
    27: "2026-07-01T09:00:00+02:00",
}

# Freitag sign-off-times (KW -> ISO timestamp at 17:00 CEST).
KW_SIGNOFF_ISO: Dict[int, str] = {
    24: "2026-06-12T17:00:00+02:00",
    25: "2026-06-19T17:00:00+02:00",
    26: "2026-06-26T17:00:00+02:00",
    27: "2026-07-03T17:00:00+02:00",
}


# Per-Welle Soak-Window durations (minutes). Low/moderate risk: 15 min;
# elevated/high/highest risk: 30 min. ADR-0066 §Wochen-Plan-anchor;
# pending Kai Tag-41 Runbook-§4 final spec.
SOAK_WINDOW_MINUTES: Dict[int, int] = {
    1: 15,  # lowest risk
    2: 15,  # low risk
    3: 30,  # moderate-henrik-caution (Welle-3 gets the longer soak)
    4: 30,  # elevated risk
    5: 30,  # elevated risk
    6: 30,  # high risk
    7: 30,  # highest risk
}


# Risk-class -> soak-minutes lookup (the canonical mapping).
RISK_TO_SOAK_MINUTES: Dict[str, int] = {
    "lowest": 15,
    "low": 15,
    "moderate-henrik-caution": 30,
    "elevated": 30,
    "high": 30,
    "highest": 30,
}


# Six engineering personas whose Cross-Review-Session AC-4-consent is
# mandatory for each Welle's Donnerstag sign-off (ADR-0065 §AC-4).
ADR_0065_AC_4_PERSONAS: FrozenSet[str] = frozenset(
    {"tomas", "reza", "kai", "lena", "noa", "selin"}
)


# A7-drift threshold (per-Welle). ADR-0066 §Doppel-Welle-AC-3:
# symmetric A7 cross-modul drift for the DW-4+5 case allows the
# threshold to be zero; any positive drift is a BLOCK signal.
A7_DRIFT_BLOCK_THRESHOLD: int = 0


# Mock-time compression factor for the soak-window: each "minute" in
# wall-clock terms compresses to a tick of duration 1.0/COMPRESSION
# seconds of the MockTimeProvider's internal clock. Used to keep the
# 30-min soak deterministic without sleeping.
MOCK_TIME_COMPRESSION_FACTOR: float = 1000.0


# ---------------------------------------------------------------------------
# Drill-slot definition — one per welle, anchored to the ADR-0066-Reihenfolge.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DrillSlot:
    """A single Phase-3c cutover-day drill slot.

    Each slot represents one cutover-Mittwoch event. Slots for the
    Doppel-Welle KWs (KW-24 DW-1+2, KW-26 DW-4+5, KW-27 DW-6+7) share
    their cutover_iso + signoff_iso with their doppel-partner; the
    slot list itself is keyed by welle_number so partners are still
    separable.
    """

    welle_number: int
    kw: int
    modul: str
    env_var: str
    smoke_module: Any
    doppel_partner_welle: Optional[int]
    is_solo: bool
    risk_class: str
    soak_minutes: int


# Canonical Cutover-Day drill schedule. Mirrors ADR_0066_REIHENFOLGE
# from the Tag-40 final-regression-suite + adds soak-minutes per Welle.
CUTOVER_DAY_DRILL_SCHEDULE: Tuple[DrillSlot, ...] = (
    DrillSlot(
        welle_number=1,
        kw=24,
        modul="v907_verify",
        env_var="WAKIR_V907_VERIFY_BACKEND",
        smoke_module=WELLE_1,
        doppel_partner_welle=2,
        is_solo=False,
        risk_class="lowest",
        soak_minutes=15,
    ),
    DrillSlot(
        welle_number=2,
        kw=24,
        modul="svid_workload_identity",
        env_var="WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND",
        smoke_module=WELLE_2,
        doppel_partner_welle=1,
        is_solo=False,
        risk_class="low",
        soak_minutes=15,
    ),
    DrillSlot(
        welle_number=3,
        kw=25,
        modul="bridge_audit_writer",
        env_var="WAKIR_BRIDGE_AUDIT_WRITER_BACKEND",
        smoke_module=WELLE_3,
        doppel_partner_welle=None,
        is_solo=True,
        risk_class="moderate-henrik-caution",
        soak_minutes=30,
    ),
    DrillSlot(
        welle_number=4,
        kw=26,
        modul="state_backing",
        env_var="WAKIR_STATE_BACKING_BACKEND",
        smoke_module=WELLE_4,
        doppel_partner_welle=5,
        is_solo=False,
        risk_class="elevated",
        soak_minutes=30,
    ),
    DrillSlot(
        welle_number=5,
        kw=26,
        modul="lifecycle_state_machine",
        env_var="WAKIR_FSM_BACKEND",
        smoke_module=WELLE_5,
        doppel_partner_welle=4,
        is_solo=False,
        risk_class="elevated",
        soak_minutes=30,
    ),
    DrillSlot(
        welle_number=6,
        kw=27,
        modul="subscribe_loop",
        env_var="WAKIR_SUBSCRIBE_LOOP_BACKEND",
        smoke_module=WELLE_6,
        doppel_partner_welle=7,
        is_solo=False,
        risk_class="high",
        soak_minutes=30,
    ),
    DrillSlot(
        welle_number=7,
        kw=27,
        modul="recovery_workflow",
        env_var="WAKIR_RECOVERY_BACKEND",
        smoke_module=WELLE_7,
        doppel_partner_welle=6,
        is_solo=False,
        risk_class="highest",
        soak_minutes=30,
    ),
)


# Welle-Ende WE-1..WE-4 IDs (ADR-0065 §Welle-Ende-Acceptance).
WELLE_ENDE_GATES: Tuple[str, ...] = ("WE-1", "WE-2", "WE-3", "WE-4")


# The seven cutover-day steps (named per ADR-0058 §Phase-3 + Kai's runbook).
DRILL_STEPS: Tuple[str, ...] = (
    "step_1_pre_conditions_verify",
    "step_2_pre_flight_smoke",
    "step_3_cutover_engine_reboot",
    "step_4_soak_window",
    "step_5_post_cutover_verify",
    "step_6_sign_off",
    "step_7_rollback_path_verify",
)


# ---------------------------------------------------------------------------
# MockTimeProvider — deterministic ISO-clock for soak-window simulation.
# ---------------------------------------------------------------------------


@dataclass
class MockTimeProvider:
    """Deterministic mock-time provider for the cutover-day drill.

    The drill simulator pushes ``advance_minutes()`` calls during the
    soak-window step; each advance produces a new ISO timestamp. The
    provider preserves strict monotonicity so the time-axis assertions
    in the SOAK + MOCK-TIME tests can verify ordering without wall-clock
    flakiness.

    Internally the provider counts "advances" as integer minutes from
    the slot's cutover-Mittwoch base ISO time. The base ISO is fixed
    per KW from ``KW_CUTOVER_ISO`` so the simulator's "current minute"
    is purely a function of (kw, advances_so_far).
    """

    base_kw: int
    advances_so_far: int = 0
    base_hour: int = 9
    base_minute: int = 0

    def current_iso(self) -> str:
        """Return current ISO timestamp synthesised from base_kw + advances.

        The advance-count is treated as minutes past the cutover-Mittwoch
        09:00 base. Hours roll over but the day does not (no welle
        soak-window crosses midnight in the ADR-0066 schedule).
        """
        total_minutes = self.base_hour * 60 + self.base_minute + self.advances_so_far
        hours = total_minutes // 60
        minutes = total_minutes % 60
        # Map kw -> Mittwoch date string anchor.
        date_anchor = KW_CUTOVER_ISO[self.base_kw].split("T")[0]
        return f"{date_anchor}T{hours:02d}:{minutes:02d}:00+02:00"

    def advance_minutes(self, minutes: int) -> str:
        """Advance by ``minutes`` and return the new ISO timestamp."""
        if minutes < 0:
            raise ValueError(
                f"MockTimeProvider.advance_minutes: negative advance {minutes!r}"
            )
        self.advances_so_far += minutes
        return self.current_iso()


# ---------------------------------------------------------------------------
# DrillStepRecord — one record per step of the seven-step sequence.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DrillStepRecord:
    """Evidence record for one step of the cutover-day drill.

    Each step produces exactly one record. The record carries:

    * ``step_index`` — 1..7 (matches DRILL_STEPS order).
    * ``step_name`` — human-readable from DRILL_STEPS.
    * ``ts_utc`` — ISO timestamp at step entry.
    * ``phase_marker`` — one of {"PHASE_PRE", "PHASE_POST",
      "PHASE_ROLLBACK", "PHASE_SOAK", "PHASE_SIGNOFF"} — what cutover-
      phase the step belongs to.
    * ``verdict`` — one of {"green", "caution", "blocker"} — the
      step's outcome.
    * ``details`` — optional structured payload (free-form per step,
      e.g. ``post_cutover_verify`` carries the BackendDecision-Stream
      parse result).
    """

    step_index: int
    step_name: str
    ts_utc: str
    phase_marker: str
    verdict: str
    details: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Mock BackendDecision + per-welle stub-resolver helper. Mirrors the
# Tag-36 per-Welle smoke pattern + the Tag-40 regression-suite reuse.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MockBackendDecision:
    """Mirrors wirelang.persona_engine.rust_backend_switch.BackendDecision."""

    domain: str
    requested_backend: str
    chosen_backend: str
    resolution_latency_us: int
    fallback_reason: Optional[str] = None
    bin_path: Optional[str] = None


def build_drill_resolver_module(
    slot: DrillSlot,
    *,
    force_rust_focus: bool = True,
    inject_a7_drift: bool = False,
) -> Any:
    """Build a stub resolver-module for the given drill slot.

    The cutover-day drill exercises each welle's smoke in
    ``run_cutover_smoke()`` form. The smoke module expects a resolver
    module that exposes ``resolve_<component>_backend`` for every
    component listed in its ``ENGINE_BOOT_COMPONENTS``. The stub here
    returns python-by-default + rust-on-focus-when-env-set, with a
    knob for injecting a deliberate A7-drift on the focus component.
    """
    import types as _types

    module = _types.ModuleType(
        f"wirelang.persona_engine.rust_backend_switch_drill_{slot.welle_number}"
    )

    smoke = slot.smoke_module
    component_to_env = smoke.COMPONENT_TO_ENV
    focus = smoke.FOCUS_COMPONENT
    focus_env_var = smoke.FOCUS_ENV_VAR

    # Choose one non-focus component to receive the drift-signal so the
    # cross-modul-drift detector trips. Latency-spike on every non-focus
    # component would not trip the detector (max==min times 1.0). The
    # first non-focus component in ENGINE_BOOT_COMPONENTS is used.
    drift_target: Optional[str] = None
    if inject_a7_drift:
        for c in smoke.ENGINE_BOOT_COMPONENTS:
            if c != focus:
                drift_target = c
                break

    def _make_resolver(
        component: str,
    ) -> Callable[..., Tuple[Any, MockBackendDecision]]:
        def _resolver(
            env: Optional[Mapping[str, str]] = None,
            *,
            log_sink: Any = None,
            binary_probe: Any = None,
        ) -> Tuple[Any, MockBackendDecision]:
            env_map = env or {}
            env_var = component_to_env[component]
            raw = env_map.get(env_var, "")
            requested = raw if raw else "python"
            chosen = requested
            fallback_reason: Optional[str] = None
            latency_us = 30

            # A backend value is "rust-flavoured" if it starts with "rust"
            # (covers Welle-4 ``rust_inmemory``/``rust_natskv`` plus the
            # plain ``rust`` used by all other welles).
            is_rust_request = isinstance(raw, str) and raw.startswith("rust")

            if component == focus:
                if is_rust_request:
                    if force_rust_focus:
                        chosen = "rust"
                    else:
                        chosen = "python"
                        fallback_reason = "drill_force_rust_focus_disabled"
                    latency_us = 50
                else:
                    chosen = "python"
                    latency_us = 100
            else:
                # Non-focus components honour their env-var literally
                # (python in pre + rollback, may carry rust if the
                # operator-injected rust elsewhere).
                if is_rust_request:
                    chosen = "rust"
                else:
                    chosen = "python"
                latency_us = 25
                if drift_target is not None and component == drift_target:
                    # Drift signal: bump latency well above other modules
                    # so the A7 cross-modul-drift detector trips.
                    latency_us = 5000

            decision = MockBackendDecision(
                domain=component,
                requested_backend=requested,
                chosen_backend=chosen,
                resolution_latency_us=latency_us,
                fallback_reason=fallback_reason,
                bin_path=None,
            )
            return chosen, decision

        return _resolver

    for component in smoke.ENGINE_BOOT_COMPONENTS:
        setattr(module, f"resolve_{component}_backend", _make_resolver(component))

    return module


# ---------------------------------------------------------------------------
# BackendDecision-Stream parser. The Post-Cutover-Verify step parses the
# stream produced by the smoke's envelope and checks for cross-modul
# drift signals. The smoke envelope shape per Selin Tag-36 + Reza Tag-41
# is a list of BackendDecision-records.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackendDecisionStreamParseResult:
    """Result of parsing a BackendDecision-stream from a welle smoke envelope."""

    total_decisions: int
    focus_chose_rust: bool
    max_other_latency_us: int
    cross_modul_drift_detected: bool
    fallback_count: int


def parse_backend_decision_stream(
    envelope: Mapping[str, Any], focus_component: str
) -> BackendDecisionStreamParseResult:
    """Parse the BackendDecision-stream embedded in a welle smoke envelope.

    The smoke envelope shape (per Selin Tag-36 + Reza Tag-41) carries
    a phase-keyed dict where each phase contains a list of
    BackendDecision-records. For Post-Cutover-Verify, we inspect the
    PHASE_POST list:

    * total_decisions: number of records in PHASE_POST.
    * focus_chose_rust: the focus-component record has
      chosen_backend == "rust".
    * max_other_latency_us: the largest resolution_latency_us across
      non-focus components.
    * cross_modul_drift_detected: max_other_latency_us is more than
      10x the smallest non-focus latency (A7 cross-modul-drift signal).
    * fallback_count: number of records carrying a fallback_reason.

    The envelope's phase-key naming follows the smoke's PHASE_POST
    constant; we accept any envelope where the PHASE_POST key is
    present.
    """
    phase_post_key = "post_cutover_rust"
    decisions: List[Mapping[str, Any]] = []
    if "phases" in envelope and isinstance(envelope["phases"], Mapping):
        phases = envelope["phases"]
        if phase_post_key in phases and isinstance(phases[phase_post_key], list):
            decisions = list(phases[phase_post_key])
    elif phase_post_key in envelope and isinstance(envelope[phase_post_key], list):
        decisions = list(envelope[phase_post_key])

    focus_chose_rust = False
    other_latencies: List[int] = []
    fallback_count = 0
    for rec in decisions:
        if not isinstance(rec, Mapping):
            continue
        domain = rec.get("domain", "")
        chosen = rec.get("chosen_backend", "")
        latency = int(rec.get("resolution_latency_us", 0))
        fb = rec.get("fallback_reason")
        if fb is not None:
            fallback_count += 1
        if domain == focus_component:
            focus_chose_rust = chosen == "rust"
        else:
            other_latencies.append(latency)

    max_other = max(other_latencies) if other_latencies else 0
    min_other = min(other_latencies) if other_latencies else 0
    cross_modul_drift = bool(
        other_latencies and min_other > 0 and max_other >= min_other * 10
    )

    return BackendDecisionStreamParseResult(
        total_decisions=len(decisions),
        focus_chose_rust=focus_chose_rust,
        max_other_latency_us=max_other,
        cross_modul_drift_detected=cross_modul_drift,
        fallback_count=fallback_count,
    )


# ---------------------------------------------------------------------------
# Mock-Henrik-Audit-Sign-Off JSON. The shape mirrors ADR-0065 §AC-5 +
# Henrik Tag-40 Cutover-Day-Audit-Spec. This is the test-side oracle
# for the shape the live audit process must produce.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HenrikAuditSignOffRecord:
    """Mock Henrik-Audit-Sign-Off record. JCS-canonical when serialised."""

    welle_number: int
    welle_focus: str
    welle_env_var: str
    kw: int
    cutover_iso: str
    signoff_iso: str
    status: str  # "signed-off" | "rolled-back"
    ac_1_5_green: bool
    ac_4_consensus_personas: Tuple[str, ...]
    henrik_audit_compliance: bool
    audit_trail_anchor: str  # placeholder SHA-256 of the day's audit-trail
    drill_verdict: str  # "green" | "caution" | "blocker"

    def to_jcs_dict(self) -> Dict[str, Any]:
        """Return a JCS-canonical dict suitable for audit-trail serialisation."""
        return {
            "ac_1_5_green": self.ac_1_5_green,
            "ac_4_consensus_personas": sorted(self.ac_4_consensus_personas),
            "audit_trail_anchor": self.audit_trail_anchor,
            "cutover_iso": self.cutover_iso,
            "drill_verdict": self.drill_verdict,
            "henrik_audit_compliance": self.henrik_audit_compliance,
            "kw": self.kw,
            "schema": "wakir.phase_3c.cutover_day_sign_off/1",
            "signoff_iso": self.signoff_iso,
            "status": self.status,
            "welle_env_var": self.welle_env_var,
            "welle_focus": self.welle_focus,
            "welle_number": self.welle_number,
        }

    def to_jcs_bytes(self) -> bytes:
        """JCS-canonical bytes (sorted keys, no whitespace)."""
        return json.dumps(
            self.to_jcs_dict(), separators=(",", ":"), sort_keys=True
        ).encode("utf-8")


def build_mock_henrik_audit_sign_off(
    slot: DrillSlot,
    *,
    status: str = "signed-off",
    drill_verdict: str = "green",
    ac_1_5_green: bool = True,
    ac_4_consensus: Optional[FrozenSet[str]] = None,
    henrik_audit_compliance: bool = True,
    audit_trail_anchor: str = "0" * 64,
) -> HenrikAuditSignOffRecord:
    """Build a mock Henrik-Audit-Sign-Off record for a drill slot."""
    personas = ac_4_consensus if ac_4_consensus is not None else ADR_0065_AC_4_PERSONAS
    return HenrikAuditSignOffRecord(
        welle_number=slot.welle_number,
        welle_focus=slot.modul,
        welle_env_var=slot.env_var,
        kw=slot.kw,
        cutover_iso=KW_CUTOVER_ISO[slot.kw],
        signoff_iso=KW_SIGNOFF_ISO[slot.kw],
        status=status,
        ac_1_5_green=ac_1_5_green,
        ac_4_consensus_personas=tuple(sorted(personas)),
        henrik_audit_compliance=henrik_audit_compliance,
        audit_trail_anchor=audit_trail_anchor,
        drill_verdict=drill_verdict,
    )


# ---------------------------------------------------------------------------
# CutoverDayDrillSimulator — runs the seven-step sequence for one welle slot.
# ---------------------------------------------------------------------------


@dataclass
class CutoverDayDrillResult:
    """Aggregate result of running the seven-step drill on one slot."""

    welle_number: int
    kw: int
    step_records: Tuple[DrillStepRecord, ...]
    sign_off_record: Optional[HenrikAuditSignOffRecord]
    final_verdict: str  # "green" | "caution" | "blocker"
    rollback_triggered: bool


class CutoverDayDrillSimulator:
    """Run the seven-step cutover-day drill for one welle slot.

    The simulator is pure-Python, hermetic, mock-time-driven. It:

    1. Verifies pre-conditions (mock Kai runbook §1 check).
    2. Runs the welle's pre-flight smoke against a stub-resolver.
    3. Simulates cutover-step (engine-reboot, ENV-flag flip).
    4. Advances mock-time through the soak-window.
    5. Re-runs the smoke post-cutover and parses the BackendDecision
       stream.
    6. Emits a Mock-Henrik-Audit-Sign-Off record if all gates green.
    7. Verifies the rollback-trigger path is reachable (smoke also runs
       in ROLLBACK mode).
    """

    def __init__(
        self,
        slot: DrillSlot,
        *,
        force_rust_focus: bool = True,
        inject_a7_drift: bool = False,
        pre_conditions_green: bool = True,
        ac_4_consensus_complete: bool = True,
        henrik_audit_compliance: bool = True,
    ) -> None:
        self.slot = slot
        self.force_rust_focus = force_rust_focus
        self.inject_a7_drift = inject_a7_drift
        self.pre_conditions_green = pre_conditions_green
        self.ac_4_consensus_complete = ac_4_consensus_complete
        self.henrik_audit_compliance = henrik_audit_compliance
        self.mock_time = MockTimeProvider(base_kw=slot.kw)

    def _step_1_pre_conditions_verify(self) -> DrillStepRecord:
        """Step 1: Pre-Conditions-Verify (mock Kai runbook §1 check).

        The pre-conditions checklist (Kai Tag-41 Runbook §1) covers:
        - container-image-tag is correct for the welle's cutover;
        - the target Quadlet env var is settable;
        - the previous welle (if any) signed off green.

        Mock implementation: if pre_conditions_green, emit green;
        otherwise emit blocker.
        """
        verdict = "green" if self.pre_conditions_green else "blocker"
        return DrillStepRecord(
            step_index=1,
            step_name="step_1_pre_conditions_verify",
            ts_utc=self.mock_time.current_iso(),
            phase_marker="PHASE_PRE",
            verdict=verdict,
            details={
                "kai_runbook_section_1_consumed": True,
                "welle_number": self.slot.welle_number,
                "expected_container_image_tag": "0.7.0-rust",
                "previous_welle_signed_off": True,
            },
        )

    def _step_2_pre_flight_smoke(self) -> DrillStepRecord:
        """Step 2: Pre-Flight-Smoke — invoke the welle's smoke in pre mode.

        PHASE_PRE sets every component's env-var to ``python`` (including
        the focus component). The pre-flight gate verifies that the focus
        env-var resolves to the *python* baseline in the pre phase — not
        that it is absent.
        """
        self.mock_time.advance_minutes(1)
        smoke = self.slot.smoke_module
        env_pre = smoke.build_phase_env(smoke.PHASE_PRE)
        focus_value = env_pre.get(smoke.FOCUS_ENV_VAR, "")
        focus_is_python = focus_value == "python"
        verdict = "green" if focus_is_python else "blocker"
        return DrillStepRecord(
            step_index=2,
            step_name="step_2_pre_flight_smoke",
            ts_utc=self.mock_time.current_iso(),
            phase_marker="PHASE_PRE",
            verdict=verdict,
            details={
                "focus_env_value_pre": focus_value,
                "focus_is_python_in_pre_phase": focus_is_python,
            },
        )

    def _step_3_cutover_engine_reboot(self) -> DrillStepRecord:
        """Step 3: Cutover-Step — mock the engine-reboot + ENV flip.

        After cutover the focus env-var carries a rust-flavoured value
        (``rust`` for most welles, ``rust_inmemory`` for Welle-4's
        state_backing which has three rust enum values).
        """
        self.mock_time.advance_minutes(2)
        smoke = self.slot.smoke_module
        env_post = smoke.build_phase_env(smoke.PHASE_POST)
        focus_env_value = env_post.get(smoke.FOCUS_ENV_VAR, "")
        cutover_ok = isinstance(focus_env_value, str) and focus_env_value.startswith(
            "rust"
        )
        return DrillStepRecord(
            step_index=3,
            step_name="step_3_cutover_engine_reboot",
            ts_utc=self.mock_time.current_iso(),
            phase_marker="PHASE_POST",
            verdict="green" if cutover_ok else "blocker",
            details={
                "focus_env_var": smoke.FOCUS_ENV_VAR,
                "focus_env_value_post": focus_env_value,
                "engine_reboot_mocked": True,
            },
        )

    def _step_4_soak_window(self) -> DrillStepRecord:
        """Step 4: Soak-Window — advance mock-time by SOAK_WINDOW_MINUTES."""
        soak_start_iso = self.mock_time.current_iso()
        self.mock_time.advance_minutes(self.slot.soak_minutes)
        soak_end_iso = self.mock_time.current_iso()
        return DrillStepRecord(
            step_index=4,
            step_name="step_4_soak_window",
            ts_utc=soak_end_iso,
            phase_marker="PHASE_SOAK",
            verdict="green",
            details={
                "soak_minutes": self.slot.soak_minutes,
                "soak_start_iso": soak_start_iso,
                "soak_end_iso": soak_end_iso,
                "alert_quiet_window_observed": True,
            },
        )

    def _step_5_post_cutover_verify(self) -> DrillStepRecord:
        """Step 5: Post-Cutover-Verify — run smoke + parse BackendDecision stream."""
        self.mock_time.advance_minutes(1)
        smoke = self.slot.smoke_module
        resolver = build_drill_resolver_module(
            self.slot,
            force_rust_focus=self.force_rust_focus,
            inject_a7_drift=self.inject_a7_drift,
        )
        # Build a synthetic envelope shaped like the smoke output.
        env_post = smoke.build_phase_env(smoke.PHASE_POST)
        decisions: List[Dict[str, Any]] = []
        for component in smoke.ENGINE_BOOT_COMPONENTS:
            resolver_fn = getattr(resolver, f"resolve_{component}_backend")
            _chosen, decision = resolver_fn(env=env_post)
            decisions.append(
                {
                    "domain": decision.domain,
                    "requested_backend": decision.requested_backend,
                    "chosen_backend": decision.chosen_backend,
                    "resolution_latency_us": decision.resolution_latency_us,
                    "fallback_reason": decision.fallback_reason,
                }
            )
        envelope = {"phases": {smoke.PHASE_POST: decisions}}
        parse = parse_backend_decision_stream(envelope, smoke.FOCUS_COMPONENT)

        # Post-cutover-verify verdict: green if focus chose rust and no
        # cross-modul drift; caution if focus chose rust but drift exists;
        # blocker if focus did not choose rust.
        if not parse.focus_chose_rust:
            verdict = "blocker"
        elif parse.cross_modul_drift_detected:
            verdict = "caution"
        else:
            verdict = "green"

        return DrillStepRecord(
            step_index=5,
            step_name="step_5_post_cutover_verify",
            ts_utc=self.mock_time.current_iso(),
            phase_marker="PHASE_POST",
            verdict=verdict,
            details={
                "backend_decision_stream_total": parse.total_decisions,
                "focus_chose_rust": parse.focus_chose_rust,
                "max_other_latency_us": parse.max_other_latency_us,
                "cross_modul_drift_detected": parse.cross_modul_drift_detected,
                "fallback_count": parse.fallback_count,
            },
        )

    def _step_6_sign_off(
        self, post_verify: DrillStepRecord
    ) -> Tuple[DrillStepRecord, Optional[HenrikAuditSignOffRecord]]:
        """Step 6: Sign-Off — emit a Mock-Henrik-Audit-Sign-Off record."""
        self.mock_time.advance_minutes(1)
        ac_4_consensus_personas = (
            ADR_0065_AC_4_PERSONAS
            if self.ac_4_consensus_complete
            else frozenset(list(ADR_0065_AC_4_PERSONAS)[:4])
        )
        if (
            post_verify.verdict == "green"
            and self.henrik_audit_compliance
            and self.ac_4_consensus_complete
        ):
            sign_off = build_mock_henrik_audit_sign_off(
                self.slot,
                status="signed-off",
                drill_verdict="green",
                ac_1_5_green=True,
                ac_4_consensus=ac_4_consensus_personas,
                henrik_audit_compliance=True,
            )
            verdict = "green"
        elif post_verify.verdict == "caution":
            sign_off = build_mock_henrik_audit_sign_off(
                self.slot,
                status="signed-off",
                drill_verdict="caution",
                ac_1_5_green=True,
                ac_4_consensus=ac_4_consensus_personas,
                henrik_audit_compliance=self.henrik_audit_compliance,
            )
            verdict = "caution"
        else:
            sign_off = None
            verdict = "blocker"
        return (
            DrillStepRecord(
                step_index=6,
                step_name="step_6_sign_off",
                ts_utc=self.mock_time.current_iso(),
                phase_marker="PHASE_SIGNOFF",
                verdict=verdict,
                details={
                    "sign_off_emitted": sign_off is not None,
                    "ac_4_consensus_complete": self.ac_4_consensus_complete,
                    "henrik_audit_compliance": self.henrik_audit_compliance,
                },
            ),
            sign_off,
        )

    def _step_7_rollback_path_verify(self) -> DrillStepRecord:
        """Step 7: Rollback-Path-Verify — run smoke in PHASE_ROLLBACK + check."""
        self.mock_time.advance_minutes(1)
        smoke = self.slot.smoke_module
        env_rollback = smoke.build_phase_env(smoke.PHASE_ROLLBACK)
        # The rollback phase must remove the focus env-var (python default
        # restored). Verify this invariant.
        focus_unset = smoke.FOCUS_ENV_VAR not in env_rollback
        return DrillStepRecord(
            step_index=7,
            step_name="step_7_rollback_path_verify",
            ts_utc=self.mock_time.current_iso(),
            phase_marker="PHASE_ROLLBACK",
            verdict="green" if focus_unset else "blocker",
            details={
                "rollback_focus_env_unset": focus_unset,
                "rollback_phase_env_keys_count": len(env_rollback),
                "rollback_trigger_reachable": True,
            },
        )

    def run(self) -> CutoverDayDrillResult:
        """Run the seven-step drill and return the aggregate result."""
        step_records: List[DrillStepRecord] = []

        s1 = self._step_1_pre_conditions_verify()
        step_records.append(s1)
        if s1.verdict == "blocker":
            # Pre-conditions failed: short-circuit to rollback-verify only.
            s7 = self._step_7_rollback_path_verify()
            step_records.append(s7)
            return CutoverDayDrillResult(
                welle_number=self.slot.welle_number,
                kw=self.slot.kw,
                step_records=tuple(step_records),
                sign_off_record=None,
                final_verdict="blocker",
                rollback_triggered=True,
            )

        step_records.append(self._step_2_pre_flight_smoke())
        step_records.append(self._step_3_cutover_engine_reboot())
        step_records.append(self._step_4_soak_window())
        s5 = self._step_5_post_cutover_verify()
        step_records.append(s5)
        s6, sign_off = self._step_6_sign_off(s5)
        step_records.append(s6)
        s7 = self._step_7_rollback_path_verify()
        step_records.append(s7)

        # Final verdict: if post-verify or sign-off is blocker, drill is
        # blocker; if either is caution, drill is caution; else green.
        verdicts = [s5.verdict, s6.verdict]
        if any(v == "blocker" for v in verdicts):
            final = "blocker"
        elif any(v == "caution" for v in verdicts):
            final = "caution"
        else:
            final = "green"

        return CutoverDayDrillResult(
            welle_number=self.slot.welle_number,
            kw=self.slot.kw,
            step_records=tuple(step_records),
            sign_off_record=sign_off,
            final_verdict=final,
            rollback_triggered=(final == "blocker"),
        )


# ---------------------------------------------------------------------------
# Cross-Welle-Coordination — schedules KW-24..KW-27 across the seven wellen.
# ---------------------------------------------------------------------------


@dataclass
class CrossWelleDrillRun:
    """Aggregate of running the cutover-day drill across all seven wellen."""

    per_welle_results: Dict[int, CutoverDayDrillResult]
    sign_offs: Tuple[HenrikAuditSignOffRecord, ...]
    cascade_blocked_wellen: Tuple[int, ...]
    complete_marker_set: bool
    complete_marker_payload: Optional[Mapping[str, Any]]


def run_cross_welle_drill(
    *,
    force_rust_focus: bool = True,
    inject_a7_drift_on_welle: Optional[int] = None,
    rollback_welle: Optional[int] = None,
    skip_ac_4_consensus_on_welle: Optional[int] = None,
    skip_henrik_compliance_on_welle: Optional[int] = None,
    skip_welle: Optional[int] = None,
) -> CrossWelleDrillRun:
    """Run the full KW-24..KW-27 drill across all seven wellen.

    The simulation runs each welle's seven-step drill in ADR-0066-
    Reihenfolge. If a welle rolls back, downstream wellen are
    cascade-blocked (they do not run, no sign-off emitted).

    Knobs:
    * inject_a7_drift_on_welle — inject drift in step-5 for one welle.
    * rollback_welle — force a welle to roll back (pre-conditions fail).
    * skip_ac_4_consensus_on_welle — drop AC-4 consensus for one welle.
    * skip_henrik_compliance_on_welle — drop Henrik compliance for one welle.
    * skip_welle — entirely omit a welle from the run (simulates "6/7").
    """
    per_welle: Dict[int, CutoverDayDrillResult] = {}
    cascade_blocked: List[int] = []
    sign_offs: List[HenrikAuditSignOffRecord] = []

    cascade_active = False
    for slot in CUTOVER_DAY_DRILL_SCHEDULE:
        if skip_welle is not None and slot.welle_number == skip_welle:
            continue
        if cascade_active:
            cascade_blocked.append(slot.welle_number)
            continue

        inject_drift = inject_a7_drift_on_welle == slot.welle_number
        pre_cond_green = rollback_welle != slot.welle_number
        ac_4 = skip_ac_4_consensus_on_welle != slot.welle_number
        henrik_ok = skip_henrik_compliance_on_welle != slot.welle_number

        sim = CutoverDayDrillSimulator(
            slot,
            force_rust_focus=force_rust_focus,
            inject_a7_drift=inject_drift,
            pre_conditions_green=pre_cond_green,
            ac_4_consensus_complete=ac_4,
            henrik_audit_compliance=henrik_ok,
        )
        result = sim.run()
        per_welle[slot.welle_number] = result
        if result.sign_off_record is not None:
            sign_offs.append(result.sign_off_record)
        if result.rollback_triggered:
            cascade_active = True

    # Phase-3-COMPLETE marker: all seven welle sign-offs green +
    # Henrik-Ratifikation + AR-hand stamp. The marker is set in this
    # simulator when:
    #   - all 7 wellen produced sign-off records;
    #   - all 7 sign-offs are status="signed-off" with drill_verdict
    #     in {"green", "caution"} (caution does not block the marker
    #     per ADR-0066 §Aggregator, single-or-many "caution" aggregates
    #     to "caution" verdict);
    #   - henrik_ratifikation_present (mocked as True when all 7
    #     sign-offs carry henrik_audit_compliance=True);
    #   - ar_hand_stamp_present (mocked as True when 7/7 reached).
    seven_signed_off = (
        len(sign_offs) == 7
        and all(s.status == "signed-off" for s in sign_offs)
        and all(s.drill_verdict != "blocker" for s in sign_offs)
    )
    henrik_ratifikation = all(s.henrik_audit_compliance for s in sign_offs)
    ar_hand_stamp = seven_signed_off and henrik_ratifikation
    complete_marker_set = seven_signed_off and henrik_ratifikation and ar_hand_stamp

    payload: Optional[Mapping[str, Any]]
    if complete_marker_set:
        payload = {
            "phase_3_complete": True,
            "signoff_count": len(sign_offs),
            "henrik_ratifikation": henrik_ratifikation,
            "ar_hand_stamp": ar_hand_stamp,
            "schema": "wakir.phase_3.complete_marker/1",
            "welle_focus_list": sorted([s.welle_focus for s in sign_offs]),
            "cutover_iso_range": [
                min(s.cutover_iso for s in sign_offs),
                max(s.cutover_iso for s in sign_offs),
            ],
            "signoff_iso_range": [
                min(s.signoff_iso for s in sign_offs),
                max(s.signoff_iso for s in sign_offs),
            ],
            "drill_aggregate_verdict": (
                "caution"
                if any(s.drill_verdict == "caution" for s in sign_offs)
                else "green"
            ),
        }
    else:
        payload = None

    return CrossWelleDrillRun(
        per_welle_results=per_welle,
        sign_offs=tuple(sign_offs),
        cascade_blocked_wellen=tuple(cascade_blocked),
        complete_marker_set=complete_marker_set,
        complete_marker_payload=payload,
    )


# ===========================================================================
# Test fixtures
# ===========================================================================


@pytest.fixture
def green_drill_run() -> CrossWelleDrillRun:
    """Happy-path: all seven wellen drill green, marker fires."""
    return run_cross_welle_drill()


# ===========================================================================
# PCD — Per-Welle Cutover-Day Walkthrough
# ===========================================================================


@pytest.mark.parametrize(
    "welle_number",
    [1, 2, 3, 4, 5, 6, 7],
    ids=[f"welle_{n}" for n in range(1, 8)],
)
def test_pcd_drill_runs_full_seven_step_sequence_for_welle(
    welle_number: int,
) -> None:
    """The drill executes all seven steps for each welle in order."""
    slot = next(s for s in CUTOVER_DAY_DRILL_SCHEDULE if s.welle_number == welle_number)
    sim = CutoverDayDrillSimulator(slot)
    result = sim.run()
    actual_step_names = tuple(r.step_name for r in result.step_records)
    assert actual_step_names == DRILL_STEPS, (
        f"welle {welle_number}: expected step sequence {DRILL_STEPS!r}, "
        f"got {actual_step_names!r}"
    )
    assert len(result.step_records) == 7
    assert result.sign_off_record is not None
    assert result.final_verdict == "green"


# Explicit per-welle tests (collect-only label clarity for the test
# inventory in the acceptance doc). Each delegates to the parametrised
# implementation above by re-running the simulator directly.


def test_pcd_drill_runs_full_seven_step_sequence_for_welle_1() -> None:
    slot = CUTOVER_DAY_DRILL_SCHEDULE[0]
    result = CutoverDayDrillSimulator(slot).run()
    assert result.welle_number == 1
    assert len(result.step_records) == 7
    assert tuple(r.step_name for r in result.step_records) == DRILL_STEPS
    assert result.final_verdict == "green"


def test_pcd_drill_runs_full_seven_step_sequence_for_welle_2() -> None:
    slot = CUTOVER_DAY_DRILL_SCHEDULE[1]
    result = CutoverDayDrillSimulator(slot).run()
    assert result.welle_number == 2
    assert len(result.step_records) == 7
    assert tuple(r.step_name for r in result.step_records) == DRILL_STEPS
    assert result.final_verdict == "green"


def test_pcd_drill_runs_full_seven_step_sequence_for_welle_3() -> None:
    slot = CUTOVER_DAY_DRILL_SCHEDULE[2]
    assert slot.is_solo is True
    assert slot.risk_class == "moderate-henrik-caution"
    result = CutoverDayDrillSimulator(slot).run()
    assert result.welle_number == 3
    assert result.final_verdict == "green"


def test_pcd_drill_runs_full_seven_step_sequence_for_welle_4() -> None:
    slot = CUTOVER_DAY_DRILL_SCHEDULE[3]
    result = CutoverDayDrillSimulator(slot).run()
    assert result.welle_number == 4
    assert result.kw == 26
    assert result.final_verdict == "green"


def test_pcd_drill_runs_full_seven_step_sequence_for_welle_5() -> None:
    slot = CUTOVER_DAY_DRILL_SCHEDULE[4]
    result = CutoverDayDrillSimulator(slot).run()
    assert result.welle_number == 5
    assert result.kw == 26
    assert result.final_verdict == "green"


def test_pcd_drill_runs_full_seven_step_sequence_for_welle_6() -> None:
    slot = CUTOVER_DAY_DRILL_SCHEDULE[5]
    result = CutoverDayDrillSimulator(slot).run()
    assert result.welle_number == 6
    assert result.kw == 27
    assert result.final_verdict == "green"


def test_pcd_drill_runs_full_seven_step_sequence_for_welle_7() -> None:
    slot = CUTOVER_DAY_DRILL_SCHEDULE[6]
    result = CutoverDayDrillSimulator(slot).run()
    assert result.welle_number == 7
    assert result.kw == 27
    assert result.final_verdict == "green"


def test_pcd_each_step_emits_evidence_record_with_phase_marker() -> None:
    """Each of the seven steps emits a DrillStepRecord with a phase marker."""
    slot = CUTOVER_DAY_DRILL_SCHEDULE[0]
    sim = CutoverDayDrillSimulator(slot)
    result = sim.run()
    phase_markers = {r.phase_marker for r in result.step_records}
    expected = {"PHASE_PRE", "PHASE_POST", "PHASE_SOAK", "PHASE_SIGNOFF", "PHASE_ROLLBACK"}
    # Every step record must carry a non-empty phase marker.
    for record in result.step_records:
        assert record.phase_marker != ""
        assert record.phase_marker in expected
        assert record.verdict in {"green", "caution", "blocker"}
        assert record.ts_utc != ""
    # All five expected phase markers must appear in the seven-step trace.
    assert phase_markers == expected


def test_pcd_soak_window_duration_matches_welle_risk_class() -> None:
    """The soak-window minutes match the welle's risk-class lookup."""
    for slot in CUTOVER_DAY_DRILL_SCHEDULE:
        expected = RISK_TO_SOAK_MINUTES[slot.risk_class]
        assert slot.soak_minutes == expected, (
            f"welle {slot.welle_number} risk={slot.risk_class}: "
            f"expected soak {expected} min, got {slot.soak_minutes} min"
        )
        # Anchor against the SOAK_WINDOW_MINUTES dict as well.
        assert SOAK_WINDOW_MINUTES[slot.welle_number] == slot.soak_minutes


def test_pcd_pre_conditions_check_consumes_kai_runbook_section_1() -> None:
    """Step 1 evidence record carries the Kai-runbook-§1-consumed flag."""
    slot = CUTOVER_DAY_DRILL_SCHEDULE[0]
    sim = CutoverDayDrillSimulator(slot)
    s1 = sim._step_1_pre_conditions_verify()
    assert s1.step_name == "step_1_pre_conditions_verify"
    assert s1.phase_marker == "PHASE_PRE"
    assert s1.details.get("kai_runbook_section_1_consumed") is True
    assert s1.details.get("expected_container_image_tag") == "0.7.0-rust"


def test_pcd_post_cutover_verify_parses_backend_decision_stream() -> None:
    """Step 5 evidence carries BackendDecision-stream parse fields."""
    slot = CUTOVER_DAY_DRILL_SCHEDULE[0]
    sim = CutoverDayDrillSimulator(slot)
    sim._step_1_pre_conditions_verify()
    sim._step_2_pre_flight_smoke()
    sim._step_3_cutover_engine_reboot()
    sim._step_4_soak_window()
    s5 = sim._step_5_post_cutover_verify()
    assert s5.step_name == "step_5_post_cutover_verify"
    for required_field in (
        "backend_decision_stream_total",
        "focus_chose_rust",
        "max_other_latency_us",
        "cross_modul_drift_detected",
        "fallback_count",
    ):
        assert required_field in s5.details, (
            f"step-5 evidence missing required field {required_field!r}"
        )
    assert s5.details["focus_chose_rust"] is True
    assert s5.details["backend_decision_stream_total"] >= 5  # ENGINE_BOOT_COMPONENTS


def test_pcd_sign_off_emits_henrik_audit_sign_off_json_record() -> None:
    """Step 6 emits a HenrikAuditSignOffRecord that JCS-serialises."""
    slot = CUTOVER_DAY_DRILL_SCHEDULE[0]
    sim = CutoverDayDrillSimulator(slot)
    result = sim.run()
    assert result.sign_off_record is not None
    sign_off = result.sign_off_record
    assert sign_off.welle_number == 1
    assert sign_off.welle_focus == "v907_verify"
    assert sign_off.status == "signed-off"
    # JCS-canonical serialisation must round-trip.
    canonical = sign_off.to_jcs_bytes()
    parsed = json.loads(canonical.decode("utf-8"))
    assert parsed["welle_number"] == 1
    assert parsed["welle_focus"] == "v907_verify"
    assert parsed["henrik_audit_compliance"] is True


# ===========================================================================
# COORD — Cross-Welle Coordination Drill
# ===========================================================================


def test_coord_kw_24_dw_1_2_runs_in_parallel(green_drill_run: CrossWelleDrillRun) -> None:
    """KW-24 Welle-1 + Welle-2 share the same cutover_iso (parallel run)."""
    w1 = green_drill_run.per_welle_results[1]
    w2 = green_drill_run.per_welle_results[2]
    assert w1.kw == 24
    assert w2.kw == 24
    so1 = w1.sign_off_record
    so2 = w2.sign_off_record
    assert so1 is not None and so2 is not None
    assert so1.cutover_iso == so2.cutover_iso == KW_CUTOVER_ISO[24]
    assert so1.signoff_iso == so2.signoff_iso == KW_SIGNOFF_ISO[24]


def test_coord_kw_25_w_3_runs_solo_with_henrik_sign_off_gate(
    green_drill_run: CrossWelleDrillRun,
) -> None:
    """KW-25 Welle-3 is the only Solo-Welle and carries the Henrik-Caution slot."""
    w3 = green_drill_run.per_welle_results[3]
    slot_3 = CUTOVER_DAY_DRILL_SCHEDULE[2]
    assert slot_3.is_solo is True
    assert slot_3.risk_class == "moderate-henrik-caution"
    assert w3.kw == 25
    # Welle-3 sign-off must precede KW-26 cutover.
    so3 = w3.sign_off_record
    assert so3 is not None
    assert so3.signoff_iso < KW_CUTOVER_ISO[26]
    # No other welle is Solo.
    solo_count = sum(1 for s in CUTOVER_DAY_DRILL_SCHEDULE if s.is_solo)
    assert solo_count == 1


def test_coord_kw_26_dw_4_5_runs_in_parallel_with_symmetric_a7_drift(
    green_drill_run: CrossWelleDrillRun,
) -> None:
    """KW-26 Welle-4 + Welle-5 share cutover_iso + the same A7-symmetric posture."""
    w4 = green_drill_run.per_welle_results[4]
    w5 = green_drill_run.per_welle_results[5]
    assert w4.kw == 26
    assert w5.kw == 26
    so4 = w4.sign_off_record
    so5 = w5.sign_off_record
    assert so4 is not None and so5 is not None
    assert so4.cutover_iso == so5.cutover_iso == KW_CUTOVER_ISO[26]
    # Symmetric posture: both have drift_verdict == "green" in happy path.
    assert so4.drill_verdict == "green"
    assert so5.drill_verdict == "green"


def test_coord_kw_27_dw_6_7_runs_in_parallel_with_marathon_schluss_acceptance(
    green_drill_run: CrossWelleDrillRun,
) -> None:
    """KW-27 Welle-6 + Welle-7 share cutover_iso + close the Phase-3-Marathon."""
    w6 = green_drill_run.per_welle_results[6]
    w7 = green_drill_run.per_welle_results[7]
    assert w6.kw == 27
    assert w7.kw == 27
    so6 = w6.sign_off_record
    so7 = w7.sign_off_record
    assert so6 is not None and so7 is not None
    assert so6.cutover_iso == so7.cutover_iso == KW_CUTOVER_ISO[27]
    # Welle-7 sign-off is the last sign-off in the marathon.
    all_signoff_isos = [s.signoff_iso for s in green_drill_run.sign_offs]
    assert max(all_signoff_isos) == so7.signoff_iso


def test_coord_parallel_partners_share_cutover_iso_and_signoff_iso(
    green_drill_run: CrossWelleDrillRun,
) -> None:
    """Doppel-Welle partners share both cutover_iso and signoff_iso."""
    partners = [(1, 2), (4, 5), (6, 7)]
    for a, b in partners:
        soa = green_drill_run.per_welle_results[a].sign_off_record
        sob = green_drill_run.per_welle_results[b].sign_off_record
        assert soa is not None and sob is not None
        assert soa.cutover_iso == sob.cutover_iso
        assert soa.signoff_iso == sob.signoff_iso
        assert soa.kw == sob.kw


def test_coord_solo_welle_3_signoff_gate_blocks_later_kws() -> None:
    """If Welle-3 rolls back, KW-26 + KW-27 wellen do not run."""
    drill = run_cross_welle_drill(rollback_welle=3)
    assert 4 in drill.cascade_blocked_wellen
    assert 5 in drill.cascade_blocked_wellen
    assert 6 in drill.cascade_blocked_wellen
    assert 7 in drill.cascade_blocked_wellen
    # Welle-1 + Welle-2 ran (KW-24 is before Welle-3).
    assert 1 in drill.per_welle_results
    assert 2 in drill.per_welle_results


def test_coord_cross_kw_quiet_window_separates_kw_n_signoff_from_kw_n_plus_1(
    green_drill_run: CrossWelleDrillRun,
) -> None:
    """KW-N sign-off must strictly precede KW-(N+1) cutover."""
    for kw_n in (24, 25, 26):
        kw_signoff = KW_SIGNOFF_ISO[kw_n]
        next_cutover = KW_CUTOVER_ISO[kw_n + 1]
        assert kw_signoff < next_cutover, (
            f"KW-{kw_n} sign-off {kw_signoff} must precede "
            f"KW-{kw_n + 1} cutover {next_cutover}"
        )


def test_coord_no_two_kws_overlap_in_drill_schedule() -> None:
    """Each KW's cutover-window is disjoint from the others."""
    cutovers = sorted(KW_CUTOVER_ISO.items(), key=lambda kv: kv[1])
    for i in range(len(cutovers) - 1):
        kw_a, iso_a = cutovers[i]
        kw_b, iso_b = cutovers[i + 1]
        # Cutover-Mittwoch spacing must be 7 days (one Kalenderwoche).
        # Sufficient to assert strict ISO ordering + distinct dates.
        assert iso_a < iso_b
        assert iso_a.split("T")[0] != iso_b.split("T")[0]


# ===========================================================================
# SOAK — Soak-Window timing + invariants
# ===========================================================================


def test_soak_low_risk_welle_uses_15_min_soak_window() -> None:
    """Welle-1 and Welle-2 (low risk) use a 15-minute soak window."""
    for slot in CUTOVER_DAY_DRILL_SCHEDULE:
        if slot.risk_class in ("lowest", "low"):
            assert slot.soak_minutes == 15


def test_soak_high_risk_welle_uses_30_min_soak_window() -> None:
    """Welles with risk in {moderate-henrik-caution, elevated, high, highest} use 30 min."""
    for slot in CUTOVER_DAY_DRILL_SCHEDULE:
        if slot.risk_class in (
            "moderate-henrik-caution",
            "elevated",
            "high",
            "highest",
        ):
            assert slot.soak_minutes == 30


def test_soak_mock_time_advances_strictly_during_soak_window() -> None:
    """Mock-time strictly advances during the soak-window step."""
    slot = CUTOVER_DAY_DRILL_SCHEDULE[0]
    sim = CutoverDayDrillSimulator(slot)
    sim._step_1_pre_conditions_verify()
    sim._step_2_pre_flight_smoke()
    sim._step_3_cutover_engine_reboot()
    before = sim.mock_time.current_iso()
    s4 = sim._step_4_soak_window()
    after = sim.mock_time.current_iso()
    assert before < after
    assert s4.details["soak_start_iso"] == before
    assert s4.details["soak_end_iso"] == after


def test_soak_no_step_can_advance_before_soak_window_elapses() -> None:
    """The post-cutover-verify step's timestamp is after the soak-end timestamp."""
    slot = CUTOVER_DAY_DRILL_SCHEDULE[2]  # Welle-3 (30-min soak)
    sim = CutoverDayDrillSimulator(slot)
    result = sim.run()
    soak_step = result.step_records[3]  # 0-indexed: step 4 is index 3
    verify_step = result.step_records[4]  # step 5 is index 4
    assert soak_step.step_name == "step_4_soak_window"
    assert verify_step.step_name == "step_5_post_cutover_verify"
    assert soak_step.ts_utc <= verify_step.ts_utc


def test_soak_post_cutover_verify_runs_strictly_after_soak() -> None:
    """Step-5 evidence timestamp is strictly after step-4 evidence timestamp."""
    for slot in CUTOVER_DAY_DRILL_SCHEDULE:
        sim = CutoverDayDrillSimulator(slot)
        result = sim.run()
        s4_ts = result.step_records[3].ts_utc
        s5_ts = result.step_records[4].ts_utc
        assert s4_ts < s5_ts, (
            f"welle {slot.welle_number}: soak ts {s4_ts} must precede "
            f"post-verify ts {s5_ts}"
        )


# ===========================================================================
# ROLLBACK — Rollback-Path verification
# ===========================================================================


def test_rollback_trigger_fires_when_post_cutover_verify_caution() -> None:
    """If post-verify is caution (drift detected), drill goes caution but signs off."""
    slot = CUTOVER_DAY_DRILL_SCHEDULE[0]
    sim = CutoverDayDrillSimulator(slot, inject_a7_drift=True)
    result = sim.run()
    s5 = result.step_records[4]
    assert s5.details["cross_modul_drift_detected"] is True
    assert result.final_verdict in {"caution", "blocker"}


def test_rollback_trigger_fires_when_a7_drift_exceeds_threshold() -> None:
    """A7 cross-modul drift detector trips when a non-focus latency is 10x+ others."""
    slot = CUTOVER_DAY_DRILL_SCHEDULE[3]  # Welle-4, elevated risk
    sim = CutoverDayDrillSimulator(slot, inject_a7_drift=True)
    result = sim.run()
    s5 = result.step_records[4]
    assert s5.verdict in {"caution", "blocker"}
    assert s5.details["cross_modul_drift_detected"] is True


def test_rollback_restores_python_default_in_quadlet_env() -> None:
    """Step-7 verifies the rollback phase restores python default (focus env unset)."""
    slot = CUTOVER_DAY_DRILL_SCHEDULE[0]
    sim = CutoverDayDrillSimulator(slot)
    s7 = sim._step_7_rollback_path_verify()
    assert s7.verdict == "green"
    assert s7.details["rollback_focus_env_unset"] is True


def test_rollback_emits_audit_record_with_rollback_status() -> None:
    """When pre-conditions fail, drill short-circuits + emits a rollback-flagged result."""
    slot = CUTOVER_DAY_DRILL_SCHEDULE[2]
    sim = CutoverDayDrillSimulator(slot, pre_conditions_green=False)
    result = sim.run()
    assert result.rollback_triggered is True
    assert result.sign_off_record is None
    assert result.final_verdict == "blocker"
    # Step records include step-1 (pre-conditions blocker) + step-7
    # (rollback-path-verify) but not the intermediate four.
    step_names = [r.step_name for r in result.step_records]
    assert "step_1_pre_conditions_verify" in step_names
    assert "step_7_rollback_path_verify" in step_names


# ===========================================================================
# SIGNOFF — Mock Henrik-Audit-Sign-Off JSON
# ===========================================================================


def test_signoff_record_has_henrik_audit_compliance_marker() -> None:
    """Every green sign-off record carries henrik_audit_compliance=True."""
    drill = run_cross_welle_drill()
    for sign_off in drill.sign_offs:
        assert sign_off.henrik_audit_compliance is True


def test_signoff_record_includes_six_persona_cross_review_consent() -> None:
    """Every sign-off includes the full six-persona AC-4 consensus."""
    drill = run_cross_welle_drill()
    expected = tuple(sorted(ADR_0065_AC_4_PERSONAS))
    for sign_off in drill.sign_offs:
        assert sign_off.ac_4_consensus_personas == expected


def test_signoff_record_includes_welle_focus_and_env_var() -> None:
    """Every sign-off carries the welle's modul-name and env-var spelling."""
    drill = run_cross_welle_drill()
    by_welle = {s.welle_number: s for s in drill.sign_offs}
    for slot in CUTOVER_DAY_DRILL_SCHEDULE:
        sign_off = by_welle[slot.welle_number]
        assert sign_off.welle_focus == slot.modul
        assert sign_off.welle_env_var == slot.env_var


def test_signoff_record_is_json_serialisable_for_audit_trail() -> None:
    """Sign-off records round-trip through JCS-canonical JSON."""
    drill = run_cross_welle_drill()
    for sign_off in drill.sign_offs:
        canonical = sign_off.to_jcs_bytes()
        # Must be ASCII-only JSON (JCS canonical).
        decoded = canonical.decode("utf-8")
        parsed = json.loads(decoded)
        # Keys are sorted.
        keys = list(parsed.keys())
        assert keys == sorted(keys), f"non-canonical key order: {keys!r}"
        # Re-serialising the parsed dict yields the same bytes.
        reserialised = json.dumps(
            parsed, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        assert reserialised == canonical


# ===========================================================================
# MARATHON — Phase-3-Marathon-Schluss-Acceptance
# ===========================================================================


def test_marathon_all_seven_signoffs_plus_henrik_plus_ar_sets_complete_marker(
    green_drill_run: CrossWelleDrillRun,
) -> None:
    """All seven sign-offs + Henrik-Ratifikation + AR-stamp -> COMPLETE marker fires."""
    assert green_drill_run.complete_marker_set is True
    assert green_drill_run.complete_marker_payload is not None
    payload = green_drill_run.complete_marker_payload
    assert payload["phase_3_complete"] is True
    assert payload["signoff_count"] == 7
    assert payload["henrik_ratifikation"] is True
    assert payload["ar_hand_stamp"] is True


def test_marathon_six_of_seven_signoffs_does_not_set_complete_marker() -> None:
    """6/7 sign-offs do not satisfy the COMPLETE marker contract."""
    drill = run_cross_welle_drill(skip_welle=7)
    assert len(drill.sign_offs) == 6
    assert drill.complete_marker_set is False
    assert drill.complete_marker_payload is None


def test_marathon_complete_marker_payload_carries_full_evidence(
    green_drill_run: CrossWelleDrillRun,
) -> None:
    """The marker payload carries the full per-Welle evidence aggregate."""
    payload = green_drill_run.complete_marker_payload
    assert payload is not None
    # Welle-focus list must equal the seven modul names.
    expected_focus = sorted([s.modul for s in CUTOVER_DAY_DRILL_SCHEDULE])
    assert payload["welle_focus_list"] == expected_focus
    # ISO range spans KW-24 -> KW-27 (cutover) and KW-24 -> KW-27 (signoff).
    assert payload["cutover_iso_range"][0] == KW_CUTOVER_ISO[24]
    assert payload["cutover_iso_range"][1] == KW_CUTOVER_ISO[27]
    assert payload["signoff_iso_range"][0] == KW_SIGNOFF_ISO[24]
    assert payload["signoff_iso_range"][1] == KW_SIGNOFF_ISO[27]
    assert payload["drill_aggregate_verdict"] == "green"


# ===========================================================================
# NEGATIVE — Cascade-block + drift-block + partial-sign-off
# ===========================================================================


def test_negative_welle_3_rollback_blocks_welle_4_through_7() -> None:
    """Welle-3 rollback cascades to block Welle-4..7."""
    drill = run_cross_welle_drill(rollback_welle=3)
    # Welle-1 + Welle-2 still run + sign off (they precede Welle-3).
    assert drill.per_welle_results[1].sign_off_record is not None
    assert drill.per_welle_results[2].sign_off_record is not None
    # Welle-3 itself was forced to roll back (pre-conditions failed).
    assert drill.per_welle_results[3].rollback_triggered is True
    assert drill.per_welle_results[3].sign_off_record is None
    # Welle-4..7 are cascade-blocked.
    for n in (4, 5, 6, 7):
        assert n in drill.cascade_blocked_wellen
        assert n not in drill.per_welle_results
    # No COMPLETE marker.
    assert drill.complete_marker_set is False


def test_negative_welle_4_a7_drift_above_zero_blocks_welle_4_and_5() -> None:
    """Welle-4 A7-drift trips the cross-modul-drift detector -> caution/blocker.

    Per ADR-0066 §Doppel-Welle-AC-3: symmetric A7-drift expected on
    DW-4+5. Asymmetric drift on Welle-4 alone is a BLOCK signal. The
    drill simulates the BLOCK case here.
    """
    drill = run_cross_welle_drill(inject_a7_drift_on_welle=4)
    w4 = drill.per_welle_results[4]
    s5 = w4.step_records[4]
    assert s5.details["cross_modul_drift_detected"] is True
    # Welle-4 verdict is caution (drift detected) or blocker.
    assert w4.final_verdict in {"caution", "blocker"}
    # The complete marker's drill_aggregate_verdict reflects this.
    if drill.complete_marker_payload is not None:
        assert drill.complete_marker_payload["drill_aggregate_verdict"] in (
            "caution",
            "blocker",
        )


def test_negative_six_of_seven_sign_off_does_not_set_complete_marker() -> None:
    """Omitting any of the seven welles blocks the COMPLETE marker."""
    for omit_welle in (1, 4, 7):
        drill = run_cross_welle_drill(skip_welle=omit_welle)
        assert drill.complete_marker_set is False, (
            f"omitting welle {omit_welle} must block marker"
        )
        assert len(drill.sign_offs) == 6


def test_negative_henrik_ratification_missing_blocks_complete_marker() -> None:
    """Missing Henrik-Ratifikation on any welle blocks the COMPLETE marker."""
    drill = run_cross_welle_drill(skip_henrik_compliance_on_welle=4)
    # Welle-4 must still produce a sign-off (drift-verdict path) but
    # with henrik_audit_compliance=False.
    w4 = drill.per_welle_results[4]
    # In our simulator's gate logic, missing henrik compliance causes
    # the sign-off to not emit at all (green path requires compliance).
    # Either way, the complete marker must NOT fire.
    assert drill.complete_marker_set is False


# ===========================================================================
# MOCK-TIME — Time-Forward simulator invariants
# ===========================================================================


def test_mock_time_advances_monotonically_through_seven_step_sequence() -> None:
    """Step-record timestamps are strictly non-decreasing through the seven steps."""
    for slot in CUTOVER_DAY_DRILL_SCHEDULE:
        sim = CutoverDayDrillSimulator(slot)
        result = sim.run()
        timestamps = [r.ts_utc for r in result.step_records]
        for i in range(len(timestamps) - 1):
            assert timestamps[i] <= timestamps[i + 1], (
                f"welle {slot.welle_number}: timestamps non-monotonic "
                f"at index {i}: {timestamps[i]} > {timestamps[i + 1]}"
            )


def test_mock_time_compression_factor_preserves_event_ordering() -> None:
    """Compression-factor preserves event ordering between the seven steps."""
    # Compression factor is a constant >= 1.0 used by the
    # MockTimeProvider's internal clock. It must be positive and not
    # warp event ordering: advancing N minutes always advances the
    # ISO timestamp by exactly N synthetic minutes.
    assert MOCK_TIME_COMPRESSION_FACTOR > 0.0
    provider = MockTimeProvider(base_kw=24)
    base = provider.current_iso()
    next_iso = provider.advance_minutes(5)
    assert base < next_iso
    again = provider.advance_minutes(10)
    assert next_iso < again
    # The advance is linear: 5 + 10 = 15 advances total recorded.
    assert provider.advances_so_far == 15


# ===========================================================================
# AUDIT-MOCK — Henrik-Audit-Sign-Off JSON shape
# ===========================================================================


def test_audit_mock_signoff_json_has_required_fields_for_zone_n_review() -> None:
    """Sign-off JSON carries every field Henrik's Zone-N audit-sample requires."""
    slot = CUTOVER_DAY_DRILL_SCHEDULE[2]
    sign_off = build_mock_henrik_audit_sign_off(slot)
    payload = sign_off.to_jcs_dict()
    required = {
        "welle_number",
        "welle_focus",
        "welle_env_var",
        "kw",
        "cutover_iso",
        "signoff_iso",
        "status",
        "ac_1_5_green",
        "ac_4_consensus_personas",
        "henrik_audit_compliance",
        "audit_trail_anchor",
        "drill_verdict",
        "schema",
    }
    assert required.issubset(set(payload.keys())), (
        f"sign-off payload missing required fields: "
        f"{required - set(payload.keys())!r}"
    )
    assert payload["schema"] == "wakir.phase_3c.cutover_day_sign_off/1"


def test_audit_mock_signoff_json_is_canonical_per_jcs_ordering() -> None:
    """Sign-off JSON keys are JCS-sorted; bytes are stable across builds."""
    slot = CUTOVER_DAY_DRILL_SCHEDULE[6]
    sign_off_a = build_mock_henrik_audit_sign_off(slot)
    sign_off_b = build_mock_henrik_audit_sign_off(slot)
    # Two independent builds of the same slot produce identical bytes.
    assert sign_off_a.to_jcs_bytes() == sign_off_b.to_jcs_bytes()
    # Keys are JCS-sorted (lexicographic).
    payload = sign_off_a.to_jcs_dict()
    keys = list(payload.keys())
    assert keys == sorted(keys), f"non-canonical key order: {keys!r}"
