# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Cutover Welle-6 E2E acceptance — ``subscribe_loop``.

Anchors
-------

- ADR-0065 §Verifikations-Plan §"Vorgeschlagene Reihenfolge" — Welle-6
  = ``subscribe_loop`` (NATS-Subscribe, Bug-42-Lessons-Learned hot).
- Bug-42-Lessons-Learned anchor: ``wirelang/tests/persona_engine/
  test_subscribe_mode_bug42.py`` (test-coverage substrate from earlier
  Mini-Welle).

Welle character
---------------

``subscribe_loop`` is the NATS-subscribe-loop that drives reactive
persona-engine workflows. Stateful (holds NATS-connection-state +
subscription-cursor), live-network-dependent in production, and the
locus of Bug-42 (the subscribe-mode-misrouting bug that Selin-
Sprint-Pengine-N earlier closed).

The cutover risk is **subscription-cursor-state drift**: Python and
Rust must agree on the cursor-advance protocol byte-for-byte
(otherwise post-rollback the Python-backend would reprocess messages
the Rust-backend already acknowledged). Bug-42-Lessons-Learned hot
means the failure-mode coverage is rich.
"""

from __future__ import annotations

import pytest

from ._ac_assertions import (
    assert_ac_1_bridge_audit_consistency,
    assert_ac_2_performance_headroom,
    assert_ac_3_bug_rate,
    assert_ac_4_cross_review_consensus,
    assert_ac_5_v907_pin_validation,
)
from .conftest import WELLE_BY_NAME

WELLE_NAME = "subscribe_loop"
WELLE_INDEX = WELLE_BY_NAME[WELLE_NAME]

pytestmark = pytest.mark.phase_3c_acceptance


# ---------------------------------------------------------------------------
# AC-1.
# ---------------------------------------------------------------------------


def test_welle_6_ac_1_bridge_audit_consistency_5_of_5_days(
    mocked_bridge_audit_writer,
) -> None:
    """AC-1: subscribe-event-envelope parity Python ⇆ Rust on 5 days."""
    roundtrips = mocked_bridge_audit_writer(WELLE_NAME, days=5, per_day=6)
    assert_ac_1_bridge_audit_consistency(roundtrips, WELLE_NAME)


def test_welle_6_ac_1_cursor_drift_blocks(
    mocked_bridge_audit_writer,
) -> None:
    """AC-1 failure-mode: subscription-cursor-state drift.

    The Bug-42-class failure (subscribe-mode-misrouting) re-surfaces if
    Python and Rust disagree on cursor-advance. The mock encodes that
    drift as a payload-hash divergence on the affected message-id.
    """
    drift_req = f"req-{WELLE_NAME}-d4-5"  # last message in window
    roundtrips = mocked_bridge_audit_writer(
        WELLE_NAME, days=5, per_day=6, drift_request_ids=(drift_req,)
    )
    with pytest.raises(AssertionError, match="AC-1"):
        assert_ac_1_bridge_audit_consistency(roundtrips, WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-2.
# ---------------------------------------------------------------------------


def test_welle_6_ac_2_performance_within_headroom() -> None:
    """AC-2: Rust subscribe-loop P95 within Python+20% budget.

    Subscribe-throughput is the metric here (events/s); P95-latency is
    per-event-handling-time. Python-baseline placeholder ~6ms p95.
    """
    python_baseline_p95_ms = 6.0
    rust_observed_p95_ms = 4.0
    assert_ac_2_performance_headroom(
        python_baseline_p95_ms, rust_observed_p95_ms, WELLE_NAME
    )


# ---------------------------------------------------------------------------
# AC-3.
# ---------------------------------------------------------------------------


def test_welle_6_ac_3_bug_rate_zero_s0_s1() -> None:
    """AC-3: 0 S0/S1 issues during Welle-6 Beobachtungs-Woche.

    Welle-6 has elevated S0/S1 risk per Bug-42-Lessons-Learned — the
    bar stays at 0, but Operator-Hand Beobachtungs-Disziplin must be
    tighter here than in earlier wellen.
    """
    assert_ac_3_bug_rate(s0_count=0, s1_count=0, welle=WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-4.
# ---------------------------------------------------------------------------


def test_welle_6_ac_4_cross_review_consensus(mocked_cross_review) -> None:
    """AC-4: Welle-6 Cross-Review-Session all-personas-consent."""
    record = mocked_cross_review(WELLE_NAME)
    assert_ac_4_cross_review_consensus(record, WELLE_NAME)


def test_welle_6_ac_4_selin_consent_required(mocked_cross_review) -> None:
    """AC-4 specific: Selin (Persona-Engine-Owner + Bug-42-closer)
    consent is non-negotiable for Welle-6.
    """
    record = mocked_cross_review(WELLE_NAME, withheld_personas=("selin",))
    with pytest.raises(AssertionError, match="AC-4"):
        assert_ac_4_cross_review_consensus(record, WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-5.
# ---------------------------------------------------------------------------


def test_welle_6_ac_5_v907_pin_validation_full_pass() -> None:
    """AC-5: V-907 Pin-Validation 100% post-Welle-6 cutover."""
    persona_def_count = 6
    assert_ac_5_v907_pin_validation(
        persona_def_count=persona_def_count,
        pin_validation_pass_count=persona_def_count,
        welle=WELLE_NAME,
    )


# ---------------------------------------------------------------------------
# Welle-6 substrate sanity — six-of-seven moduln on rust.
# ---------------------------------------------------------------------------


def test_welle_6_six_moduln_rust(mocked_quadlet_env) -> None:
    """Welle-6 Quadlet-state: 6 rust + 1 python (only recovery_workflow
    remains on python)."""
    env = mocked_quadlet_env(
        WELLE_NAME,
        flipped_moduln=(
            "v907_verify",
            "svid_workload_identity",
            "bridge_audit_writer",
            "state_backing",
            "lifecycle_state_machine",
            "subscribe_loop",
        ),
    )
    rust_count = sum(1 for v in env.values() if v == "rust")
    python_count = sum(1 for v in env.values() if v == "python")
    assert rust_count == 6 and python_count == 1, (
        f"Welle-6 mixed-state must have exactly 6 rust + 1 python; "
        f"got rust={rust_count}, python={python_count}"
    )
    assert env["WAKIR_ENGINE_RECOVERY_WORKFLOW_BACKEND"] == "python", (
        "Welle-6 must leave recovery_workflow on python (Welle-7 only)"
    )


@pytest.mark.skip(reason="pending welle-cutover — Bug-42-regression-replay corpus")
def test_welle_6_bug_42_regression_replay_clean() -> None:
    """Welle-6-specific: Bug-42-regression-replay corpus runs clean on
    Rust-backend.

    The Bug-42-Lessons-Learned corpus from
    ``wirelang/tests/persona_engine/test_subscribe_mode_bug42.py`` is
    the hot-path failure-mode pin. Phase-3c-trigger sprint wires the
    full replay against the Rust-subscribe-loop.
    """
    raise NotImplementedError("pending welle-cutover")
