# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Rollback-Drill — ``v907_verify``.

Anchors
-------

- ADR-0065 §Rollback-Strategie (Welle-1 = ``v907_verify``, lowest
  blast-radius read-only verify pathway).
- ADR-0066 §Rollback (Doppel-Welle-Rollback-Kompatibilität).
- Sister per-welle E2E acceptance file: ``test_welle_1_v907_verify_
  e2e.py`` — same modul, different gate-surface (AC-1...AC-5 vs.
  RD-1...RD-4).

Komponente character
--------------------

``v907_verify`` is the read-only V-907-pin-attest validation pathway.
Rollback risk profile: very low — no state mutation, no NATS, the
ENV-Flag-Switch back to ``python`` simply re-routes the verify-call.
Bridge-Audit-Writer-Re-Verify (ADR-0065 §Rollback-Strategie step 4)
is the cross-check oracle for this read-only Komponente.

This drill verifies the four RD-1...RD-4 SLA-shape gates for the
lowest-risk Komponente as the canonical baseline; deviations across
the other eight drill-files must be motivated against this baseline.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_rd_1_env_flag_switch_effective,
    assert_rd_2_audit_record_documents_rollback,
    assert_rd_3_cross_modul_konsistenz_post_rollback,
    assert_rd_4_time_to_rollback_within_sla,
)

MODUL = "v907_verify"

pytestmark = pytest.mark.phase_3c_rollback_drill


def test_rd_1_env_flag_switch_effective(mocked_rollback_event) -> None:
    """RD-1 — ENV-Flag rust→python switch hat Effekt.

    The Quadlet-ENV-rewrite + engine-reboot must move the modul's
    backend binding from ``rust`` to ``python``. Happy-path: the
    mocked rollback-event reports the post-switch backend as
    ``python``; the assertion verifies pre/post-states and the modul-
    identity. For ``v907_verify`` the switch is read-only-safe — no
    in-flight V-907-pin-attest verification is affected because
    each verify-call is idempotent per ADR-0064 §Risiken.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_1_env_flag_switch_effective(event, MODUL)


def test_rd_2_audit_record_documents_rollback(mocked_rollback_event) -> None:
    """RD-2 — BackendDecision-Audit-Record dokumentiert Rollback-Event.

    On rollback-boot, the engine emits a Backend-Decision-Audit-Record
    with ``target_backend=python``, modul-name correct, operator-actor
    populated, and a non-empty cutover-cycle-id. Mirrors the cutover-
    flip audit-trail (DW-AC-5) but with the inverse target-backend.
    Henrik-Zone-N consumes this audit-record on his audit-sample.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_2_audit_record_documents_rollback(event, MODUL)


def test_rd_3_cross_modul_konsistenz_post_rollback(
    mocked_phase_2_acceptance_gate,
) -> None:
    """RD-3 — Cross-Modul-Konsistenz nach Rollback grün.

    Re-run of the Phase-2-Acceptance-Gate (Tomás Tag-29 substrate,
    ADR-0066 §Mitigation 1) after the rollback completes must return
    green: no cross-modul-schema-drift, no failed sub-gates. For
    ``v907_verify`` the cross-modul touchpoint is the Bridge-Audit-
    Writer-Konsistenz-Report (ADR-0065 §Rollback-Strategie step 4),
    which re-verifies the post-rollback anchor state.
    """
    gate = mocked_phase_2_acceptance_gate(MODUL)
    assert_rd_3_cross_modul_konsistenz_post_rollback(gate, MODUL)


def test_rd_4_time_to_rollback_within_sla(mocked_rollback_event) -> None:
    """RD-4 — Time-to-rollback ≤10min SLA.

    Mocked-clock elapsed-seconds from ``systemctl restart``-start
    through engine-boot-complete must stay ≤``ROLLBACK_SLA_SECONDS``
    (600.0s). For ``v907_verify`` the typical Phase-3a benchmark
    elapsed is ~30s engine-boot-time, well inside the SLA; the mock
    uses 240s as a conservative anchor.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_4_time_to_rollback_within_sla(event, MODUL)
