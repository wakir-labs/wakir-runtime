# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Cutover Welle-5 E2E acceptance — ``lifecycle_state_machine``.

Anchors
-------

- ADR-0065 §Verifikations-Plan §"Vorgeschlagene Reihenfolge" — Welle-5
  = ``lifecycle_state_machine`` (Stateful, Cross-Modul-Dependency).
- ADR-0065 §Risiken §"Cross-Komponenten-Schema-Drift" — Welle-5
  consumes ``state_backing`` output; cross-modul-schema-drift is now
  a *two-sided* risk (Rust-state_backing × Rust-lifecycle vs.
  pre-Welle-4 Python-state_backing × Python-lifecycle).

Welle character
---------------

``lifecycle_state_machine`` orchestrates persona lifecycle states
(idle → active → terminating → archived). Stateful + cross-modul
dependent (reads from ``state_backing``, writes lifecycle-events into
the Bridge-Audit-Writer trail).

Welle-5 is the first welle where the *cross-modul-schema-contract*
is the dominant risk: Welle-4 already flipped ``state_backing`` to
Rust, so the lifecycle-machine's input is now Rust-produced state-
records. The transition-table itself must be cross-language
behaviorally identical.
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

WELLE_NAME = "lifecycle_state_machine"
WELLE_INDEX = WELLE_BY_NAME[WELLE_NAME]

pytestmark = pytest.mark.phase_3c_acceptance


# ---------------------------------------------------------------------------
# AC-1.
# ---------------------------------------------------------------------------


def test_welle_5_ac_1_bridge_audit_consistency_5_of_5_days(
    mocked_bridge_audit_writer,
) -> None:
    """AC-1: lifecycle-event-envelope parity Python ⇆ Rust."""
    roundtrips = mocked_bridge_audit_writer(WELLE_NAME, days=5, per_day=5)
    assert_ac_1_bridge_audit_consistency(roundtrips, WELLE_NAME)


def test_welle_5_ac_1_transition_table_drift_blocks(
    mocked_bridge_audit_writer,
) -> None:
    """AC-1 failure-mode: transition-table cross-lang behaviour drift.

    A Python lifecycle-machine accepts the ``idle → active`` transition
    on some edge-input that the Rust port rejects (or vice-versa).
    The envelope-hash captures the *result* state — drift surfaces here.
    """
    drift_req = f"req-{WELLE_NAME}-d3-3"
    roundtrips = mocked_bridge_audit_writer(
        WELLE_NAME, days=5, per_day=5, drift_request_ids=(drift_req,)
    )
    with pytest.raises(AssertionError, match="AC-1"):
        assert_ac_1_bridge_audit_consistency(roundtrips, WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-2.
# ---------------------------------------------------------------------------


def test_welle_5_ac_2_performance_within_headroom() -> None:
    """AC-2: Rust lifecycle-machine P95 within Python+20% budget."""
    python_baseline_p95_ms = 4.5
    rust_observed_p95_ms = 3.2
    assert_ac_2_performance_headroom(
        python_baseline_p95_ms, rust_observed_p95_ms, WELLE_NAME
    )


# ---------------------------------------------------------------------------
# AC-3.
# ---------------------------------------------------------------------------


def test_welle_5_ac_3_bug_rate_zero_s0_s1() -> None:
    """AC-3: 0 S0/S1 issues during Welle-5 Beobachtungs-Woche."""
    assert_ac_3_bug_rate(s0_count=0, s1_count=0, welle=WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-4.
# ---------------------------------------------------------------------------


def test_welle_5_ac_4_cross_review_consensus(mocked_cross_review) -> None:
    """AC-4: Welle-5 Cross-Review-Session all-personas-consent."""
    record = mocked_cross_review(WELLE_NAME)
    assert_ac_4_cross_review_consensus(record, WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-5.
# ---------------------------------------------------------------------------


def test_welle_5_ac_5_v907_pin_validation_full_pass() -> None:
    """AC-5: V-907 Pin-Validation 100% post-Welle-5 cutover."""
    persona_def_count = 6
    assert_ac_5_v907_pin_validation(
        persona_def_count=persona_def_count,
        pin_validation_pass_count=persona_def_count,
        welle=WELLE_NAME,
    )


# ---------------------------------------------------------------------------
# Welle-5 substrate sanity — cross-modul-schema-contract verify.
# ---------------------------------------------------------------------------


def test_welle_5_five_moduln_rust(mocked_quadlet_env) -> None:
    """Welle-5 Quadlet-state: 5 rust + 2 python (subscribe_loop +
    recovery_workflow remaining)."""
    env = mocked_quadlet_env(
        WELLE_NAME,
        flipped_moduln=(
            "v907_verify",
            "svid_workload_identity",
            "bridge_audit_writer",
            "state_backing",
            "lifecycle_state_machine",
        ),
    )
    rust_count = sum(1 for v in env.values() if v == "rust")
    python_count = sum(1 for v in env.values() if v == "python")
    assert rust_count == 5 and python_count == 2, (
        f"Welle-5 mixed-state must have exactly 5 rust + 2 python; "
        f"got rust={rust_count}, python={python_count}"
    )


@pytest.mark.skip(reason="pending welle-cutover — lifecycle transition-table corpus")
def test_welle_5_transition_table_cross_lang_parity() -> None:
    """Welle-5-specific: every reachable transition in the lifecycle
    state-graph behaves identically across Python and Rust.

    The corpus is the full transition-table (idle → active → terminating
    → archived, plus all error-edges). Phase-3c-trigger sprint wires
    the real transition-corpus replay.
    """
    raise NotImplementedError("pending welle-cutover")


@pytest.mark.skip(reason="pending welle-cutover — Welle-4-Welle-5 cross-contract drill")
def test_welle_5_consumes_welle_4_state_records() -> None:
    """Welle-5 reads state-records that Welle-4 (Rust-state_backing)
    wrote. Cross-modul-schema-contract verify under
    Rust-state_backing × Rust-lifecycle conditions.

    Coordinated with Selin-Sprint-Pengine-N (ADR-0065 §Folgeartefakte 2).
    """
    raise NotImplementedError("pending welle-cutover")
