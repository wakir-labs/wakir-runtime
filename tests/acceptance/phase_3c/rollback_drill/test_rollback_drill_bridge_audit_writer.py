# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Rollback-Drill — ``bridge_audit_writer``.

Anchors
-------

- ADR-0065 §Rollback-Strategie (Welle-3 = ``bridge_audit_writer``,
  Write-Pfad, aber idempotent — WAT-Hash-Anchored).
- ADR-0066 §Rollback + §Beschluss (Welle-3 = Solo-Welle, Henrik-
  Caution-Carve-out — independent unabhängige Konsistenz-Oracle vor
  Welle-3-Cutover).
- Sister per-welle E2E acceptance file: ``test_welle_3_bridge_audit_
  writer_e2e.py``.

Komponente character
--------------------

``bridge_audit_writer`` is the WAT-anchor-write surface that ties the
two backends (Python/Rust) into the same anchor-sink. Rollback risk
profile: **mid** — write-path, but every write is idempotent because
the anchor is content-addressed by SHA-256. The ENV-Flag-Switch back
to ``python`` re-binds the writer; in-flight anchor-writes simply
repeat under the python-backend, producing the same SHA-256 because
JCS-byte-input is identical.

Henrik-Zone-N watches this rollback particularly closely: bridge-
audit-writer *is* the audit-trail substrate. A rollback that breaks
the bridge-audit-writer's own audit-trail is a Zone-N-emergency.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_rd_1_env_flag_switch_effective,
    assert_rd_2_audit_record_documents_rollback,
    assert_rd_3_cross_modul_konsistenz_post_rollback,
    assert_rd_4_time_to_rollback_within_sla,
)

MODUL = "bridge_audit_writer"

pytestmark = pytest.mark.phase_3c_rollback_drill


def test_rd_1_env_flag_switch_effective(mocked_rollback_event) -> None:
    """RD-1 — ENV-Flag rust→python switch hat Effekt.

    The bridge-audit-writer backend selector flips from ``rust`` to
    ``python``. Because anchor-writes are content-addressed by SHA-256
    over JCS-bytes, the switch is functionally invisible to the
    anchor-sink — but the engine-internal binding must reflect the
    new flag-state for the next write-call.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_1_env_flag_switch_effective(event, MODUL)


def test_rd_2_audit_record_documents_rollback(mocked_rollback_event) -> None:
    """RD-2 — BackendDecision-Audit-Record dokumentiert Rollback-Event.

    Zone-N-critical: the bridge-audit-writer rollback must itself emit
    an audit-record into the (still-online) audit-trail. The drill
    asserts that the audit-record names ``bridge_audit_writer`` and
    targets ``python``. ADR-0066 §Beschluss carves Welle-3 out as a
    Solo-Welle precisely because this Komponente's audit-trail-
    integrity demands an unabhängige Konsistenz-Oracle pre-rollback.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_2_audit_record_documents_rollback(event, MODUL)


def test_rd_3_cross_modul_konsistenz_post_rollback(
    mocked_phase_2_acceptance_gate,
) -> None:
    """RD-3 — Cross-Modul-Konsistenz nach Rollback grün.

    Post-rollback, the WAT-anchor-sink's most recent anchors (the
    last batch produced under the rust-backend) must be byte-
    consistent with what the python-backend produces under the same
    input. The Phase-2-Acceptance-Gate replays the recent batch
    against the python-backend and compares SHA-256s — the gate is
    green when no drift is observed.
    """
    gate = mocked_phase_2_acceptance_gate(MODUL)
    assert_rd_3_cross_modul_konsistenz_post_rollback(gate, MODUL)


def test_rd_4_time_to_rollback_within_sla(mocked_rollback_event) -> None:
    """RD-4 — Time-to-rollback ≤10min SLA.

    Bridge-audit-writer rollback elapsed-time is bounded by engine-
    boot-time + WAT-anchor-sink-reconnect-time. The 600s SLA holds
    so long as no schema-migration is in flight — ADR-0065 §Rollback-
    Strategie carves out schema-migration-rollback as a 2-hour SLA
    surface, which does NOT apply to bridge_audit_writer (anchor-
    writes are content-addressed, no schema-migration semantics).
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_4_time_to_rollback_within_sla(event, MODUL)
