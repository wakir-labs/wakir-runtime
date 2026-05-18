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
    CROSS_MODUL_DRIFT_CONSISTENCY_WELLE_6_7_PCT_FLOOR,
    CROSS_MODUL_DRIFT_ROLLBACK_WELLE_6_7_PCT_THRESHOLD,
    CROSS_MODUL_DRIFT_WELLE_6_7_RECOVERY_TRIGGER_IDS,
    CROSS_MODUL_DRIFT_WELLE_6_7_RECOVERY_TRIGGER_ORACLES,
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
# CMD-AC-6-7-1 — subscribe_loop ack-record → recovery_workflow consume
# round-trip parity (byte-identical schema-deserialization).
#
# subscribe_loop-rust emits ack-records → recovery_workflow-rust consumes
# with byte-identical schema-deserialization. Drills deeper than DW-AC-2
# (single-touchpoint byte-parity on the producer side) by exercising the
# deserialize → re-serialize round-trip on the consumer side, with a
# Welle-6+7-specific cursor-delta-survival sub-gate (Bug-42-adjacent).
# ---------------------------------------------------------------------------


def test_doppel_welle_6_7_cmd_ac_6_7_1_ack_consume_round_trip_parity(
    mocked_cross_modul_drift_welle_6_7_ack_consume,
) -> None:
    """CMD-AC-6-7-1: subscribe_loop-rust → recovery_workflow-rust
    ack-record round-trip byte-identical.

    The Phase-3c-trigger sprint wires this against real wire-form
    output: subscribe_loop-rust emits an ack-record (NATS-ack envelope
    + subscription-cursor delta + keepalive snapshot); recovery_
    workflow-rust reads it, deserialises into the typed Rust struct,
    then re-serialises back to canonical wire-form. The re-serialised
    bytes must be byte-identical to the original.
    """
    records = mocked_cross_modul_drift_welle_6_7_ack_consume(MODUL_A, MODUL_B)
    assert_cross_modul_drift_welle_6_7_ac_1_ack_consume_round_trip(
        records, WELLE_PAIR_LABEL
    )


