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
    assert_dw_ac_1_both_moduln_boot_rust,
    assert_dw_ac_2_cross_modul_schema_byte_parity,
    assert_dw_ac_3_asymmetric_rollback,
    assert_dw_ac_4_cross_modul_stress_test_green,
    assert_dw_ac_5_backend_decision_audit_two_records_consistent,
)
from .conftest import DOPPEL_WELLE_BY_PAIR

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
