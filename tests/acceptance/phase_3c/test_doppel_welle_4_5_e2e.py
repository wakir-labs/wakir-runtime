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
    assert_cross_modul_drift_ac_1_deserialization_round_trip,
    assert_cross_modul_drift_ac_2_write_back_wire_form_parity,
    assert_cross_modul_drift_ac_3_per_komponente_consistency,
    assert_cross_modul_drift_ac_4_atomic_flip_rollback,
    assert_dw_ac_1_both_moduln_boot_rust,
    assert_dw_ac_2_cross_modul_schema_byte_parity,
    assert_dw_ac_3_asymmetric_rollback,
    assert_dw_ac_4_cross_modul_stress_test_green,
    assert_dw_ac_5_backend_decision_audit_two_records_consistent,
)
from .conftest import (
    CROSS_MODUL_DRIFT_CONSISTENCY_PCT_FLOOR,
    CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD,
    CROSS_MODUL_DRIFT_WIRE_FORM_ORACLES,
    DOPPEL_WELLE_BY_PAIR,
)

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


# ---------------------------------------------------------------------------
# CMD-AC-1 — Producer→Consumer deserialization round-trip parity.
#
# state_backing-rust schreibt → lifecycle_state_machine-rust liest mit
# byte-identischer Schema-Deserialization. Drills deeper than DW-AC-2
# (single-touchpoint byte-parity on the producer side) by exercising
# the deserialize → re-serialize round-trip on the consumer side.
# ---------------------------------------------------------------------------


def test_doppel_welle_4_5_cmd_ac_1_deserialization_round_trip_parity(
    mocked_cross_modul_drift_deserialization,
) -> None:
    """CMD-AC-1: state_backing-rust → lifecycle_state_machine-rust
    round-trip byte-identical.

    The Phase-3c-trigger sprint wires this against real JCS output:
    state_backing-rust writes a state-record (initial, transition,
    terminal); lifecycle_state_machine-rust reads it, deserialises
    into the typed Rust struct, then re-serialises back to JCS. The
    re-serialised bytes must be byte-identical to the original.
    """
    records = mocked_cross_modul_drift_deserialization(MODUL_A, MODUL_B)
    assert_cross_modul_drift_ac_1_deserialization_round_trip(
        records, WELLE_PAIR_LABEL
    )