def test_doppel_welle_6_7_cmd_ac_6_7_1_byte_drift_blocks(
    mocked_cross_modul_drift_welle_6_7_ack_consume,
) -> None:
    """CMD-AC-6-7-1 failure-mode: ack-record deserialization mutates bytes.

    Welle-6+7-specific drift-source: Rust-side serde implementation
    drift between the producer (subscribe_loop-rust) and the consumer
    (recovery_workflow-rust) — e.g. NATS-ack-envelope field-ordering
    drift, keepalive-timestamp formatting drift, or schema-evolution
    drift that survives deserialize but mutates re-serialize.
    """
    records = mocked_cross_modul_drift_welle_6_7_ack_consume(
        MODUL_A,
        MODUL_B,
        drift_ack_ids=("ack-cycle-1",),
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-1"):
        assert_cross_modul_drift_welle_6_7_ac_1_ack_consume_round_trip(
            records, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_1_cursor_breakage_blocks(
    mocked_cross_modul_drift_welle_6_7_ack_consume,
) -> None:
    """CMD-AC-6-7-1 failure-mode: cursor-delta dropped on round-trip.

    This is the Bug-42-adjacent regression-class: a one-byte difference
    or missing field in cursor-delta serialisation causes recovery_
    workflow to compute a wrong restart-point and replay messages
    incorrectly. The Welle-6 Bug-42-Lessons-Learned coverage in
    test_welle_6_subscribe_loop_e2e.py covers the per-welle surface;
    CMD-AC-6-7-1 covers the cross-modul-consumer surface.
    """
    records = mocked_cross_modul_drift_welle_6_7_ack_consume(
        MODUL_A,
        MODUL_B,
        cursor_breakage_ids=("ack-cursor-advance",),
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-1"):
        assert_cross_modul_drift_welle_6_7_ac_1_ack_consume_round_trip(
            records, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# CMD-AC-6-7-2 — recovery_workflow R1..R4 → subscribe_loop Re-subscribe
# trigger wire-form parity vs. python-python-baseline.
#
# recovery_workflow-rust R1..R4 triggert subscribe_loop-rust Re-subscribe
# mit gleicher Wire-Form wie Python-Pendant. Direction is inverted vs.
# CMD-AC-2 (Welle-4+5: consumer → producer write-back); here the
# *consumer* (recovery_workflow) triggers the *producer* (subscribe_loop)
# to Re-subscribe. The wire-form on the trigger-side must byte-match
# the Python-pendant's output.
# ---------------------------------------------------------------------------


def test_doppel_welle_6_7_cmd_ac_6_7_2_resubscribe_trigger_wire_form_all_r1_r4(
    mocked_cross_modul_drift_welle_6_7_resubscribe_trigger,
) -> None:
    """CMD-AC-6-7-2: R1..R4 Re-subscribe-trigger wire-form matches the
    python-python-baseline oracle for every trigger-id.

    The four R1..R4 triggers are recovery_workflow-rust's full
    restart-point-reconstruction trigger taxonomy:

    * R1-cursor-restore — resume from a stored subscription-cursor.
    * R2-keepalive-replay — replay the keepalive-window to re-arm
      the NATS-subscription liveness.
    * R3-backlog-replay — replay buffered backlog messages.
    * R4-terminal-archive-rebuild — rebuild from terminal-archive
      (the last-known-good snapshot path).

    Every trigger-id must produce wire-form byte-identical to the
    python-python pre-Welle-7-cutover production state.
    """
    records = mocked_cross_modul_drift_welle_6_7_resubscribe_trigger(
        MODUL_A, MODUL_B
    )
    assert_cross_modul_drift_welle_6_7_ac_2_resubscribe_trigger_wire_form(
        records, WELLE_PAIR_LABEL
    )


def test_doppel_welle_6_7_cmd_ac_6_7_2_python_baseline_drift_blocks(
    mocked_cross_modul_drift_welle_6_7_resubscribe_trigger,
) -> None:
    """CMD-AC-6-7-2 failure-mode: Rust-Rust trigger diverges from
    python-python-baseline.

    This is a Phase-3c-Ende blocker: if recovery_workflow-rust emits a
    Re-subscribe-trigger wire-form different from the Python pendant,
    subscribe_loop cannot recognise the trigger on records that
    survived the cutover from the Python-Python production era. The
    recovery-restart-point reconstruction silently fails on pre-cutover
    records.
    """
    records = mocked_cross_modul_drift_welle_6_7_resubscribe_trigger(
        MODUL_A,
        MODUL_B,
        drift_trigger_ids=("R3-backlog-replay",),
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-2"):
        assert_cross_modul_drift_welle_6_7_ac_2_resubscribe_trigger_wire_form(
            records, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_2_missing_trigger_blocks(
    mocked_cross_modul_drift_welle_6_7_resubscribe_trigger,
) -> None:
    """CMD-AC-6-7-2 failure-mode: a trigger-id from the R1..R4 set is
    missing from the observed record-set.

    The full R1..R4 taxonomy must be exercised. A missing trigger
    indicates either the test-harness under-instrumented the
    recovery_workflow-rust trigger surface (test-coverage bug) or
    recovery_workflow-rust failed to emit the trigger at all under the
    test scenario (substrate bug). Either way, CMD-AC-6-7-2 blocks.
    """
    records = mocked_cross_modul_drift_welle_6_7_resubscribe_trigger(
        MODUL_A,
        MODUL_B,
        trigger_ids=(
            "R1-cursor-restore",
            "R2-keepalive-replay",
            # R3-backlog-replay deliberately omitted.
            "R4-terminal-archive-rebuild",
        ),
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-2"):
        assert_cross_modul_drift_welle_6_7_ac_2_resubscribe_trigger_wire_form(
            records, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_2_oracle_set_anchored_to_adr_0066() -> None:
    """CMD-AC-6-7-2 sanity: the Welle-6+7 oracle-set is ADR-0066-fixed
    and single-valued (python-python-baseline).

    Unlike CMD-AC-2 (Welle-4+5) which carries two oracles (python-
    python-baseline + python-rust-welle-4-only), Welle-6+7 has only
    python-python-baseline. The mid-Doppel-Welle hypothetical
    (python-rust-welle-6-only) is operationally unreachable because
    subscribe_loop and recovery_workflow share a single cutover-cycle
    under Doppel-Welle-6+7. Adding a Rust-Rust self-referential
    oracle is explicitly forbidden.
    """
    assert CROSS_MODUL_DRIFT_WELLE_6_7_RECOVERY_TRIGGER_ORACLES == (
        "python-python-baseline",
    ), (
        f"CMD-AC-6-7-2 oracle-set anchored to ADR-0066 — must be "
        f"(python-python-baseline,); got "
        f"{CROSS_MODUL_DRIFT_WELLE_6_7_RECOVERY_TRIGGER_ORACLES!r}"
    )


def test_doppel_welle_6_7_cmd_ac_6_7_2_trigger_taxonomy_anchored_to_adr_0066() -> None:
    """CMD-AC-6-7-2 sanity: the R1..R4 trigger taxonomy is ADR-0066-fixed.

    Adding or removing trigger-ids requires an ADR-Folge-Item, not a
    conftest-edit. The four trigger-ids match recovery_workflow-rust's
    documented restart-point-reconstruction surface.
    """
    assert CROSS_MODUL_DRIFT_WELLE_6_7_RECOVERY_TRIGGER_IDS == (
        "R1-cursor-restore",
        "R2-keepalive-replay",
        "R3-backlog-replay",
        "R4-terminal-archive-rebuild",
    ), (
        f"CMD-AC-6-7-2 trigger-taxonomy anchored to ADR-0066 — must be "
        f"(R1-cursor-restore, R2-keepalive-replay, R3-backlog-replay, "
        f"R4-terminal-archive-rebuild); got "
        f"{CROSS_MODUL_DRIFT_WELLE_6_7_RECOVERY_TRIGGER_IDS!r}"
    )


# ---------------------------------------------------------------------------
# CMD-AC-6-7-3 — Cross-Modul-Stress-Test per-Komponente consistency
# ≥99.5% (Welle-6+7-specific stress profile, PR #197 substrate).
#
# PR #197 Cross-Modul-Stress-Test substrate joint-load output split by
# Komponente. DW-AC-4 sets zero-failure-floor on the aggregate; CMD-
# AC-6-7-3 sets a per-Komponente consistency-rate ≥99.5% floor over
# the Welle-6+7-realistic joint-load (subscribe-event-flood +
# simultaneous recovery-restart-points).
# ---------------------------------------------------------------------------


def test_doppel_welle_6_7_cmd_ac_6_7_3_per_komponente_consistency_green(
    mocked_cross_modul_drift_welle_6_7_per_komponente_consistency,
) -> None:
    """CMD-AC-6-7-3: both per-Komponente consistency-rates ≥99.5%.

    The Phase-3c-trigger sprint wires this against PR #197 Cross-
    Modul-Stress-Test substrate output broken out per Komponente for
    the Welle-6+7 joint-load:

    * subscribe_loop-rust Rust-side NATS-subscribe-cycle consistency
      under the subscribe-event-flood profile.
    * recovery_workflow-rust Rust-side restart-point-reconstruction
      consistency during the same window with simultaneous recovery
      restart-points.
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

    Even if the aggregate DW-AC-4 stress-test is zero-failure (e.g.
    because recovery_workflow compensates with retries), CMD-AC-6-7-3
    catches a subscribe_loop-side consistency degradation below 99.5%
    — typically a NATS-reconnect-storm regression under stress.
    """
    record = mocked_cross_modul_drift_welle_6_7_per_komponente_consistency(
        MODUL_A, MODUL_B, modul_a_rate=0.991
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-3"):
        assert_cross_modul_drift_welle_6_7_ac_3_per_komponente_consistency(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_3_recovery_below_floor_blocks(
    mocked_cross_modul_drift_welle_6_7_per_komponente_consistency,
) -> None:
    """CMD-AC-6-7-3 failure-mode: recovery_workflow per-Komponente rate
    below floor.

    A recovery-side consistency degradation below 99.5% indicates the
    Rust-recovery-orchestrator drops or mis-orders restart-point
    triggers under stress — operationally signals a Welle-7-blocker.
    """
    record = mocked_cross_modul_drift_welle_6_7_per_komponente_consistency(
        MODUL_A, MODUL_B, modul_b_rate=0.988
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-3"):
        assert_cross_modul_drift_welle_6_7_ac_3_per_komponente_consistency(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_3_both_below_floor_blocks(
    mocked_cross_modul_drift_welle_6_7_per_komponente_consistency,
) -> None:
    """CMD-AC-6-7-3 failure-mode: both per-Komponente rates below floor.

    Joint-rate (min()) is the lower of the two; the assertion-shape
    lists both failing moduln in the error.
    """
    record = mocked_cross_modul_drift_welle_6_7_per_komponente_consistency(
        MODUL_A, MODUL_B, modul_a_rate=0.992, modul_b_rate=0.989
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-3"):
        assert_cross_modul_drift_welle_6_7_ac_3_per_komponente_consistency(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_3_consistency_floor_anchored_to_adr_0066() -> None:
    """CMD-AC-6-7-3 sanity: the 99.5% floor is ADR-0066-fixed and
    consistent with CMD-AC-3 (Welle-4+5).

    Loosening this floor per-Doppel-Welle would require an ADR-Folge-
    Item; the floor is uniform across the two DWs carrying the CMD-AC
    layer.
    """
    assert CROSS_MODUL_DRIFT_CONSISTENCY_WELLE_6_7_PCT_FLOOR == 0.995, (
        f"CMD-AC-6-7-3 consistency-floor anchored to ADR-0066 — must "
        f"be 0.995 (99.5%); got "
        f"{CROSS_MODUL_DRIFT_CONSISTENCY_WELLE_6_7_PCT_FLOOR}"
    )


# ---------------------------------------------------------------------------
# CMD-AC-6-7-4 — Drift-triggered atomic single-Komponente rollback for
# Welle-6+7 (atomic-flip-pattern, ≤10min ENV-Flag-Switch SLA).
#
# Rollback einer Komponente bei Drift > 0.5pp, andere bleibt rust-
# Default (atomic-flip-pattern). Drills deeper than DW-AC-3 (manual-
# operator asymmetric rollback) by enforcing the drift-magnitude
# trigger-precondition and the atomicity property.
#
# Welle-6+7-specific risk: a recovery_workflow rollback delays Phase-3c-
# Ende + ADR-0035-C-Drift-Closure by ≥1 week because recovery is the
# last welle; the atomic-flip discipline minimises blast-radius.
# ---------------------------------------------------------------------------


def test_doppel_welle_6_7_cmd_ac_6_7_4_atomic_flip_high_drift_subscribe_loop(
    mocked_cross_modul_drift_welle_6_7_atomic_flip,
) -> None:
    """CMD-AC-6-7-4: subscribe_loop drift > 0.5pp → atomic flip to python.

    recovery_workflow stays rust-Default. The Phase-3c-trigger sprint
    wires this against the real Operator-Hand-runbook atomic-flip
    script (single ``systemctl restart`` cycle, ENV-flag rewrite,
    post-flip backend-state verification).
    """
    record = mocked_cross_modul_drift_welle_6_7_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
        measured_drift_pct=0.75,
    )
    assert_cross_modul_drift_welle_6_7_ac_4_atomic_flip_rollback(
        record, WELLE_PAIR_LABEL
    )


def test_doppel_welle_6_7_cmd_ac_6_7_4_atomic_flip_high_drift_recovery_workflow(
    mocked_cross_modul_drift_welle_6_7_atomic_flip,
) -> None:
    """CMD-AC-6-7-4 direction-check: recovery_workflow drift > 0.5pp →
    flip recovery_workflow.

    subscribe_loop stays rust-Default. A recovery_workflow flip is
    particularly costly (last-welle, blocks Phase-3c-Ende), so the
    atomic-flip discipline confines the rollback to recovery_workflow
    only and preserves the subscribe_loop progress on rust.
    """
    record = mocked_cross_modul_drift_welle_6_7_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_B,
        measured_drift_pct=0.62,
    )
    assert_cross_modul_drift_welle_6_7_ac_4_atomic_flip_rollback(
        record, WELLE_PAIR_LABEL
    )


def test_doppel_welle_6_7_cmd_ac_6_7_4_sub_threshold_flip_rejected(
    mocked_cross_modul_drift_welle_6_7_atomic_flip,
) -> None:
    """CMD-AC-6-7-4 failure-mode: spurious sub-threshold flip rejected.

    A flip on measured drift ≤0.5pp is spurious — the Operator-Hand-
    runbook must not fire an atomic-flip on sub-threshold drift. The
    operationally-relevant bar is uniformly 0.5pp across the two CMD-
    AC-carrying Doppel-Wellen.
    """
    record = mocked_cross_modul_drift_welle_6_7_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
        measured_drift_pct=0.30,
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-4"):
        assert_cross_modul_drift_welle_6_7_ac_4_atomic_flip_rollback(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_4_partner_contagion_blocks(
    mocked_cross_modul_drift_welle_6_7_atomic_flip,
) -> None:
    """CMD-AC-6-7-4 failure-mode: partner also flipped → contagious rollback.

    Atomic-flip-pattern forbids contagious rollback: only the high-
    drift modul flips; the partner stays rust. A cross-modul-contract
    bug triggers both-rollback through the DW-AC-3 path (not CMD-AC-
    6-7-4); this gate covers exclusively the single-modul-drift path.
    """
    record = mocked_cross_modul_drift_welle_6_7_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
        measured_drift_pct=0.85,
        partner_also_flipped=True,
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-4"):
        assert_cross_modul_drift_welle_6_7_ac_4_atomic_flip_rollback(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_4_non_atomic_flip_blocks(
    mocked_cross_modul_drift_welle_6_7_atomic_flip,
) -> None:
    """CMD-AC-6-7-4 failure-mode: non-atomic flip (multi-restart-cycle).

    The Operator-Hand-runbook is single-shot. A multi-cycle flip
    indicates the runbook drifted from the atomic-flip-pattern; the
    intermediate state where one modul is mid-flip risks contract
    violations between subscribe_loop and recovery_workflow during
    the flip-window.
    """
    record = mocked_cross_modul_drift_welle_6_7_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
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
    """CMD-AC-6-7-4 failure-mode: flip-elapsed exceeds 10min SLA.

    Same ENV-Flag-Switch SLA as DW-AC-3 (600s). A slow atomic-flip
    extends the cross-modul-drift-window and is operationally
    indistinguishable from a non-atomic flip from the substrate's
    perspective.
    """
    record = mocked_cross_modul_drift_welle_6_7_atomic_flip(
        MODUL_A,
        MODUL_B,
        high_drift_modul=MODUL_A,
        measured_drift_pct=0.78,
        flip_elapsed_seconds=820.0,
    )
    with pytest.raises(AssertionError, match="CMD-AC-6-7-4"):
        assert_cross_modul_drift_welle_6_7_ac_4_atomic_flip_rollback(
            record, WELLE_PAIR_LABEL
        )


def test_doppel_welle_6_7_cmd_ac_6_7_4_threshold_anchored_to_adr_0066() -> None:
    """CMD-AC-6-7-4 sanity: the 0.5pp drift-threshold is ADR-0066-fixed.

    Tightening or loosening the threshold requires an ADR-Folge-Item,
    not a conftest-edit. The 0.5pp value is consistent with CMD-AC-4
    (Welle-4+5) — both CMD-AC-carrying Doppel-Wellen share the
    operationally-relevant atomic-flip bar.
    """
    assert CROSS_MODUL_DRIFT_ROLLBACK_WELLE_6_7_PCT_THRESHOLD == 0.5, (
        f"CMD-AC-6-7-4 drift-threshold anchored to ADR-0066 — must be "
        f"0.5pp; got {CROSS_MODUL_DRIFT_ROLLBACK_WELLE_6_7_PCT_THRESHOLD}"
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
