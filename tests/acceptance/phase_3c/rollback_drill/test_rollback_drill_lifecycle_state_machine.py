# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Rollback-Drill — ``lifecycle_state_machine``.

Anchors
-------

- ADR-0065 §Rollback-Strategie (Welle-5 = ``lifecycle_state_machine``,
  stateful, Cross-Modul-Dependency).
- ADR-0066 §Rollback + §Beschluss (Welle-5 = Doppel-Welle mit Welle-4
  = ``state_backing``, Cross-Modul-Drift-Focus **hoch**).
- Sister per-welle E2E acceptance file: ``test_welle_5_lifecycle_
  state_machine_e2e.py``.

Komponente character
--------------------

``lifecycle_state_machine`` reads from ``state_backing`` and drives
persona-lifecycle transitions. Rollback risk profile: **high** —
stateful, with the producer-consumer contract against state_backing
as the dominant Drift-Risk surface. Per ADR-0066 §Beschluss-Tabelle
this is the second half of Doppel-Welle DW-4+5 (Cross-Modul-Drift-
Focus *hoch*).

The four RD-1...RD-4 gates verify the same ENV-Flag-Switch contract
as state_backing; the cross-modul-Konsistenz-post-rollback (RD-3)
gates the producer/consumer touchpoint specifically.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_rd_1_env_flag_switch_effective,
    assert_rd_2_audit_record_documents_rollback,
    assert_rd_3_cross_modul_konsistenz_post_rollback,
    assert_rd_4_time_to_rollback_within_sla,
)

MODUL = "lifecycle_state_machine"

pytestmark = pytest.mark.phase_3c_rollback_drill


def test_rd_1_env_flag_switch_effective(mocked_rollback_event) -> None:
    """RD-1 — ENV-Flag rust→python switch hat Effekt.

    The ``WAKIR_ENGINE_LIFECYCLE_STATE_MACHINE_BACKEND`` flag flip
    must re-bind the transition-table consumer-end. In-flight
    transitions queue against the next engine-boot under ADR-0065
    §Rollback-Strategie step 2 (``systemctl restart``).
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_1_env_flag_switch_effective(event, MODUL)


def test_rd_2_audit_record_documents_rollback(mocked_rollback_event) -> None:
    """RD-2 — BackendDecision-Audit-Record dokumentiert Rollback-Event.

    For Doppel-Welle DW-4+5 the rollback may be **asymmetric** —
    lifecycle_state_machine alone, or together with state_backing.
    The drill here gates the lifecycle-alone audit-record; the
    Doppel-Welle test-file ``test_doppel_welle_4_5_e2e.py`` covers
    the paired-audit cardinality.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_2_audit_record_documents_rollback(event, MODUL)


def test_rd_3_cross_modul_konsistenz_post_rollback(
    mocked_phase_2_acceptance_gate,
) -> None:
    """RD-3 — Cross-Modul-Konsistenz nach Rollback grün.

    The lifecycle_state_machine ↔ state_backing producer/consumer
    contract is the critical cross-modul touchpoint. Post-rollback
    Phase-2-Acceptance-Gate re-runs the transition-table contract
    against both moduln in their current (possibly mixed) backend-
    state. RD-3 green means the transition-table contract holds
    regardless of asymmetric-rollback shape.
    """
    gate = mocked_phase_2_acceptance_gate(MODUL)
    assert_rd_3_cross_modul_konsistenz_post_rollback(gate, MODUL)


def test_rd_4_time_to_rollback_within_sla(mocked_rollback_event) -> None:
    """RD-4 — Time-to-rollback ≤10min SLA.

    Lifecycle-state-machine rollback elapsed-time is comparable to
    state_backing because both share the engine-boot dominator. The
    600s SLA holds for the non-schema-migration path; schema-migration
    rollback (2-hour SLA) is scoped to a separate Reza-Folge-Artefakt.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_4_time_to_rollback_within_sla(event, MODUL)
