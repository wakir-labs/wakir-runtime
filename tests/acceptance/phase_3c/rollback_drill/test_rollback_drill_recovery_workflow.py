# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Rollback-Drill — ``recovery_workflow``.

Anchors
-------

- ADR-0065 §Rollback-Strategie (Welle-7 = ``recovery_workflow``,
  komplexester Pfad, zuletzt).
- ADR-0066 §Rollback + §Beschluss (Welle-7 = Doppel-Welle mit Welle-6
  = ``subscribe_loop``, Phase-3c-Closing-Cutover).
- Sister per-welle E2E acceptance file: ``test_welle_7_recovery_
  workflow_e2e.py``.

Komponente character
--------------------

``recovery_workflow`` is the cross-modul-orchestration surface that
coordinates recovery-decisions across state_backing, lifecycle_state_
machine, and subscribe_loop. Rollback risk profile: **highest** —
ADR-0065 §Verifikations-Plan ranks recovery_workflow last in the
welle-sequence specifically because its blast-radius touches the
full Phase-3c-Komponenten-Inventory.

The four RD-1...RD-4 gates verify the ENV-Flag-Switch contract under
the most demanding cross-modul-load. The Doppel-Welle DW-6+7 test-
file ``test_doppel_welle_6_7_e2e.py`` covers the paired-rollback
shape; this file covers the single-Komponente rollback in isolation.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_rd_1_env_flag_switch_effective,
    assert_rd_2_audit_record_documents_rollback,
    assert_rd_3_cross_modul_konsistenz_post_rollback,
    assert_rd_4_time_to_rollback_within_sla,
)

MODUL = "recovery_workflow"

pytestmark = pytest.mark.phase_3c_rollback_drill


def test_rd_1_env_flag_switch_effective(mocked_rollback_event) -> None:
    """RD-1 — ENV-Flag rust→python switch hat Effekt.

    The ``WAKIR_ENGINE_RECOVERY_WORKFLOW_BACKEND`` flag flip re-binds
    the recovery-decision orchestrator. In-flight recovery cycles
    queue against the next engine-boot; the engine completes the
    current recovery-cycle under the old backend before the switch
    takes effect (recovery-cycles are designed for atomic completion).
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_1_env_flag_switch_effective(event, MODUL)


def test_rd_2_audit_record_documents_rollback(mocked_rollback_event) -> None:
    """RD-2 — BackendDecision-Audit-Record dokumentiert Rollback-Event.

    Recovery-workflow is the **Welle-Ende-handoff** Komponente
    (ADR-0065 §Welle-Ende-Acceptance WE-1...WE-4). A rollback at this
    point is the highest-stakes case in the entire Phase-3c-Welle —
    the audit-trail integrity is non-negotiable for the Welle-Ende
    Henrik-Audit-Compliance-Check (WE-3).
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_2_audit_record_documents_rollback(event, MODUL)


def test_rd_3_cross_modul_konsistenz_post_rollback(
    mocked_phase_2_acceptance_gate,
) -> None:
    """RD-3 — Cross-Modul-Konsistenz nach Rollback grün.

    Recovery-workflow's post-rollback cross-modul verification covers
    the broadest surface: recovery-decisions are inputs to state_
    backing-writes and outputs from lifecycle_state_machine-transitions
    + subscribe_loop-events. The Phase-2-Acceptance-Gate re-run probes
    all three downstream touchpoints in a single sample.
    """
    gate = mocked_phase_2_acceptance_gate(MODUL)
    assert_rd_3_cross_modul_konsistenz_post_rollback(gate, MODUL)


def test_rd_4_time_to_rollback_within_sla(mocked_rollback_event) -> None:
    """RD-4 — Time-to-rollback ≤10min SLA.

    Recovery-workflow's rollback elapsed-time has the highest tail-
    risk because in-flight recovery-cycles must complete atomically
    before the engine-boot proceeds. The 600s SLA assumes typical
    recovery-cycle duration ≤2min; longer-running recovery-cycles
    fall under the operator-runbook escalation-path, not the
    standard 10-minute drill.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_4_time_to_rollback_within_sla(event, MODUL)
