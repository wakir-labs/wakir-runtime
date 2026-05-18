# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Rollback-Drill — ``anchor_emitter``.

Anchors
-------

- ADR-0065 §Rollback-Strategie (additional Phase-3c-Komponente, not
  in the seven-welle sequence but shares the ENV-Flag-Switch substrate
  ``WAKIR_ENGINE_ANCHOR_EMITTER_BACKEND=rust|python``).
- Phase-3c additional Komponente per the runtime PR-series Tag-18+
  ``feat(persona-engine): rust anchor-emitter`` and bridge-side fan-
  out integration (PR #143 / Tag-18 family).

Komponente character
--------------------

``anchor_emitter`` is the bridge-side anchor-fan-out surface — it
broadcasts WAT-anchors to subscribed clients after the bridge-audit-
writer has hashed and committed them. Rollback risk profile: **low-
mid** — write-path, but every emit is idempotent because anchors are
content-addressed; duplicate-emits are observable but harmless under
client-side deduplication.

This Komponente is part of Phase-3c-Cutover (default Python →
default Rust flip) but does not occupy a numbered welle-slot; it is
included in the rollback-drill suite because the same 10-minute SLA
applies to its ENV-Flag-Switch surface.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_rd_1_env_flag_switch_effective,
    assert_rd_2_audit_record_documents_rollback,
    assert_rd_3_cross_modul_konsistenz_post_rollback,
    assert_rd_4_time_to_rollback_within_sla,
)

MODUL = "anchor_emitter"

pytestmark = pytest.mark.phase_3c_rollback_drill


def test_rd_1_env_flag_switch_effective(mocked_rollback_event) -> None:
    """RD-1 — ENV-Flag rust→python switch hat Effekt.

    The ``WAKIR_ENGINE_ANCHOR_EMITTER_BACKEND`` flag flip moves the
    anchor-fan-out producer from ``rust`` to ``python``. Anchor-payload
    is content-addressed (SHA-256 over JCS-bytes) so the post-rollback
    emits are byte-identical to what the rust-backend produced — RD-1
    asserts the binding change, not the payload content.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_1_env_flag_switch_effective(event, MODUL)


def test_rd_2_audit_record_documents_rollback(mocked_rollback_event) -> None:
    """RD-2 — BackendDecision-Audit-Record dokumentiert Rollback-Event.

    Anchor-emitter rollbacks emit a Backend-Decision-Audit-Record
    naming the modul, targeting ``python``, and tying the rollback to
    a cutover-cycle-id. Because anchor-emitter is the broadcast-side
    of the bridge-audit-writer Komponente-pair, Henrik-Zone-N
    correlates the audit-trail across both Komponenten when both
    are rolled back in close temporal proximity.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_2_audit_record_documents_rollback(event, MODUL)


def test_rd_3_cross_modul_konsistenz_post_rollback(
    mocked_phase_2_acceptance_gate,
) -> None:
    """RD-3 — Cross-Modul-Konsistenz nach Rollback grün.

    Anchor-emitter's downstream consumers (federation_resolver and
    external bridge-subscribers) must continue to see byte-identical
    anchor-emits post-rollback. The Phase-2-Acceptance-Gate re-run
    samples the broadcast-stream and verifies SHA-256 parity against
    the bridge-audit-writer-committed anchor-set.
    """
    gate = mocked_phase_2_acceptance_gate(MODUL)
    assert_rd_3_cross_modul_konsistenz_post_rollback(gate, MODUL)


def test_rd_4_time_to_rollback_within_sla(mocked_rollback_event) -> None:
    """RD-4 — Time-to-rollback ≤10min SLA.

    Anchor-emitter rollback elapsed-time is bounded by engine-boot-
    time + NATS-publish-channel-reconnect-time. Because anchor-emitter
    holds no per-anchor state (the bridge-audit-writer owns commitment;
    anchor-emitter is fan-out only), the rollback is fast — the 240s
    mock anchor is conservative versus typical Phase-3a benchmark.
    """
    event = mocked_rollback_event(MODUL)
    assert_rd_4_time_to_rollback_within_sla(event, MODUL)
