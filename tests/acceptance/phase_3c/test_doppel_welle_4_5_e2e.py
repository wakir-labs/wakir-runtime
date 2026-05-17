# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Doppel-Welle-4+5 E2E acceptance — ``state_backing`` +
``lifecycle_state_machine`` parallel cutover (KW 26).

Anchors
-------

- ADR-0066 §Beschluss — Doppel-Welle KW 26: Welle-4 + Welle-5 parallel.
- ADR-0066 §Mitigation 1 — **Cross-Modul-Stress-Test grün vor Cutover**
  is a hard pre-requisite for Welle-4+5. Phase-2-Acceptance-Gate
  (PR #178) was extended with Cross-Modul-Stress-Test by Tomás Tag-29.
- ADR-0066 §Rollback-Strategie — bei Cross-Modul-Bug in Doppel-Wellen:
  *beide* Komponenten gleichzeitig zurück auf python-Default.
- ADR-0065 §Risiken §"Cross-Komponenten-Schema-Drift" — Welle-5 reads
  state-records that Welle-4 (Rust-state_backing) wrote; the contract
  is now *two-sided rust* under Doppel-Welle (vs. one-sided rust in
  the original ADR-0065 sequential plan).
- ``test_welle_4_state_backing_e2e.py`` + ``test_welle_5_lifecycle_state_
  machine_e2e.py`` — per-welle sister files. Welle-4 first introduces
  persistent state; Welle-5 first introduces cross-modul dependency.
  Doppel-Welle-4+5 collapses these two risk-classes into one cutover.

Doppel-Welle character — **Cross-Modul-Drift-Focus**
----------------------------------------------------

This is the **highest cross-modul-drift-risk** of the three Doppel-
Wellen, because:

1. ``state_backing`` *produces* JCS-canonicalised state-records that
   ``lifecycle_state_machine`` *consumes*. The producer/consumer
   contract is a primary drift-surface.
2. Both moduln flip to rust in the same cutover-cycle, so the
   contract is now Rust-producer × Rust-consumer (no Python-fallback
   on either side mid-Doppel-Welle).
3. The transition-table (lifecycle) interacts with the state-write-
   schema (state_backing) — drift in either layer cascades.

DW-AC-2 (Cross-Modul-Schema byte-parity) and DW-AC-4 (Cross-Modul-
Stress-Test) carry the dominant gate-weight here. Welle-1+2 had
DW-AC-1 + DW-AC-5 as primary; Welle-4+5 inverts that emphasis.
"""

from __future__ import annotations

import pytest

from ._ac_assertions import (
    assert_dw_ac_1_both_moduln_boot_rust,
    assert_dw_ac_2_cross_modul_schema_byte_parity,
    assert_dw_ac_3_asymmetric_rollback,
    assert_dw_ac_4_cross_modul_stress_test_green,
    assert_dw_ac_5_backend_decision_audit_two_records_consistent,
)
from .conftest import DOPPEL_WELLE_BY_PAIR

MODUL_A = "state_backing"
MODUL_B = "lifecycle_state_machine"
WELLE_PAIR_LABEL = f"KW26:{MODUL_A}+{MODUL_B}"
EXPECTED_KW = DOPPEL_WELLE_BY_PAIR[(MODUL_A, MODUL_B)]

pytestmark = pytest.mark.phase_3c_doppel_welle_acceptance


def test_doppel_welle_4_5_anchored_to_kw_26() -> None:
    """Sanity: this file targets the ADR-0066 KW 26 Doppel-Welle pair."""
    assert EXPECTED_KW == "KW26", (
        f"Doppel-Welle-4+5 must anchor to KW26 per ADR-0066 §Beschluss; "
        f"got {EXPECTED_KW!r}"
    )


# ---------------------------------------------------------------------------
# DW-AC-1 — Both Doppel-Welle moduln boot with rust-backend.
# ---------------------------------------------------------------------------


def test_doppel_welle_4_5_dw_ac_1_both_moduln_boot_rust(
    mocked_engine_boot_doppel,
) -> None:
    """DW-AC-1: state_backing + lifecycle_state_machine both on rust.

    Pre-Welle-3 (KW 25) is the bridge_audit_writer solo welle, so by
    KW 26 the substrate is: v907_verify + svid_workload_identity +
    bridge_audit_writer on rust (3 from prior wellen), plus the
    Doppel-Welle-4+5 pair → 5 moduln rust, 2 python.

    The Doppel-Welle boot-builder default models only the new pair;
    in production, the prior-wellen rust-flips are persisted in the
    Quadlet-ENV already.
    """
    boot = mocked_engine_boot_doppel(MODUL_A, MODUL_B)
    assert_dw_ac_1_both_moduln_boot_rust(
        boot, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
    )


def test_doppel_welle_4_5_dw_ac_1_boot_failure_blocks(
    mocked_engine_boot_doppel,
) -> None:
    """DW-AC-1 failure-mode: engine-boot fails → both rollback.

    Welle-4 first introduces state-on-disk that could outlast a
    rollback; under Doppel-Welle conditions the Schema-Migrations-
    Rollback-Plan (ADR-0065 §Rollback-Procedure §3) is a hard pre-
    requisite to a boot-failure path.
    """
    boot = mocked_engine_boot_doppel(MODUL_A, MODUL_B, boot_succeeded=False)
    with pytest.raises(AssertionError, match="DW-AC-1"):
        assert_dw_ac_1_both_moduln_boot_rust(
            boot, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# DW-AC-2 — Cross-Modul-Schema-Konsistenz (byte-paritär).
#
# DOMINANT GATE for Doppel-Welle-4+5 (Cross-Modul-Drift-Focus).
# ---------------------------------------------------------------------------


def test_doppel_welle_4_5_dw_ac_2_state_record_to_lifecycle_byte_parity(
    mocked_cross_modul_schema,
) -> None:
    """DW-AC-2: state_backing-record byte-paritär across the touchpoints
    lifecycle_state_machine reads.

    Real touchpoints (Phase-3c-trigger-sprint wiring):
    * ``tp-state-record-init`` — initial state-write by state_backing,
      lifecycle reads on persona-spawn.
    * ``tp-state-transition-write`` — lifecycle writes transition,
      state_backing persists; both sides Rust under Doppel-Welle.
    * ``tp-state-finalize`` — lifecycle marks ``archived``,
      state_backing flushes terminal record.
    * ``tp-state-recovery-readback`` — recovery_workflow path
      (Welle-7, still Python here in KW 26) reads — but the test is
      restricted to the rust-rust touchpoints in this DW.
    """
    records = mocked_cross_modul_schema(
        MODUL_A,
        MODUL_B,
        touchpoint_ids=(
            "tp-state-record-init",
            "tp-state-transition-write",
            "tp-state-finalize",
        ),
    )
    assert_dw_ac_2_cross_modul_schema_byte_parity(records, WELLE_PAIR_LABEL)


def test_doppel_welle_4_5_dw_ac_2_jcs_byte_drift_blocks(
    mocked_cross_modul_schema,
) -> None:
    """DW-AC-2 failure-mode: JCS-byte-divergence on transition-write.

    Welle-4-specific drift-source: Unicode-normalisation or float-
    formatting drift between the Rust JCS-implementation in
    state_backing and the lifecycle_state_machine's Rust-side JCS
    re-read. Cross-Modul-Drift-Focus = exactly this surface.
    """
    records = mocked_cross_modul_schema(
        MODUL_A,
        MODUL_B,
        touchpoint_ids=(
            "tp-state-record-init",
            "tp-state-transition-write",
            "tp-state-finalize",
        ),
        drift_touchpoint_ids=("tp-state-transition-write",),
    )
    with pytest.raises(AssertionError, match="DW-AC-2"):
        assert_dw_ac_2_cross_modul_schema_byte_parity(
            records, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_dw_ac_2_terminal_record_drift_blocks(
    mocked_cross_modul_schema,
) -> None:
    """DW-AC-2 failure-mode: drift on terminal ``tp-state-finalize`` is
    a Welle-7-recovery-blocker (recovery_workflow reads terminal
    records to compute the restart-point).
    """
    records = mocked_cross_modul_schema(
        MODUL_A,
        MODUL_B,
        touchpoint_ids=(
            "tp-state-record-init",
            "tp-state-transition-write",
            "tp-state-finalize",
        ),
        drift_touchpoint_ids=("tp-state-finalize",),
    )
    with pytest.raises(AssertionError, match="DW-AC-2"):
        assert_dw_ac_2_cross_modul_schema_byte_parity(
            records, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# DW-AC-3 — Asymmetric single-Komponente-Rollback.
#
# Note: Welle-4 first triggers the Schema-Migrations-Rollback-Plan
# pre-requisite — a state_backing rollback under Doppel-Welle means
# lifecycle_state_machine must continue reading Rust-state from disk
# while *itself* still on Rust. Risky combination, hence ADR-0066
# §Rollback-Strategie nuance: if state_backing rollback is needed,
# *also* roll back lifecycle to keep the schema-contract one-sided.
#
# DW-AC-3 here verifies the *asymmetric* path is supported; the
# follow-up policy decision (when to take it vs. both-rollback) is
# Henrik-Zone-N + Operator-Hand-runbook territory.
# ---------------------------------------------------------------------------


def test_doppel_welle_4_5_dw_ac_3_rollback_state_backing_partner_stays_rust(
    mocked_single_komponente_rollback,
) -> None:
    """DW-AC-3: bug in state_backing → state_backing rolls back to python.

    lifecycle_state_machine stays on rust. The two-sided rust →
    one-sided rust transition is what the schema-migration-rollback-
    plan prepares for.
    """
    record = mocked_single_komponente_rollback(
        MODUL_A,
        MODUL_B,
        rolled_back_modul=MODUL_A,
    )
    assert_dw_ac_3_asymmetric_rollback(record, WELLE_PAIR_LABEL)


def test_doppel_welle_4_5_dw_ac_3_rollback_lifecycle_partner_stays_rust(
    mocked_single_komponente_rollback,
) -> None:
    """DW-AC-3 direction-check: bug in lifecycle → lifecycle rolls back.

    state_backing stays on rust. Schema-direction stays
    Rust-producer × Python-consumer post-rollback.
    """
    record = mocked_single_komponente_rollback(
        MODUL_A,
        MODUL_B,
        rolled_back_modul=MODUL_B,
    )
    assert_dw_ac_3_asymmetric_rollback(record, WELLE_PAIR_LABEL)


def test_doppel_welle_4_5_dw_ac_3_sla_violation_blocks(
    mocked_single_komponente_rollback,
) -> None:
    """DW-AC-3 failure-mode: rollback >10min blocks the gate.

    For Welle-4 rollback specifically, the Schema-Migrations-Rollback-
    Plan has a ≤2h drill SLA — but the ENV-Flag-Switch-portion is
    still ≤10min (ADR-0066 retained ADR-0065 SLA).
    """
    record = mocked_single_komponente_rollback(
        MODUL_A,
        MODUL_B,
        rolled_back_modul=MODUL_A,
        elapsed_seconds=900.0,  # > 600s SLA
    )
    with pytest.raises(AssertionError, match="DW-AC-3"):
        assert_dw_ac_3_asymmetric_rollback(record, WELLE_PAIR_LABEL)


# ---------------------------------------------------------------------------
# DW-AC-4 — Cross-Modul-Stress-Test grün.
#
# DOMINANT GATE for Doppel-Welle-4+5 (Cross-Modul-Drift-Focus).
# References Tomás Tag-29 Phase-2-Acceptance-Gate-Erweiterung.
# ---------------------------------------------------------------------------


def test_doppel_welle_4_5_dw_ac_4_cross_modul_stress_test_green(
    mocked_cross_modul_stress_test,
) -> None:
    """DW-AC-4: cross-modul-state-paar joint-load stress green.

    The stress profile: high-frequency write→read→transition cycles
    against the state_backing×lifecycle_state_machine touchpoint set.
    Zero failures, zero p99-latency-excursions, zero schema-drifts
    required.

    References Tomás Tag-29 Cross-Modul-Stress-Test substrate
    (Phase-2-Acceptance-Gate-Erweiterung per ADR-0066 §Mitigation 1).
    """
    record = mocked_cross_modul_stress_test(
        MODUL_A, MODUL_B, total=5000  # higher stress-load than DW-1+2
    )
    assert_dw_ac_4_cross_modul_stress_test_green(record, WELLE_PAIR_LABEL)


def test_doppel_welle_4_5_dw_ac_4_failure_blocks(
    mocked_cross_modul_stress_test,
) -> None:
    """DW-AC-4 failure-mode: any failure in the stress-window blocks."""
    record = mocked_cross_modul_stress_test(
        MODUL_A, MODUL_B, total=5000, failures=1
    )
    with pytest.raises(AssertionError, match="DW-AC-4"):
        assert_dw_ac_4_cross_modul_stress_test_green(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_dw_ac_4_schema_drift_blocks(
    mocked_cross_modul_stress_test,
) -> None:
    """DW-AC-4 failure-mode: cross-modul-schema-drift during stress.

    This is the dominant Doppel-Welle-4+5 risk surface: stress-induced
    Unicode-normalisation drift, float-formatting drift, or transition-
    table edge-case drift.
    """
    record = mocked_cross_modul_stress_test(
        MODUL_A, MODUL_B, total=5000, schema_drifts=3
    )
    with pytest.raises(AssertionError, match="DW-AC-4"):
        assert_dw_ac_4_cross_modul_stress_test_green(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_dw_ac_4_p99_excursion_blocks(
    mocked_cross_modul_stress_test,
) -> None:
    """DW-AC-4 failure-mode: p99 latency excursion under joint load.

    Especially relevant for Welle-4+5: filesystem-fsync tail
    (state_backing) interacts with the transition-state-machine
    decision-loop (lifecycle); a slow fsync could starve a transition
    and create a latency-excursion that neither modul alone would
    surface.
    """
    record = mocked_cross_modul_stress_test(
        MODUL_A, MODUL_B, total=5000, p99_excursions=2
    )
    with pytest.raises(AssertionError, match="DW-AC-4"):
        assert_dw_ac_4_cross_modul_stress_test_green(
            record, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# DW-AC-5 — Backend-Decision-Audit emits 2 records consistently.
# ---------------------------------------------------------------------------


def test_doppel_welle_4_5_dw_ac_5_backend_decision_audit_two_records(
    mocked_backend_decision_audit,
) -> None:
    """DW-AC-5: Cutover-Mittwoch emits 2 audit records in one cycle."""
    records = mocked_backend_decision_audit(MODUL_A, MODUL_B)
    assert_dw_ac_5_backend_decision_audit_two_records_consistent(
        records, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
    )


def test_doppel_welle_4_5_dw_ac_5_missing_state_backing_record_blocks(
    mocked_backend_decision_audit,
) -> None:
    """DW-AC-5 failure-mode: only lifecycle's record present → state_
    backing flip silently happened off-cycle → audit-trail incomplete.
    """
    records = mocked_backend_decision_audit(
        MODUL_A, MODUL_B, missing_modul=MODUL_A
    )
    with pytest.raises(AssertionError, match="DW-AC-5"):
        assert_dw_ac_5_backend_decision_audit_two_records_consistent(
            records, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_dw_ac_5_cycle_id_drift_blocks(
    mocked_backend_decision_audit,
) -> None:
    """DW-AC-5 failure-mode: sequential cutover masquerading as parallel."""
    records = mocked_backend_decision_audit(
        MODUL_A, MODUL_B, drift_cycle_id=True
    )
    with pytest.raises(AssertionError, match="DW-AC-5"):
        assert_dw_ac_5_backend_decision_audit_two_records_consistent(
            records, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# Doppel-Welle-4+5 substrate sanity — Schema-Migrations-Rollback drill.
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "pending Doppel-Welle-cutover — Schema-Migrations-Rollback-Plan"
        " drill (Welle-4 prerequisite, retained under Doppel-Welle)"
    )
)
def test_doppel_welle_4_5_schema_migration_rollback_under_2h() -> None:
    """Doppel-Welle-4+5 Schema-Migrations-Rollback drill: ≤2h SLA on the
    full schema-rollback path (separate from the ≤10min ENV-Flag-Switch
    SLA covered by DW-AC-3).

    Operator-Hand drill substrate; the Doppel-Welle-trigger sprint
    wires this against the real state-backing schema-migration tooling.
    """
    raise NotImplementedError("pending Doppel-Welle-cutover")


@pytest.mark.skip(
    reason=(
        "pending Doppel-Welle-cutover — cross-modul-bug both-rollback"
        " runbook"
    )
)
def test_doppel_welle_4_5_cross_modul_bug_triggers_both_rollback() -> None:
    """Doppel-Welle-4+5 cross-modul-bug path: when the bug is in the
    *contract* between state_backing and lifecycle (not in one modul
    alone), the runbook calls for *both* moduln to roll back per
    ADR-0066 §Rollback-Strategie (the asymmetric DW-AC-3 path does
    not apply).

    Pending: real cross-modul-bug-classifier wiring + both-rollback
    runbook drill.
    """
    raise NotImplementedError("pending Doppel-Welle-cutover")
