# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Doppel-Welle-6+7 E2E acceptance — ``subscribe_loop`` +
``recovery_workflow`` parallel cutover (KW 27).

Anchors
-------

- ADR-0066 §Beschluss — Doppel-Welle KW 27: Welle-6 + Welle-7 parallel.
- ADR-0066 §Verifikations-Plan §"Welle-6+7 KW 27" — Low-Coupling-
  Komponenten, Standard-Acceptance. Note: "Low-Coupling" refers to
  the *coupling between the pair*, not the absolute coupling of each
  modul. recovery_workflow is itself the most cross-modul-dependent
  modul of all seven (it reads every prior welle's substrate during
  restart-point reconstruction).
- ADR-0065 §Welle-Ende-Acceptance §WE-1...WE-4 — fires after Welle-7
  completes. Doppel-Welle-6+7 telescopes the Welle-7-AC + WE-1...WE-4
  into the same cutover-week.
- ``test_welle_6_subscribe_loop_e2e.py`` + ``test_welle_7_recovery_
  workflow_e2e.py`` — per-welle sister files.

Doppel-Welle character — stateful-loop-paar
-------------------------------------------

Welle-6+7 closes Phase-3c. After this cutover, all 7 moduln are on
rust-default. The Doppel-Welle character:

1. ``subscribe_loop`` holds NATS-subscription state (subscription-
   cursor, connection-keepalive). Bug-42-Lessons-Learned hot
   substrate.
2. ``recovery_workflow`` is the cross-modul orchestrator — by KW 27,
   *all six* prior moduln are rust-backed, so recovery_workflow's
   read-path is uniformly Rust. The cutover of recovery_workflow
   itself to rust means the Rust-recovery-orchestrator reads Rust-
   substrate uniformly.
3. The *pair* coupling is moderate: subscribe_loop delivers
   subscription-events that recovery_workflow consults during
   restart-point reconstruction, but they share no JCS-schema
   touchpoint as directly as Welle-4+5 did.

