# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Rollback-Drill — ``federation_resolver``.

Anchors
-------

- ADR-0065 §Rollback-Strategie (additional Phase-3c-Komponente, not
  in the seven-welle sequence but shares the ENV-Flag-Switch substrate
  ``WAKIR_ENGINE_FEDERATION_RESOLVER_BACKEND=rust|python``).
- Phase-3c additional Komponente per the runtime PR-series Tag-14+
  ``feat(federation): cross-org name resolution``.

Komponente character
--------------------

``federation_resolver`` is the cross-org persona-name-resolution
surface — given a fully-qualified persona-name (``<org>/<persona>``),
it resolves to a workload-identity-attestation root. Rollback risk
profile: **low-mid** — read-only cache-backed lookup, but the cache-
invalidation contract is shared between the rust- and python-
backends, so the post-rollback cache state must be consistent.

This Komponente is part of Phase-3c-Cutover (default Python →
default Rust flip) but does not occupy a numbered welle-slot; the
rollback-drill includes it because the same 10-minute SLA applies
to its ENV-Flag-Switch surface.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_rd_1_env_flag_switch_effective,
    assert_rd_2_audit_record_documents_rollback,
    assert_rd_3_cross_modul_konsistenz_post_rollback,
    assert_rd_4_time_to_rollback_within_sla,
)

MODUL = "federation_resolver"

pytestmark = pytest.mark.phase_3c_rollback_drill


def test_rd_1_env_flag_switch_effective(mocked_rollback_event) -> None:
    """RD-1 — ENV-Flag rust→python switch hat Effekt.

    The ``WAKIR_ENGINE_FEDERATION_RESOLVER_BACKEND`` flag flip from
    ``rust`` to ``python`` re-binds the cross-org-name resolver. The
    resolver cache is engine-process-local so the post-switch cache
    starts empty; cold-cache resolution times during the immediate
    post-rollback window are an expected operational signal, not a
    drill-failure.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_1_env_flag_switch_effective(event, MODUL)


def test_rd_2_audit_record_documents_rollback(mocked_rollback_event) -> None:
    """RD-2 — BackendDecision-Audit-Record dokumentiert Rollback-Event.

    Federation-resolver rollback emits a Backend-Decision-Audit-Record
    naming the modul, targeting ``python``, and tying the rollback to
    a cutover-cycle-id. Henrik-Zone-N correlates this against the
    cross-org-trust-anchor sample because federation_resolver decisions
    feed into the workload-identity-attestation chain.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_2_audit_record_documents_rollback(event, MODUL)


def test_rd_3_cross_modul_konsistenz_post_rollback(
    mocked_phase_2_acceptance_gate,
) -> None:
    """RD-3 — Cross-Modul-Konsistenz nach Rollback grün.

    The critical post-rollback verification is name-resolution-
    determinism: the same fully-qualified persona-name must resolve to
    the same workload-identity-attestation root under both backends.
    The Phase-2-Acceptance-Gate re-run samples a name-set across the
    resolver and verifies byte-parity of the resolution-output.
    """
    gate = mocked_phase_2_acceptance_gate(MODUL)
    assert_rd_3_cross_modul_konsistenz_post_rollback(gate, MODUL)


def test_rd_4_time_to_rollback_within_sla(mocked_rollback_event) -> None:
    """RD-4 — Time-to-rollback ≤10min SLA.

    Federation-resolver rollback elapsed-time is bounded by engine-
    boot-time + cache-cold-start window. Because cache-warm-up is
    incremental (per-resolution, not bulk), engine-boot-complete is
    the SLA-relevant milestone — well inside the 600s budget under
    typical load. The 240s mock anchor is conservative.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_4_time_to_rollback_within_sla(event, MODUL)
