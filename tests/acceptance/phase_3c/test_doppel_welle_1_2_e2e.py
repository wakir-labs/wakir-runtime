# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Doppel-Welle-1+2 E2E acceptance — ``v907_verify`` +
``svid_workload_identity`` parallel cutover (KW 24).

Anchors
-------

- ADR-0066 §Beschluss — Doppel-Welle KW 24: Welle-1 + Welle-2 parallel.
- ADR-0066 §Mitigations §3 — Cutover-Mittwoch bleibt fix; Mo Dry-Run
  beider, Mi gleichzeitig Cutover, Fr Acceptance-Decision beider.
- ADR-0065 §Rollback-Strategie — ENV-Flag-Switch ≤10min SLA pro
  Komponente (asymmetrischer Rollback unter Doppel-Welle).
- ``test_welle_1_v907_verify_e2e.py`` + ``test_welle_2_svid_workload_
  identity_e2e.py`` — per-welle sister files this doppel-welle file
  extends with cross-modul-parallel-cutover acceptance.

Doppel-Welle character
----------------------

Welle-1 + Welle-2 is the **read-only-paar**: both moduln are read-only
pathways (V-907-pin-attest verify + SPIRE-SVID-workload-identity-
lookup). Lowest blast-radius of the three Doppel-Wellen because
neither modul mutates persistent state nor holds long-lived
subscriptions.

Cross-Modul-Drift-Focus is **low** here — the two moduln share no
schema, no state, no NATS-subject. The Cross-Modul-Stress-Test
(DW-AC-4) primarily verifies that *under joint load*, neither modul's
Rust-backend produces unexpected drift in the *other*'s envelope-trail
(e.g. accidental shared-cache contention in the engine-runtime).

Per ADR-0066 §Mitigation 1, Welle-1+2 has Standard-Acceptance: no
extended cross-modul-stress-window beyond the Phase-2-Acceptance-Gate-
baseline.

Skip-by-default
---------------

All tests carry the ``phase_3c_doppel_welle_acceptance`` marker.
Conftest-level skip unless ``WAKIR_PHASE_3C_DOPPEL_E2E=1`` env-var
is set OR the ``--phase-3c-doppel-welle-acceptance`` CLI flag is
passed.
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

MODUL_A = "v907_verify"
MODUL_B = "svid_workload_identity"
WELLE_PAIR_LABEL = f"KW24:{MODUL_A}+{MODUL_B}"
EXPECTED_KW = DOPPEL_WELLE_BY_PAIR[(MODUL_A, MODUL_B)]

pytestmark = pytest.mark.phase_3c_doppel_welle_acceptance


def test_doppel_welle_1_2_anchored_to_kw_24() -> None:
    """Sanity: this file targets the ADR-0066 KW 24 Doppel-Welle pair.

    Guards against accidental modul-name typos cascading into AC-helper
    calls with wrong pair-identity.
    """
    assert EXPECTED_KW == "KW24", (
        f"Doppel-Welle-1+2 must anchor to KW24 per ADR-0066 §Beschluss; "
        f"got {EXPECTED_KW!r}"
    )


# ---------------------------------------------------------------------------
# DW-AC-1 — Both Doppel-Welle moduln boot with rust-backend.
# ---------------------------------------------------------------------------


def test_doppel_welle_1_2_dw_ac_1_both_moduln_boot_rust(
    mocked_engine_boot_doppel,
) -> None:
    """DW-AC-1: v907_verify + svid_workload_identity both on rust-backend.

    The Cutover-Mittwoch-Doppel-Cutover (ADR-0066 §Mitigation 3) flips
    both moduln in a single engine-boot-cycle. Other five moduln stay
    on Python pre-Welle-3.
    """
    boot = mocked_engine_boot_doppel(MODUL_A, MODUL_B)
    assert_dw_ac_1_both_moduln_boot_rust(
        boot, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
    )


