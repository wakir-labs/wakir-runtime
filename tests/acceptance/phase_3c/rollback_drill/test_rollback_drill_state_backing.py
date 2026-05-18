# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Rollback-Drill — ``state_backing``.

Anchors
-------

- ADR-0065 §Rollback-Strategie (Welle-4 = ``state_backing``,
  persistenter State, höheres Risiko).
- ADR-0066 §Rollback + §Beschluss (Welle-4 = Doppel-Welle mit
  Welle-5 = ``lifecycle_state_machine``, Cross-Modul-Drift-Focus).
- Sister per-welle E2E acceptance file: ``test_welle_4_state_backing_
  e2e.py``.

Komponente character
--------------------

``state_backing`` is the persistent-state surface (NATS-KV-backed JCS
records). Rollback risk profile: **high** — persistent state, schema-
migration-rollback applies for schema-touching changes (2-hour SLA
under ADR-0065 §Rollback-Strategie). This drill verifies the
**non-schema-migration** rollback path: pure ENV-Flag-Switch when no
schema-evolution is in flight, falling under the 10-minute SLA.

For schema-migration rollback see Reza-Folge-Spawn-Artefakt per
ADR-0065 §Folgeartefakte 3 (Schema-Migrations-Rollback-Plan pro
Komponente, scoped to state_backing + lifecycle_state_machine).
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_rd_1_env_flag_switch_effective,
    assert_rd_2_audit_record_documents_rollback,
    assert_rd_3_cross_modul_konsistenz_post_rollback,
    assert_rd_4_time_to_rollback_within_sla,
)

MODUL = "state_backing"

pytestmark = pytest.mark.phase_3c_rollback_drill


def test_rd_1_env_flag_switch_effective(mocked_rollback_event) -> None:
    """RD-1 — ENV-Flag rust→python switch hat Effekt.

    The ``WAKIR_ENGINE_STATE_BACKING_BACKEND`` flag flip from ``rust``
    to ``python`` must re-bind the state-backing read/write path.
    Existing NATS-KV entries are schema-agnostic to the backend (JCS-
    byte-records, content-addressed) so long as no schema-migration
    is in flight. The drill assumes the non-migration path.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_1_env_flag_switch_effective(event, MODUL)


def test_rd_2_audit_record_documents_rollback(mocked_rollback_event) -> None:
    """RD-2 — BackendDecision-Audit-Record dokumentiert Rollback-Event.

    State-backing rollbacks are high-stakes for Henrik-Zone-N because
    persistent-state-touching changes leave a forensic footprint. The
    audit-record must name ``state_backing`` and ``target_backend=
    python`` and carry a non-empty cutover-cycle-id so the audit-
    sample can correlate the rollback boot to the corresponding
    Phase-2-Acceptance-Gate-re-run record.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_2_audit_record_documents_rollback(event, MODUL)


def test_rd_3_cross_modul_konsistenz_post_rollback(
    mocked_phase_2_acceptance_gate,
) -> None:
    """RD-3 — Cross-Modul-Konsistenz nach Rollback grün.

    The critical cross-modul touchpoint is ``state_backing →
    lifecycle_state_machine`` (producer → consumer JCS-record-pair).
    Post-rollback, the Phase-2-Acceptance-Gate stresses this
    touchpoint and verifies byte-parity. ADR-0066 §Beschluss flags
    this Doppel-Welle's Cross-Modul-Drift-Focus as **hoch** — RD-3
    inherits that priority.
    """
    gate = mocked_phase_2_acceptance_gate(MODUL)
    assert_rd_3_cross_modul_konsistenz_post_rollback(gate, MODUL)


def test_rd_4_time_to_rollback_within_sla(mocked_rollback_event) -> None:
    """RD-4 — Time-to-rollback ≤10min SLA.

    State-backing's ENV-Flag-Switch elapsed-time can run slightly
    longer than read-only Komponenten because the NATS-KV-reconnect
    + state-cache-warm-up are additive. The 600s SLA still holds for
    the non-migration path. Schema-migration-rollback (2-hour SLA) is
    a separate drill-surface and out of scope here.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_4_time_to_rollback_within_sla(event, MODUL)
