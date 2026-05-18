# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Rollback-Drill — ``subscribe_loop``.

Anchors
-------

- ADR-0065 §Rollback-Strategie (Welle-6 = ``subscribe_loop``, NATS-
  Subscribe, Bug-42-Lessons-Learned-hot).
- ADR-0066 §Rollback + §Beschluss (Welle-6 = Doppel-Welle mit Welle-7
  = ``recovery_workflow``).
- Sister per-welle E2E acceptance file: ``test_welle_6_subscribe_
  loop_e2e.py``.

Komponente character
--------------------

``subscribe_loop`` runs the long-lived NATS-JetStream subscription
loop. Rollback risk profile: **high** — Bug-42 (PR #67) flagged
subscription-cursor-position-resumption as the dominant pitfall.
The ENV-Flag-Switch back to ``python`` must preserve the JetStream-
cursor-position via the durable-consumer name (NATS-side state, not
engine-side).

The four RD-1...RD-4 gates verify:
* RD-1: engine binding flipped.
* RD-2: rollback audit-record emitted.
* RD-3: post-rollback re-subscribe replays from the correct cursor
  (Phase-2-Acceptance-Gate cross-modul-touchpoint covers this).
* RD-4: rollback elapsed-time inside SLA (includes JetStream-reconnect
  + cursor-resume latency).
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_rd_1_env_flag_switch_effective,
    assert_rd_2_audit_record_documents_rollback,
    assert_rd_3_cross_modul_konsistenz_post_rollback,
    assert_rd_4_time_to_rollback_within_sla,
)

MODUL = "subscribe_loop"

pytestmark = pytest.mark.phase_3c_rollback_drill


def test_rd_1_env_flag_switch_effective(mocked_rollback_event) -> None:
    """RD-1 — ENV-Flag rust→python switch hat Effekt.

    The ``WAKIR_ENGINE_SUBSCRIBE_LOOP_BACKEND`` flag flip must re-bind
    the JetStream-subscription-handler. Durable-consumer-name is
    preserved across the switch, so the NATS-side cursor-position is
    not lost — Bug-42 lessons-learned (PR #67).
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_1_env_flag_switch_effective(event, MODUL)


def test_rd_2_audit_record_documents_rollback(mocked_rollback_event) -> None:
    """RD-2 — BackendDecision-Audit-Record dokumentiert Rollback-Event.

    Subscribe-loop rollback emits a Backend-Decision-Audit-Record
    with ``modul=subscribe_loop``, ``target_backend=python``, and
    the cutover-cycle-id tying it to the post-rollback Phase-2-
    Acceptance-Gate re-run sample.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_2_audit_record_documents_rollback(event, MODUL)


def test_rd_3_cross_modul_konsistenz_post_rollback(
    mocked_phase_2_acceptance_gate,
) -> None:
    """RD-3 — Cross-Modul-Konsistenz nach Rollback grün.

    The critical post-rollback verification is replay-correctness:
    the JetStream cursor must resume at the correct sequence-number
    and the python-backend must produce the same downstream events
    as the rust-backend would have. The Phase-2-Acceptance-Gate
    re-run gates this surface.
    """
    gate = mocked_phase_2_acceptance_gate(MODUL)
    assert_rd_3_cross_modul_konsistenz_post_rollback(gate, MODUL)


def test_rd_4_time_to_rollback_within_sla(mocked_rollback_event) -> None:
    """RD-4 — Time-to-rollback ≤10min SLA.

    Subscribe-loop rollback elapsed-time has two additive components:
    engine-boot-time + JetStream-reconnect-time (durable-consumer
    catch-up to cursor-position). The 600s SLA accommodates both
    under steady-state NATS-server-load; under heavy lag the operator-
    runbook flags the slow-rollback path as a separate signal.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_4_time_to_rollback_within_sla(event, MODUL)