def test_doppel_welle_1_2_dw_ac_1_boot_failure_blocks(
    mocked_engine_boot_doppel,
) -> None:
    """DW-AC-1 failure-mode: engine-boot fails → both rollback.

    Per ADR-0066 §Rollback-Strategie, a boot-failure under Doppel-Welle
    conditions triggers a *both-modul* rollback (different from the
    asymmetric single-Komponente-Rollback covered by DW-AC-3, which
    fires post-boot on a runtime-bug).
    """
    boot = mocked_engine_boot_doppel(MODUL_A, MODUL_B, boot_succeeded=False)
    with pytest.raises(AssertionError, match="DW-AC-1"):
        assert_dw_ac_1_both_moduln_boot_rust(
            boot, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# DW-AC-2 — Cross-Modul-Schema-Konsistenz (byte-paritär).
# ---------------------------------------------------------------------------


def test_doppel_welle_1_2_dw_ac_2_cross_modul_schema_byte_parity(
    mocked_cross_modul_schema,
) -> None:
    """DW-AC-2: read-only pair has minimal cross-modul-touchpoints.

    For Welle-1+2 the only meaningful touchpoint is the engine-runtime
    shared substrate (logging-context, persona-def-cache reference).
    Byte-parity is required across the touchpoint set.
    """
    records = mocked_cross_modul_schema(
        MODUL_A,
        MODUL_B,
        touchpoint_ids=(
            "tp-engine-runtime-context",
            "tp-persona-def-cache-ref",
            "tp-shared-logging-frame",
        ),
    )
    assert_dw_ac_2_cross_modul_schema_byte_parity(records, WELLE_PAIR_LABEL)


def test_doppel_welle_1_2_dw_ac_2_byte_drift_blocks(
    mocked_cross_modul_schema,
) -> None:
    """DW-AC-2 failure-mode: any touchpoint byte-drift blocks the gate."""
    records = mocked_cross_modul_schema(
        MODUL_A,
        MODUL_B,
        drift_touchpoint_ids=("tp-update",),
    )
    with pytest.raises(AssertionError, match="DW-AC-2"):
        assert_dw_ac_2_cross_modul_schema_byte_parity(
            records, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# DW-AC-3 — Asymmetric single-Komponente-Rollback (one rolls back,
# partner stays rust).
# ---------------------------------------------------------------------------


def test_doppel_welle_1_2_dw_ac_3_rollback_v907_partner_stays_rust(
    mocked_single_komponente_rollback,
) -> None:
    """DW-AC-3: bug in v907_verify → only v907_verify rolls back to python.

    svid_workload_identity stays on rust. Elapsed-seconds ≤ 600s SLA.
    """
    record = mocked_single_komponente_rollback(
        MODUL_A,
        MODUL_B,
        rolled_back_modul=MODUL_A,
    )
    assert_dw_ac_3_asymmetric_rollback(record, WELLE_PAIR_LABEL)


def test_doppel_welle_1_2_dw_ac_3_rollback_svid_partner_stays_rust(
    mocked_single_komponente_rollback,
) -> None:
    """DW-AC-3: symmetric direction-check — bug in svid → svid rolls back.

    v907_verify stays on rust.
    """
    record = mocked_single_komponente_rollback(
        MODUL_A,
        MODUL_B,
        rolled_back_modul=MODUL_B,
    )
    assert_dw_ac_3_asymmetric_rollback(record, WELLE_PAIR_LABEL)


def test_doppel_welle_1_2_dw_ac_3_sla_violation_blocks(
    mocked_single_komponente_rollback,
) -> None:
    """DW-AC-3 failure-mode: rollback >10min blocks the gate."""
    record = mocked_single_komponente_rollback(
        MODUL_A,
        MODUL_B,
        rolled_back_modul=MODUL_A,
        elapsed_seconds=720.0,  # > 600s SLA
    )
    with pytest.raises(AssertionError, match="DW-AC-3"):
        assert_dw_ac_3_asymmetric_rollback(record, WELLE_PAIR_LABEL)


def test_doppel_welle_1_2_dw_ac_3_both_rolled_back_blocks(
    mocked_single_komponente_rollback,
) -> None:
    """DW-AC-3 failure-mode: partner-also-rolled-back is wrong shape.

    Under Doppel-Welle, single-Komponente-Rollback is the asymmetric
    happy-path; a both-rolled-back path means a *cross-modul-bug* and
    is governed by a different runbook (covered by Henrik Zone-N
    audit-trail, not by DW-AC-3 directly).
    """
    record = mocked_single_komponente_rollback(
        MODUL_A,
        MODUL_B,
        rolled_back_modul=MODUL_A,
        partner_also_rolled_back=True,
    )
    with pytest.raises(AssertionError, match="DW-AC-3"):
        assert_dw_ac_3_asymmetric_rollback(record, WELLE_PAIR_LABEL)


# ---------------------------------------------------------------------------
# DW-AC-4 — Cross-Modul-Stress-Test grün.
# ---------------------------------------------------------------------------


def test_doppel_welle_1_2_dw_ac_4_cross_modul_stress_test_green(
    mocked_cross_modul_stress_test,
) -> None:
    """DW-AC-4: read-only-paar joint-load stress green (no engine-runtime
    cache-contention, no shared-logging-frame drift).

    References Tomás Tag-29 Cross-Modul-Stress-Test substrate
    (Phase-2-Acceptance-Gate-Erweiterung per ADR-0066 §Mitigation 1).
    """
    record = mocked_cross_modul_stress_test(MODUL_A, MODUL_B, total=1000)
    assert_dw_ac_4_cross_modul_stress_test_green(record, WELLE_PAIR_LABEL)


def test_doppel_welle_1_2_dw_ac_4_schema_drift_blocks(
    mocked_cross_modul_stress_test,
) -> None:
    """DW-AC-4 failure-mode: any cross-modul-schema-drift blocks."""
    record = mocked_cross_modul_stress_test(
        MODUL_A, MODUL_B, total=1000, schema_drifts=1
    )
    with pytest.raises(AssertionError, match="DW-AC-4"):
        assert_dw_ac_4_cross_modul_stress_test_green(
            record, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# DW-AC-5 — Backend-Decision-Audit emits 2 records consistently.
# ---------------------------------------------------------------------------


def test_doppel_welle_1_2_dw_ac_5_backend_decision_audit_two_records(
    mocked_backend_decision_audit,
) -> None:
    """DW-AC-5: Cutover-Mittwoch emits exactly 2 backend-decision-audit
    records, both in the same cutover-cycle, both targeting rust.
    """
    records = mocked_backend_decision_audit(MODUL_A, MODUL_B)
    assert_dw_ac_5_backend_decision_audit_two_records_consistent(
        records, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
    )


def test_doppel_welle_1_2_dw_ac_5_missing_modul_record_blocks(
    mocked_backend_decision_audit,
) -> None:
    """DW-AC-5 failure-mode: only one record emitted blocks the gate."""
    records = mocked_backend_decision_audit(
        MODUL_A, MODUL_B, missing_modul=MODUL_B
    )
    with pytest.raises(AssertionError, match="DW-AC-5"):
        assert_dw_ac_5_backend_decision_audit_two_records_consistent(
            records, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
        )


def test_doppel_welle_1_2_dw_ac_5_cycle_id_drift_blocks(
    mocked_backend_decision_audit,
) -> None:
    """DW-AC-5 failure-mode: two records in *different* cutover-cycles
    means they were sequential, not parallel — the Doppel-Welle parallel-
    cutover discipline is broken.
    """
    records = mocked_backend_decision_audit(
        MODUL_A, MODUL_B, drift_cycle_id=True
    )
    with pytest.raises(AssertionError, match="DW-AC-5"):
        assert_dw_ac_5_backend_decision_audit_two_records_consistent(
            records, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
        )


def test_doppel_welle_1_2_dw_ac_5_wrong_target_backend_blocks(
    mocked_backend_decision_audit,
) -> None:
    """DW-AC-5 failure-mode: one record's target_backend is not 'rust'."""
    records = mocked_backend_decision_audit(
        MODUL_A, MODUL_B, wrong_target_backend="python"
    )
    with pytest.raises(AssertionError, match="DW-AC-5"):
        assert_dw_ac_5_backend_decision_audit_two_records_consistent(
            records, MODUL_A, MODUL_B, WELLE_PAIR_LABEL
        )


# ---------------------------------------------------------------------------
# Doppel-Welle-1+2 substrate sanity — Cutover-Mittwoch runbook drill.
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="pending Doppel-Welle-cutover — Cutover-Mittwoch runbook drill"
)
def test_doppel_welle_1_2_cutover_mittwoch_runbook_drill() -> None:
    """Doppel-Welle-1+2 Cutover-Mittwoch-Drill: Mo Dry-Run, Mi parallel
    Cutover, Fr Acceptance-Decision (ADR-0066 §Mitigation 3).

    Operator-Hand drill substrate; hermetic skeleton placeholder. The
    Doppel-Welle-trigger sprint wires this against the real
    ``systemctl restart wakir-persona-engine`` + ENV-rewrite cadence.
    """
    raise NotImplementedError("pending Doppel-Welle-cutover")
