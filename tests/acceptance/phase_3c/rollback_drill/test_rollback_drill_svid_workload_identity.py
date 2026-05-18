# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Rollback-Drill — ``svid_workload_identity``.

Anchors
-------

- ADR-0065 §Rollback-Strategie (Welle-2 = ``svid_workload_identity``,
  read-only-Identity-Lookup, deterministisch).
- ADR-0066 §Rollback (Doppel-Welle-Rollback-Kompatibilität).
- Sister per-welle E2E acceptance file: ``test_welle_2_svid_workload_
  identity_e2e.py``.

Komponente character
--------------------

``svid_workload_identity`` resolves SPIRE-SVID payloads for workload-
identity attestation. Rollback risk profile: low — deterministic
lookup, but SPIRE-agent RPC is the upstream substrate (handled by
SPIRE itself, not by the engine-backend). The ENV-Flag-Switch back
to ``python`` re-routes the SVID-payload-hash computation only;
SPIRE-agent state is invariant under the rollback.

The four RD-1...RD-4 gates verify that the SVID-payload-hash producer
is correctly re-selected after the ENV-rewrite + engine-reboot.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_rd_1_env_flag_switch_effective,
    assert_rd_2_audit_record_documents_rollback,
    assert_rd_3_cross_modul_konsistenz_post_rollback,
    assert_rd_4_time_to_rollback_within_sla,
)

MODUL = "svid_workload_identity"

pytestmark = pytest.mark.phase_3c_rollback_drill


def test_rd_1_env_flag_switch_effective(mocked_rollback_event) -> None:
    """RD-1 — ENV-Flag rust→python switch hat Effekt.

    The ``WAKIR_ENGINE_SVID_WORKLOAD_IDENTITY_BACKEND`` flag flip from
    ``rust`` to ``python`` must move the SVID-payload-hash producer
    binding accordingly. SPIRE-agent itself is untouched (out-of-
    process), so the switch-impact is local to the engine's
    SVID-payload-hash function selection.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_1_env_flag_switch_effective(event, MODUL)


def test_rd_2_audit_record_documents_rollback(mocked_rollback_event) -> None:
    """RD-2 — BackendDecision-Audit-Record dokumentiert Rollback-Event.

    For SVID-workload-identity the audit-record is particularly
    relevant for Henrik-Zone-N: workload-identity-attestation is the
    SPIFFE-SVID-trust-root substrate; any rollback in this
    Komponente must leave a clean audit-trail on the cutover-cycle.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_2_audit_record_documents_rollback(event, MODUL)


def test_rd_3_cross_modul_konsistenz_post_rollback(
    mocked_phase_2_acceptance_gate,
) -> None:
    """RD-3 — Cross-Modul-Konsistenz nach Rollback grün.

    Post-rollback, the Phase-2-Acceptance-Gate re-run must verify that
    the SVID-payload-hash output (post-python-rebind) matches the
    pre-cutover-python-baseline. Deterministic lookup makes this gate
    a strong invariant — a drift here implies a SPIRE-agent state
    issue, *not* an engine-backend issue, and the operator-runbook
    Eskalation pivots to Selin (engine-telemetrie).
    """
    gate = mocked_phase_2_acceptance_gate(MODUL)
    assert_rd_3_cross_modul_konsistenz_post_rollback(gate, MODUL)


def test_rd_4_time_to_rollback_within_sla(mocked_rollback_event) -> None:
    """RD-4 — Time-to-rollback ≤10min SLA.

    SVID-workload-identity's rollback elapsed-time is bound by the
    engine-boot-time + SPIRE-agent-reconnect-time. The 600s SLA
    accommodates both; the mock uses 240s as the typical anchor.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_4_time_to_rollback_within_sla(event, MODUL)