DW-AC-1 + DW-AC-3 + DW-AC-5 carry the dominant gate-weight here;
DW-AC-2 + DW-AC-4 are present but lower-emphasis than Welle-4+5.
"""

from __future__ import annotations

import pytest

from ._ac_assertions import (
    assert_cross_modul_drift_welle_6_7_ac_1_ack_consume_round_trip,
    assert_cross_modul_drift_welle_6_7_ac_2_resubscribe_trigger_wire_form,
    assert_cross_modul_drift_welle_6_7_ac_3_per_komponente_consistency,
    assert_cross_modul_drift_welle_6_7_ac_4_atomic_flip_rollback,
    assert_dw_ac_1_both_moduln_boot_rust,
    assert_dw_ac_2_cross_modul_schema_byte_parity,
    assert_dw_ac_3_asymmetric_rollback,
    assert_dw_ac_4_cross_modul_stress_test_green,
    assert_dw_ac_5_backend_decision_audit_two_records_consistent,
)
from .conftest import (
    CROSS_MODUL_DRIFT_CONSISTENCY_PCT_FLOOR,
    CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD,
    CROSS_MODUL_DRIFT_WELLE_6_7_WIRE_FORM_ORACLES,
    DOPPEL_WELLE_BY_PAIR,
)

MODUL_A = "subscribe_loop"
MODUL_B = "recovery_workflow"
WELLE_PAIR_LABEL = f"KW27:{MODUL_A}+{MODUL_B}"
EXPECTED_KW = DOPPEL_WELLE_BY_PAIR[(MODUL_A, MODUL_B)]

pytestmark = pytest.mark.phase_3c_doppel_welle_acceptance


def test_doppel_welle_6_7_anchored_to_kw_27() -> None:
    """Sanity: this file targets the ADR-0066 KW 27 Doppel-Welle pair."""
    assert EXPECTED_KW == "KW27", (
        f"Doppel-Welle-6+7 must anchor to KW27 per ADR-0066 §Beschluss; "
        f"got {EXPECTED_KW!r}"
    )


# ---------------------------------------------------------------------------
# DW-AC-1 — Both Doppel-Welle moduln boot with rust-backend.
# ---------------------------------------------------------------------------


def test_doppel_welle_6_7_dw_ac_1_both_moduln_boot_rust(
    mocked_engine_boot_doppel,
) -> None:
    """DW-AC-1: subscribe_loop + recovery_workflow both on rust-backend.

    Post-cutover this completes Phase-3c — all 7 moduln on rust-
    default. WE-1...WE-4 fire after Friday Acceptance-Decision (see
    test_welle_7_recovery_workflow_e2e.py for the Welle-Ende-Acceptance
    gates).
    """
    boot = mocked_engine_boot_doppel(MODUL_A, MODUL_B)
    assert_dw_ac_1_both_moduln_boot_rust(
        boot, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
    )


def test_doppel_welle_6_7_dw_ac_1_boot_failure_blocks(
    mocked_engine_boot_doppel,
) -> None:
    """DW-AC-1 failure-mode: engine-boot fails → both rollback.

    Welle-6 has the Bug-42-replay-coverage substrate (subscribe-mode-
    misrouting); a boot-failure must trigger Bug-42-replay-runbook
    pre-rollback to determine whether the boot-failure is a Bug-42
    regression or a different surface.
    """
    boot = mocked_engine_boot_doppel(MODUL_A, MODUL_B, boot_succeeded=False)
    with pytest.raises(AssertionError, match="DW-AC-1"):
        assert_dw_ac_1_both_moduln_boot_rust(
            boot, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# DW-AC-2 — Cross-Modul-Schema-Konsistenz (byte-paritär).
# ---------------------------------------------------------------------------


def test_doppel_welle_6_7_dw_ac_2_subscription_event_to_recovery_byte_parity(
    mocked_cross_modul_schema,
) -> None:
    """DW-AC-2: subscription-event records byte-paritär across the
    touchpoints recovery_workflow consults.

    Real touchpoints (Phase-3c-trigger-sprint wiring):
    * ``tp-subscription-cursor-readback`` — recovery reads cursor-state
      to determine restart-point.
    * ``tp-nats-keepalive-snapshot`` — recovery reads keepalive-trail.
    * ``tp-subscribe-event-log-frame`` — recovery replays event-log
      frames into the reconstruction-pipeline.
    """
    records = mocked_cross_modul_schema(
        MODUL_A,
        MODUL_B,
        touchpoint_ids=(
            "tp-subscription-cursor-readback",
            "tp-nats-keepalive-snapshot",
            "tp-subscribe-event-log-frame",
        ),
    )
    assert_dw_ac_2_cross_modul_schema_byte_parity(records, WELLE_PAIR_LABEL)


def test_doppel_welle_6_7_dw_ac_2_cursor_drift_blocks(
    mocked_cross_modul_schema,
) -> None:
    """DW-AC-2 failure-mode: subscription-cursor byte-drift blocks.

    Cursor-drift is the Bug-42-adjacent surface: a one-byte difference
    in cursor-serialisation would cause recovery to compute a wrong
    restart-point and replay messages incorrectly.
    """
    records = mocked_cross_modul_schema(
        MODUL_A,
        MODUL_B,
        touchpoint_ids=(
            "tp-subscription-cursor-readback",
            "tp-nats-keepalive-snapshot",
            "tp-subscribe-event-log-frame",
        ),
        drift_touchpoint_ids=("tp-subscription-cursor-readback",),
    )
    with pytest.raises(AssertionError, match="DW-AC-2"):
        assert_dw_ac_2_cross_modul_schema_byte_parity(
            records, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# DW-AC-3 — Asymmetric single-Komponente-Rollback.
# ---------------------------------------------------------------------------


def test_doppel_welle_6_7_dw_ac_3_rollback_subscribe_partner_stays_rust(
    mocked_single_komponente_rollback,
) -> None:
    """DW-AC-3: bug in subscribe_loop → only subscribe_loop rolls back.

    recovery_workflow stays on rust. The Rust-recovery-orchestrator
    now reads a Python-subscribe-loop's cursor — the cross-language
    cursor-readback is the asymmetric-rollback risk surface, mitigated
    by the per-welle Welle-6 Bug-42-Lessons-Learned coverage that's
    already in test_welle_6_subscribe_loop_e2e.py.
    """
    record = mocked_single_komponente_rollback(
        MODUL_A,
        MODUL_B,
        rolled_back_modul=MODUL_A,
    )
    assert_dw_ac_3_asymmetric_rollback(record, WELLE_PAIR_LABEL)


def test_doppel_welle_6_7_dw_ac_3_rollback_recovery_partner_stays_rust(
    mocked_single_komponente_rollback,
) -> None:
    """DW-AC-3 direction-check: bug in recovery → recovery rolls back.

    subscribe_loop stays on rust. recovery_workflow rollback is
    particularly costly because it's the last welle and a rollback
    here delays Phase-3c-Ende + ADR-0035-C-Drift-Closure by ≥1 week.
    """
    record = mocked_single_komponente_rollback(
        MODUL_A,
        MODUL_B,
        rolled_back_modul=MODUL_B,
    )
    assert_dw_ac_3_asymmetric_rollback(record, WELLE_PAIR_LABEL)


def test_doppel_welle_6_7_dw_ac_3_sla_violation_blocks(
    mocked_single_komponente_rollback,
) -> None:
    """DW-AC-3 failure-mode: rollback >10min blocks the gate."""
    record = mocked_single_komponente_rollback(
        MODUL_A,
        MODUL_B,
        rolled_back_modul=MODUL_B,
        elapsed_seconds=650.0,  # > 600s SLA
    )
    with pytest.raises(AssertionError, match="DW-AC-3"):
        assert_dw_ac_3_asymmetric_rollback(record, WELLE_PAIR_LABEL)


# ---------------------------------------------------------------------------
# DW-AC-4 — Cross-Modul-Stress-Test grün.
# ---------------------------------------------------------------------------


def test_doppel_welle_6_7_dw_ac_4_cross_modul_stress_test_green(
    mocked_cross_modul_stress_test,
) -> None:
    """DW-AC-4: stateful-loop-paar joint-load stress green.

    The stress profile: subscription-event-flood + simultaneous
    recovery-restart-points. References Tomás Tag-29 substrate
    (Phase-2-Acceptance-Gate-Erweiterung). Per ADR-0066 §Verifikations-
    Plan §"Welle-6+7", Standard-Acceptance applies — the stress-load
    is the baseline (not the Welle-4+5-enhanced level).
    """
    record = mocked_cross_modul_stress_test(MODUL_A, MODUL_B, total=2000)
    assert_dw_ac_4_cross_modul_stress_test_green(record, WELLE_PAIR_LABEL)


def test_doppel_welle_6_7_dw_ac_4_failure_blocks(
    mocked_cross_modul_stress_test,
) -> None:
    """DW-AC-4 failure-mode: stress-induced failure blocks.

    Welle-6+7-specific failure-source: NATS-reconnect-storm during
    stress + simultaneous recovery-walk on the same persona could
    deadlock the engine-runtime if subscribe_loop holds a lock that
    recovery_workflow waits on.
    """
    record = mocked_cross_modul_stress_test(
        MODUL_A, MODUL_B, total=2000, failures=2
    )
    with pytest.raises(AssertionError, match="DW-AC-4"):
        assert_dw_ac_4_cross_modul_stress_test_green(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_dw_ac_4_p99_excursion_blocks(
    mocked_cross_modul_stress_test,
) -> None:
    """DW-AC-4 failure-mode: NATS-tail-latency excursions block."""
    record = mocked_cross_modul_stress_test(
        MODUL_A, MODUL_B, total=2000, p99_excursions=1
    )
    with pytest.raises(AssertionError, match="DW-AC-4"):
        assert_dw_ac_4_cross_modul_stress_test_green(
            record, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# DW-AC-5 — Backend-Decision-Audit emits 2 records consistently.
# ---------------------------------------------------------------------------


def test_doppel_welle_6_7_dw_ac_5_backend_decision_audit_two_records(
    mocked_backend_decision_audit,
) -> None:
    """DW-AC-5: Cutover-Mittwoch emits 2 audit records in one cycle.

    Post-Welle-7 the audit-trail closes Phase-3c; Henrik-Audit (Zone-N)
    cross-references this audit-record-pair against the per-welle audit-
    trail for the WE-3 Welle-Ende-gate (audit-compliance check).
    """
    records = mocked_backend_decision_audit(MODUL_A, MODUL_B)
    assert_dw_ac_5_backend_decision_audit_two_records_consistent(
        records, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
    )


def test_doppel_welle_6_7_dw_ac_5_missing_recovery_record_blocks(
    mocked_backend_decision_audit,
) -> None:
    """DW-AC-5 failure-mode: missing recovery_workflow record means
    Phase-3c-Ende cannot be declared (WE-2 Quadlet-Default-ENV-Flags
    requires all 7 flags on rust; without the audit-record-pair for
    Welle-6+7, the audit-trail for the cutover is incomplete).
    """
    records = mocked_backend_decision_audit(
        MODUL_A, MODUL_B, missing_modul=MODUL_B
    )
    with pytest.raises(AssertionError, match="DW-AC-5"):
        assert_dw_ac_5_backend_decision_audit_two_records_consistent(
            records, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_dw_ac_5_wrong_target_backend_blocks(
    mocked_backend_decision_audit,
) -> None:
    """DW-AC-5 failure-mode: one record names a non-rust target.

    A target_backend other than ``rust`` on Welle-7 means recovery_
    workflow didn't flip — Phase-3c cannot close.
    """
    records = mocked_backend_decision_audit(
        MODUL_A, MODUL_B, wrong_target_backend="python"
    )
    with pytest.raises(AssertionError, match="DW-AC-5"):
        assert_dw_ac_5_backend_decision_audit_two_records_consistent(
            records, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# Doppel-Welle-6+7 substrate sanity — Welle-Ende-Acceptance hand-off.
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "pending Doppel-Welle-cutover — WE-1...WE-4 Welle-Ende-"
        "Acceptance hand-off (covered welle-for-welle in"
        " test_welle_7_recovery_workflow_e2e.py)"
    )
)
def test_doppel_welle_6_7_welle_ende_acceptance_handoff() -> None:
    """Doppel-Welle-6+7 closes Phase-3c. After this cutover passes all
    DW-AC-1...DW-AC-5 *and* the per-welle Welle-7-AC-1...AC-5, the
    Welle-Ende-Acceptance lane (WE-1...WE-4, ADR-0065 §Welle-Ende-
    Acceptance) fires.

    WE-1: Container-Image-Tag ``0.7.0-rust`` als Production-Default.
    WE-2: Quadlet-Default-ENV-Flags alle 7 auf ``rust``.
    WE-3: Henrik-Audit-Compliance-Check GREEN.
    WE-4: ``wirelang/persona_engine_py_legacy/`` archived (4-Wochen-
    Reserve).

    The WE-1...WE-4 assertions live in test_welle_7_recovery_workflow_
    e2e.py (per-welle file, parent skeleton). This Doppel-Welle file
    leaves them as the per-welle responsibility — DW-AC-1...DW-AC-5 are
    the Doppel-Welle-specific value-add, not a WE-1...WE-4 duplicate.
    """
    raise NotImplementedError("pending Doppel-Welle-cutover")


# ---------------------------------------------------------------------------
# CMD-AC-6-7-1 — subscribe_loop ack-record → recovery_workflow consume
# round-trip parity + cursor-delta-survival.
#
# Drills deeper than DW-AC-2 (single-touchpoint byte-parity on the
# producer side) by exercising the deserialize → re-serialize round-
# trip on the consumer side AND the cursor-delta-field survival
# (Bug-42-adjacent surface).
# ---------------------------------------------------------------------------


def test_doppel_welle_6_7_cmd_ac_6_7_1_ack_consume_round_trip_parity(
    mocked_cross_modul_drift_welle_6_7_ack_round_trip,
) -> None:
    """CMD-AC-6-7-1: subscribe_loop-rust ack → recovery_workflow-rust
    consume byte-identical (cursor-delta-survival).

    The Phase-3c-trigger sprint wires this against real NATS-JetStream
    ack-records: subscribe_loop-rust emits the ack on subscription-
    event, recovery_workflow-rust consumes during restart-point
    reconstruction, deserialises into the typed Rust struct, then re-
    serialises back. The re-serialised bytes must equal the original.
    """
    records = mocked_cross_modul_drift_welle_6_7_ack_round_trip(
        MODUL_A, MODUL_B
    )
    assert_cross_modul_drift_welle_6_7_ac_1_ack_consume_round_trip(
        records, WELLE_PAIR_LABEL
    )


def test_doppel_welle_6_7_cmd_ac_6_7_1_byte_drift_blocks(
    mocked_cross_modul_drift_welle_6_7_ack_round_trip,
) -> None:
    """CMD-AC-6-7-1 failure-mode: ack-bytes mutate on consumer-side.

    Welle-6+7-specific drift-source: Rust-side serde implementation
    drift between subscribe_loop-rust (producer) and recovery_
    workflow-rust (consumer) — Unicode-normalisation drift,
    field-ordering drift in the ack-record envelope.
    """
    records = mocked_cross_modul_drift_welle_6_7_ack_round_trip(
        MODUL_A,
        MODUL_B,
        drift_ack_ids=("ack-cursor-1",),
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-1"):
        assert_cross_modul_drift_welle_6_7_ac_1_ack_consume_round_trip(
            records, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_1_cursor_delta_drop_blocks(
    mocked_cross_modul_drift_welle_6_7_ack_round_trip,
) -> None:
    """CMD-AC-6-7-1 failure-mode: cursor-delta dropped on round-trip.

    This is the Bug-42-replay-class regression: the cursor-delta field
    silently drops on consumer-side deserialize -> re-serialize,
    causing recovery_workflow to compute a wrong restart-point on
    next replay. Bug-42 lessons-learned coverage is the dominant
    testing surface for this exact failure-class.
    """
    records = mocked_cross_modul_drift_welle_6_7_ack_round_trip(
        MODUL_A,
        MODUL_B,
        cursor_delta_breakage_ids=("ack-keepalive-snapshot",),
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-1"):
        assert_cross_modul_drift_welle_6_7_ac_1_ack_consume_round_trip(
            records, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# CMD-AC-6-7-2 — recovery_workflow R1..R4 Re-subscribe-trigger wire-form
# parity vs python-python-baseline.
#
# Singleton oracle-set: only python-python-baseline. The Welle-4+5
# mid-Doppel-Welle hypothetical (python-rust-welle-N-only) is
# operationally unreachable for Welle-6+7 because the subscribe/
# recovery contract crosses no bisectable schema touchpoint.
# ---------------------------------------------------------------------------


def test_doppel_welle_6_7_cmd_ac_6_7_2_resubscribe_trigger_wire_form_parity(
    mocked_cross_modul_drift_welle_6_7_resubscribe,
) -> None:
    """CMD-AC-6-7-2: R1..R4 Re-subscribe-trigger wire-form matches
    python-python-baseline.

    The Phase-3c-trigger sprint wires this against:
    * R1 — Re-subscribe-on-cold-start (post-engine-boot).
    * R2 — Re-subscribe-with-restart-point-replay.
    * R3 — Re-subscribe-with-partial-replay (cursor-walk-forward).
    * R4 — Re-subscribe-with-fast-forward (skip-to-tip).

    Rust-Rust trigger wire-form must match the pre-Doppel-Welle-6+7
    production baseline byte-identically for every R1..R4 trigger.
    """
    records = mocked_cross_modul_drift_welle_6_7_resubscribe(
        MODUL_A, MODUL_B
    )
    assert_cross_modul_drift_welle_6_7_ac_2_resubscribe_trigger_wire_form(
        records, WELLE_PAIR_LABEL
    )


def test_doppel_welle_6_7_cmd_ac_6_7_2_python_baseline_drift_blocks(
    mocked_cross_modul_drift_welle_6_7_resubscribe,
) -> None:
    """CMD-AC-6-7-2 failure-mode: Rust-Rust diverges from python-
    python baseline.

    This is the dominant regression-class for the Welle-6+7 Doppel-
    Welle: the new Rust-Rust trigger wire-form produces a hash that
    the long-standing Python-Python production state did not. Recovery
    runbooks reading pre-cutover triggers become hash-divergent, raising
    re-subscribe-storm risk during cutover-day.
    """
    records = mocked_cross_modul_drift_welle_6_7_resubscribe(
        MODUL_A,
        MODUL_B,
        drift_trigger_ids=("R2",),
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-2"):
        assert_cross_modul_drift_welle_6_7_ac_2_resubscribe_trigger_wire_form(
            records, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_2_multiple_trigger_drifts_block(
    mocked_cross_modul_drift_welle_6_7_resubscribe,
) -> None:
    """CMD-AC-6-7-2 failure-mode: multiple R1..R4 triggers drift.

    The assertion-shape surfaces every drifting trigger in the error
    message, not just the first one. Useful for operator-side triage
    when the Rust-side recovery-runbook regressed all triggers
    simultaneously (e.g. via a shared serialisation-helper change).
    """
    records = mocked_cross_modul_drift_welle_6_7_resubscribe(
        MODUL_A,
        MODUL_B,
        drift_trigger_ids=("R1", "R3", "R4"),
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-2"):
        assert_cross_modul_drift_welle_6_7_ac_2_resubscribe_trigger_wire_form(
            records, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_2_oracle_set_singleton_anchored_to_adr_0066() -> None:
    """CMD-AC-6-7-2 sanity: oracle-set is singleton (python-python-
    baseline only), ADR-0066-fixed.

    The Welle-4+5 mid-Doppel-Welle hypothetical (python-rust-welle-N-
    only) does NOT apply to Welle-6+7 because the subscribe/recovery
    contract crosses no bisectable schema touchpoint. Adding a second
    oracle requires an ADR-Folge-Item.
    """
    assert CROSS_MODUL_DRIFT_WELLE_6_7_WIRE_FORM_ORACLES == (
        "python-python-baseline",
    ), (
        f"CMD-AC-6-7-2 oracle-set anchored to ADR-0066 - must be "
        f"singleton (python-python-baseline,); got "
        f"{CROSS_MODUL_DRIFT_WELLE_6_7_WIRE_FORM_ORACLES!r}"
    )


# ---------------------------------------------------------------------------
# CMD-AC-6-7-3 — Welle-6+7 joint stress-load per-Komponente consistency
# >=99.5%.
#
# Stress profile: subscribe-event-flood + simultaneous recovery-
# restart-points. References Tomás Tag-29 substrate (Phase-2-Acceptance-
# Gate-Erweiterung, PR #197). Both per-Komponente rates must clear the
# 0.995 floor; joint-rate = min(rate_a, rate_b).
# ---------------------------------------------------------------------------


def test_doppel_welle_6_7_cmd_ac_6_7_3_per_komponente_consistency_green(
    mocked_cross_modul_drift_welle_6_7_per_komponente_consistency,
) -> None:
    """CMD-AC-6-7-3: both per-Komponente consistency-rates >=99.5%.

    The Phase-3c-trigger sprint wires this against PR #197 Cross-
    Modul-Stress-Test substrate output broken out per Komponente:
    one rate for subscribe_loop-rust's subscription-event-flood
    handling and one rate for recovery_workflow-rust's simultaneous-
    restart-point reconstruction.
    """
    record = mocked_cross_modul_drift_welle_6_7_per_komponente_consistency(
        MODUL_A, MODUL_B
    )
    assert_cross_modul_drift_welle_6_7_ac_3_per_komponente_consistency(
        record, WELLE_PAIR_LABEL
    )


def test_doppel_welle_6_7_cmd_ac_6_7_3_subscribe_loop_below_floor_blocks(
    mocked_cross_modul_drift_welle_6_7_per_komponente_consistency,
) -> None:
    """CMD-AC-6-7-3 failure-mode: subscribe_loop per-Komponente rate
    below 99.5% floor.

    Even when the aggregate DW-AC-4 stress-test is zero-failure (e.g.
    because the recovery side compensates), CMD-AC-6-7-3 catches a
    subscribe_loop-side consistency degradation below 99.5%.
    """
    record = mocked_cross_modul_drift_welle_6_7_per_komponente_consistency(
        MODUL_A, MODUL_B, modul_a_rate=0.989
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-3"):
        assert_cross_modul_drift_welle_6_7_ac_3_per_komponente_consistency(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_3_recovery_workflow_below_floor_blocks(
    mocked_cross_modul_drift_welle_6_7_per_komponente_consistency,
) -> None:
    """CMD-AC-6-7-3 failure-mode: recovery_workflow per-Komponente rate
    below 99.5% floor.

    Particularly costly here: a recovery_workflow consistency drift
    means restart-points are computed incorrectly, which propagates
    through the entire recovery-pipeline.
    """
    record = mocked_cross_modul_drift_welle_6_7_per_komponente_consistency(
        MODUL_A, MODUL_B, modul_b_rate=0.991
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-3"):
        assert_cross_modul_drift_welle_6_7_ac_3_per_komponente_consistency(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_3_both_below_floor_blocks(
    mocked_cross_modul_drift_welle_6_7_per_komponente_consistency,
) -> None:
    """CMD-AC-6-7-3 failure-mode: both per-Komponente rates below floor.

    Joint-rate (computed as min()) is the lower of the two; the
    assertion-shape lists both failing moduln in the error message
    for operator-side triage.
    """
    record = mocked_cross_modul_drift_welle_6_7_per_komponente_consistency(
        MODUL_A, MODUL_B, modul_a_rate=0.990, modul_b_rate=0.988
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-3"):
        assert_cross_modul_drift_welle_6_7_ac_3_per_komponente_consistency(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_3_consistency_floor_anchored_to_adr_0066() -> None:
    """CMD-AC-6-7-3 sanity: the 99.5% floor is ADR-0066-fixed.

    Shared with Welle-4+5 CMD-AC-3 (same constant
    CROSS_MODUL_DRIFT_CONSISTENCY_PCT_FLOOR = 0.995). Loosening
    requires an ADR-Folge-Item, not a conftest-edit.
    """
    assert CROSS_MODUL_DRIFT_CONSISTENCY_PCT_FLOOR == 0.995, (
        f"CMD-AC-6-7-3 consistency-floor anchored to ADR-0066 - must "
        f"be 0.995 (99.5%); got {CROSS_MODUL_DRIFT_CONSISTENCY_PCT_FLOOR}"
    )


# ---------------------------------------------------------------------------
# CMD-AC-6-7-4 — Drift-triggered atomic single-Komponente rollback with
# Phase-3c-Ende-delay-classification.
#
# Same gate-shape as Welle-4+5 CMD-AC-4 plus the Welle-6+7-specific
# risk surface: a recovery_workflow rollback delays Phase-3c-Ende by
# +1 week (Welle-7 is the closing welle).
# ---------------------------------------------------------------------------


def test_doppel_welle_6_7_cmd_ac_6_7_4_atomic_flip_subscribe_loop_no_delay(
    mocked_cross_modul_drift_welle_6_7_atomic_flip,
) -> None:
    """CMD-AC-6-7-4: subscribe_loop drift > 0.5pp -> atomic flip,
    Phase-3c-Ende-delay = 0 weeks.

    recovery_workflow stays rust-Default. subscribe_loop rollback is
    less costly than recovery_workflow rollback because subscribe_
    loop is Welle-6 (not the closing welle) - Phase-3c-Ende-Tag is
    unaffected.
    """
    record = mocked_cross_modul_drift_welle_6_7_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
        measured_drift_pct=0.78,
    )
    assert_cross_modul_drift_welle_6_7_ac_4_atomic_flip_rollback(
        record, WELLE_PAIR_LABEL
    )
    assert record.phase_3c_ende_delay_weeks == 0, (
        f"subscribe_loop flip must surface delay-weeks=0; got "
        f"{record.phase_3c_ende_delay_weeks}"
    )


def test_doppel_welle_6_7_cmd_ac_6_7_4_atomic_flip_recovery_workflow_one_week_delay(
    mocked_cross_modul_drift_welle_6_7_atomic_flip,
) -> None:
    """CMD-AC-6-7-4: recovery_workflow drift > 0.5pp -> atomic flip,
    Phase-3c-Ende-delay = +1 week.

    The closing-welle rollback impact-surface: Welle-7 is the last
    cutover-welle, so rolling it back delays Phase-3c-Ende by +1
    week. The gate passes (atomic-flip discipline upheld) but the
    delay-classification surfaces in the record for downstream
    operator-hand triage.
    """
    record = mocked_cross_modul_drift_welle_6_7_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_B,
        measured_drift_pct=0.65,
    )
    assert_cross_modul_drift_welle_6_7_ac_4_atomic_flip_rollback(
        record, WELLE_PAIR_LABEL
    )
    assert record.phase_3c_ende_delay_weeks == 1, (
        f"recovery_workflow flip must surface delay-weeks=1; got "
        f"{record.phase_3c_ende_delay_weeks}"
    )


def test_doppel_welle_6_7_cmd_ac_6_7_4_sub_threshold_flip_rejected(
    mocked_cross_modul_drift_welle_6_7_atomic_flip,
) -> None:
    """CMD-AC-6-7-4 failure-mode: spurious sub-threshold flip rejected.

    A flip on measured drift <=0.5pp is spurious. CMD-AC-6-7-4 catches
    runbook over-firing during stress-window noise.
    """
    record = mocked_cross_modul_drift_welle_6_7_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
        measured_drift_pct=0.32,
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-4"):
        assert_cross_modul_drift_welle_6_7_ac_4_atomic_flip_rollback(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_4_partner_contagion_blocks(
    mocked_cross_modul_drift_welle_6_7_atomic_flip,
) -> None:
    """CMD-AC-6-7-4 failure-mode: partner also flipped -> contagious
    rollback rejected.

    Atomic-flip-pattern forbids contagion. A cross-modul-contract bug
    triggers both-rollback through the DW-AC-3 path, not CMD-AC-6-7-4.
    """
    record = mocked_cross_modul_drift_welle_6_7_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
        measured_drift_pct=0.81,
        partner_also_flipped=True,
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-4"):
        assert_cross_modul_drift_welle_6_7_ac_4_atomic_flip_rollback(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_4_non_atomic_flip_blocks(
    mocked_cross_modul_drift_welle_6_7_atomic_flip,
) -> None:
    """CMD-AC-6-7-4 failure-mode: multi-restart-cycle flip rejected."""
    record = mocked_cross_modul_drift_welle_6_7_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_B,
        measured_drift_pct=0.72,
        flip_was_atomic=False,
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-4"):
        assert_cross_modul_drift_welle_6_7_ac_4_atomic_flip_rollback(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_4_sla_violation_blocks(
    mocked_cross_modul_drift_welle_6_7_atomic_flip,
) -> None:
    """CMD-AC-6-7-4 failure-mode: flip-elapsed > 600s SLA."""
    record = mocked_cross_modul_drift_welle_6_7_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
        measured_drift_pct=0.83,
        flip_elapsed_seconds=730.0,
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-4"):
        assert_cross_modul_drift_welle_6_7_ac_4_atomic_flip_rollback(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_4_threshold_anchored_to_adr_0066() -> None:
    """CMD-AC-6-7-4 sanity: the 0.5pp drift-threshold is ADR-0066-fixed.

    Shared with Welle-4+5 CMD-AC-4 (same constant
    CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD = 0.5).
    """
    assert CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD == 0.5, (
        f"CMD-AC-6-7-4 drift-threshold anchored to ADR-0066 - must be "
        f"0.5pp; got {CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD}"
    )