def test_doppel_welle_4_5_cmd_ac_1_byte_drift_blocks(
    mocked_cross_modul_drift_deserialization,
) -> None:
    """CMD-AC-1 failure-mode: deserialization mutates record bytes.

    Welle-4+5-specific drift-source: Rust-side serde implementation
    drift between the producer (state_backing-rust) and the consumer
    (lifecycle_state_machine-rust) — e.g. field-ordering drift,
    Unicode-normalisation drift, or float-formatting drift that
    survives deserialize but mutates re-serialize.
    """
    records = mocked_cross_modul_drift_deserialization(
        MODUL_A,
        MODUL_B,
        drift_record_ids=("rec-transition-1",),
    )
    with pytest.raises(AssertionError, match="CMD-AC-1"):
        assert_cross_modul_drift_ac_1_deserialization_round_trip(
            records, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_cmd_ac_1_schema_version_drop_blocks(
    mocked_cross_modul_drift_deserialization,
) -> None:
    """CMD-AC-1 failure-mode: schema-version field dropped on round-trip.

    This is a Welle-7-recovery-blocker: recovery_workflow reads
    terminal records to compute restart-points and the schema-version
    field is the primary disambiguator for cross-version state
    migration. A drop on round-trip silently breaks recovery for any
    state-record persisted under the Doppel-Welle cutover-cycle.
    """
    records = mocked_cross_modul_drift_deserialization(
        MODUL_A,
        MODUL_B,
        schema_version_breakage_ids=("rec-terminal-archived",),
    )
    with pytest.raises(AssertionError, match="CMD-AC-1"):
        assert_cross_modul_drift_ac_1_deserialization_round_trip(
            records, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# CMD-AC-2 — Consumer-triggered Producer write-back wire-form parity.
#
# lifecycle_state_machine-rust State-Transition triggert state_backing-
# rust Persist mit gleicher Wire-Form wie Python-Pendant. Validates
# Rust-Rust wire-form against Python-Python baseline + Python-Rust
# mixed-state oracles.
# ---------------------------------------------------------------------------


def test_doppel_welle_4_5_cmd_ac_2_write_back_wire_form_parity_all_oracles(
    mocked_cross_modul_drift_write_back,
) -> None:
    """CMD-AC-2: transition-triggered persist wire-form matches all oracles.

    The Phase-3c-trigger sprint wires this against:
    * Pre-Welle-4-cutover production state (python-python baseline)
    * Synthetic python-rust-welle-4-only state (state_backing-rust +
      lifecycle-python — never observed in production but available
      as a hypothetical reference oracle).

    Rust-Rust wire-form must match both oracles byte-identically for
    every transition in the test-set.
    """
    records = mocked_cross_modul_drift_write_back(MODUL_A, MODUL_B)
    assert_cross_modul_drift_ac_2_write_back_wire_form_parity(
        records, WELLE_PAIR_LABEL
    )


def test_doppel_welle_4_5_cmd_ac_2_python_baseline_drift_blocks(
    mocked_cross_modul_drift_write_back,
) -> None:
    """CMD-AC-2 failure-mode: Rust-Rust diverges from python-python baseline.

    This is the dominant regression-class for the Welle-4+5 Doppel-
    Welle: the new Rust-Rust wire-form produces a hash that the long-
    standing Python-Python production state did not. Recovery from
    pre-cutover-state records becomes hash-divergent → Welle-7
    recovery-workflow blocker.
    """
    records = mocked_cross_modul_drift_write_back(
        MODUL_A,
        MODUL_B,
        drift_oracle="python-python-baseline",
        drift_transition_ids=("transition-active-to-archived",),
    )
    with pytest.raises(AssertionError, match="CMD-AC-2"):
        assert_cross_modul_drift_ac_2_write_back_wire_form_parity(
            records, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_cmd_ac_2_python_rust_mixed_drift_blocks(
    mocked_cross_modul_drift_write_back,
) -> None:
    """CMD-AC-2 failure-mode: Rust-Rust diverges from python-rust-welle-4-only.

    Asymmetric drift here localises the bug to the Rust-side
    lifecycle_state_machine modul: state_backing-rust write-out
    matches the python-python baseline (otherwise the python-rust
    oracle would also fail), but the transition trigger from the
    Rust-side lifecycle introduced a wire-form regression.
    """
    records = mocked_cross_modul_drift_write_back(
        MODUL_A,
        MODUL_B,
        drift_oracle="python-rust-welle-4-only",
        drift_transition_ids=(
            "transition-spawn-to-ready",
            "transition-ready-to-active",
        ),
    )
    with pytest.raises(AssertionError, match="CMD-AC-2"):
        assert_cross_modul_drift_ac_2_write_back_wire_form_parity(
            records, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_cmd_ac_2_oracles_anchor_to_adr_0066() -> None:
    """CMD-AC-2 sanity: the wire-form-oracle set is ADR-0066-fixed.

    Tightening or loosening the oracle set requires an ADR-Folge-Item,
    not a conftest-edit. The set is exactly (python-python-baseline,
    python-rust-welle-4-only); a Rust-Rust oracle would be self-
    referential and is explicitly excluded.
    """
    assert CROSS_MODUL_DRIFT_WIRE_FORM_ORACLES == (
        "python-python-baseline",
        "python-rust-welle-4-only",
    ), (
        f"CMD-AC-2 oracle-set anchored to ADR-0066 — must be "
        f"(python-python-baseline, python-rust-welle-4-only); got "
        f"{CROSS_MODUL_DRIFT_WIRE_FORM_ORACLES!r}"
    )


# ---------------------------------------------------------------------------
# CMD-AC-3 — Cross-Modul-Stress-Test per-Komponente consistency ≥99.5%.
#
# PR #197 Cross-Modul-Stress-Test substrate joint-load output split by
# Komponente. DW-AC-4 sets zero-failure-floor on the aggregate; CMD-
# AC-3 sets a per-Komponente consistency-rate ≥99.5% floor.
# ---------------------------------------------------------------------------


def test_doppel_welle_4_5_cmd_ac_3_per_komponente_consistency_green(
    mocked_cross_modul_drift_per_komponente_consistency,
) -> None:
    """CMD-AC-3: both per-Komponente consistency-rates ≥99.5%.

    The Phase-3c-trigger sprint wires this against PR #197 Cross-
    Modul-Stress-Test substrate output broken out per Komponente:
    one rate for state_backing-rust's write-side behaviour and one
    rate for lifecycle_state_machine-rust's read+transition-side
    behaviour over the same stress-window.
    """
    record = mocked_cross_modul_drift_per_komponente_consistency(
        MODUL_A, MODUL_B
    )
    assert_cross_modul_drift_ac_3_per_komponente_consistency(
        record, WELLE_PAIR_LABEL
    )


def test_doppel_welle_4_5_cmd_ac_3_modul_a_below_floor_blocks(
    mocked_cross_modul_drift_per_komponente_consistency,
) -> None:
    """CMD-AC-3 failure-mode: state_backing per-Komponente rate below floor.

    Even if the aggregate DW-AC-4 stress-test is zero-failure (e.g.
    because the lifecycle side compensates), CMD-AC-3 catches a
    state_backing-side consistency degradation below 99.5%.
    """
    record = mocked_cross_modul_drift_per_komponente_consistency(
        MODUL_A, MODUL_B, modul_a_rate=0.991
    )
    with pytest.raises(AssertionError, match="CMD-AC-3"):
        assert_cross_modul_drift_ac_3_per_komponente_consistency(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_cmd_ac_3_modul_b_below_floor_blocks(
    mocked_cross_modul_drift_per_komponente_consistency,
) -> None:
    """CMD-AC-3 failure-mode: lifecycle per-Komponente rate below floor."""
    record = mocked_cross_modul_drift_per_komponente_consistency(
        MODUL_A, MODUL_B, modul_b_rate=0.989
    )
    with pytest.raises(AssertionError, match="CMD-AC-3"):
        assert_cross_modul_drift_ac_3_per_komponente_consistency(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_cmd_ac_3_both_below_floor_blocks(
    mocked_cross_modul_drift_per_komponente_consistency,
) -> None:
    """CMD-AC-3 failure-mode: both per-Komponente rates below floor.

    Joint-rate (computed as min()) is the lower of the two; the
    assertion-shape lists both failing moduln in the error.
    """
    record = mocked_cross_modul_drift_per_komponente_consistency(
        MODUL_A, MODUL_B, modul_a_rate=0.992, modul_b_rate=0.988
    )
    with pytest.raises(AssertionError, match="CMD-AC-3"):
        assert_cross_modul_drift_ac_3_per_komponente_consistency(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_cmd_ac_3_consistency_floor_anchored_to_adr_0066() -> None:
    """CMD-AC-3 sanity: the 99.5% floor is ADR-0066-fixed.

    Loosening this floor requires an ADR-Folge-Item, not a conftest-
    edit. The 0.995 value is the Welle-4+5 Cross-Modul-Drift-Focus
    bar; other Doppel-Wellen (DW-1+2 read-only, DW-6+7 stateful-loop)
    do not carry CMD-AC-3 at all.
    """
    assert CROSS_MODUL_DRIFT_CONSISTENCY_PCT_FLOOR == 0.995, (
        f"CMD-AC-3 consistency-floor anchored to ADR-0066 — must be "
        f"0.995 (99.5%); got {CROSS_MODUL_DRIFT_CONSISTENCY_PCT_FLOOR}"
    )


# ---------------------------------------------------------------------------
# CMD-AC-4 — Drift-triggered atomic single-Komponente rollback.
#
# Rollback einer Komponente bei Drift > 0.5pp, andere bleibt rust-
# Default (atomic-flip-pattern). Drills deeper than DW-AC-3 (manual-
# operator asymmetric rollback) by enforcing the drift-magnitude
# trigger-precondition and the atomicity property.
# ---------------------------------------------------------------------------


def test_doppel_welle_4_5_cmd_ac_4_atomic_flip_high_drift_state_backing(
    mocked_cross_modul_drift_atomic_flip,
) -> None:
    """CMD-AC-4: state_backing drift > 0.5pp → atomic flip to python.

    lifecycle_state_machine stays rust-Default. The Phase-3c-trigger
    sprint wires this against the real Operator-Hand-runbook
    atomic-flip script (single ``systemctl restart`` cycle, ENV-flag
    rewrite, post-flip backend-state verification).
    """
    record = mocked_cross_modul_drift_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
        measured_drift_pct=0.75,
    )
    assert_cross_modul_drift_ac_4_atomic_flip_rollback(
        record, WELLE_PAIR_LABEL
    )


def test_doppel_welle_4_5_cmd_ac_4_atomic_flip_high_drift_lifecycle(
    mocked_cross_modul_drift_atomic_flip,
) -> None:
    """CMD-AC-4 direction-check: lifecycle drift > 0.5pp → flip lifecycle."""
    record = mocked_cross_modul_drift_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_B,
        measured_drift_pct=0.62,
    )
    assert_cross_modul_drift_ac_4_atomic_flip_rollback(
        record, WELLE_PAIR_LABEL
    )


def test_doppel_welle_4_5_cmd_ac_4_sub_threshold_flip_rejected(
    mocked_cross_modul_drift_atomic_flip,
) -> None:
    """CMD-AC-4 failure-mode: spurious sub-threshold flip rejected.

    A flip on measured drift ≤0.5pp is spurious — the Operator-Hand-
    runbook must not fire an atomic-flip on sub-threshold drift,
    because Welle-4+5 Cross-Modul-Drift-Focus accepts small drift
    (covered by DW-AC-2's exact-byte-parity check) but reserves the
    automated flip for the 0.5pp-and-above operationally-relevant
    drift.
    """
    record = mocked_cross_modul_drift_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
        measured_drift_pct=0.35,
    )
    with pytest.raises(AssertionError, match="CMD-AC-4"):
        assert_cross_modul_drift_ac_4_atomic_flip_rollback(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_cmd_ac_4_partner_contagion_blocks(
    mocked_cross_modul_drift_atomic_flip,
) -> None:
    """CMD-AC-4 failure-mode: partner also flipped → contagious rollback.

    Atomic-flip-pattern forbids contagious rollback: only the high-
    drift modul flips; the partner stays rust. A cross-modul-contract
    bug triggers both-rollback through the DW-AC-3 path (not CMD-
    AC-4); CMD-AC-4 covers exclusively the single-modul-drift path.
    """
    record = mocked_cross_modul_drift_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
        measured_drift_pct=0.85,
        partner_also_flipped=True,
    )
    with pytest.raises(AssertionError, match="CMD-AC-4"):
        assert_cross_modul_drift_ac_4_atomic_flip_rollback(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_cmd_ac_4_non_atomic_flip_blocks(
    mocked_cross_modul_drift_atomic_flip,
) -> None:
    """CMD-AC-4 failure-mode: non-atomic flip (multi-restart-cycle).

    The Operator-Hand-runbook is single-shot. A multi-cycle flip
    indicates the runbook drifted from the atomic-flip-pattern; the
    intermediate state where one modul is mid-flip risks contract
    violations between the moduln during the flip-window.
    """
    record = mocked_cross_modul_drift_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
        measured_drift_pct=0.72,
        flip_was_atomic=False,
    )
    with pytest.raises(AssertionError, match="CMD-AC-4"):
        assert_cross_modul_drift_ac_4_atomic_flip_rollback(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_cmd_ac_4_sla_violation_blocks(
    mocked_cross_modul_drift_atomic_flip,
) -> None:
    """CMD-AC-4 failure-mode: flip-elapsed exceeds 10min SLA.

    Same ENV-Flag-Switch SLA as DW-AC-3 (600s). A slow atomic-flip
    extends the cross-modul-drift-window and is operationally
    indistinguishable from a non-atomic flip from the substrate's
    perspective.
    """
    record = mocked_cross_modul_drift_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
        measured_drift_pct=0.78,
        flip_elapsed_seconds=820.0,
    )
    with pytest.raises(AssertionError, match="CMD-AC-4"):
        assert_cross_modul_drift_ac_4_atomic_flip_rollback(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_4_5_cmd_ac_4_threshold_anchored_to_adr_0066() -> None:
    """CMD-AC-4 sanity: the 0.5pp drift-threshold is ADR-0066-fixed.

    Tightening or loosening the threshold requires an ADR-Folge-Item,
    not a conftest-edit. The 0.5pp value is the Welle-4+5 Cross-
    Modul-Drift-Focus operational-trigger; mirrors the Welle-3
    Henrik-Caution divergence threshold numerically but applies per-
    modul rather than whole-bridge-audit-writer.
    """
    assert CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD == 0.5, (
        f"CMD-AC-4 drift-threshold anchored to ADR-0066 — must be "
        f"0.5pp; got {CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD}"
    )
