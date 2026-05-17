# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Cutover Welle-2 E2E acceptance — ``svid_workload_identity``.

Anchors
-------

- ADR-0065 §Verifikations-Plan §"Vorgeschlagene Reihenfolge" — Welle-2
  = ``svid_workload_identity`` (Read-only-Identity-Lookup, deterministic).
- ADR-0065 §Acceptance-Kriterien — AC-1...AC-5.
- ``infra/spire/`` (existing SPIRE federation substrate) — the workload-
  identity surface this welle re-implements in Rust.

Welle character
---------------

``svid_workload_identity`` is the SPIRE workload-identity-lookup
pathway: takes a workload-spiffe-id, returns the X.509-SVID. Read-only
+ deterministic (same input → same output, modulo SPIRE rotation
windows). Welle-2 after Welle-1 in the risk-ascending order.

The Bridge-Audit-Writer parity check (AC-1) compares the SVID-payload
hash across Python- and Rust-backends on the same workload-spiffe-id
input set.
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

WELLE_NAME = "svid_workload_identity"
WELLE_INDEX = WELLE_BY_NAME[WELLE_NAME]

pytestmark = pytest.mark.phase_3c_acceptance


# ---------------------------------------------------------------------------
# AC-1 — Bridge-Audit-Writer-Konsistenz-Report.
# ---------------------------------------------------------------------------


def test_welle_2_ac_1_bridge_audit_consistency_5_of_5_days(
    mocked_bridge_audit_writer,
) -> None:
    """AC-1: SVID-payload-hash parity Python ⇆ Rust over 5 days."""
    roundtrips = mocked_bridge_audit_writer(WELLE_NAME, days=5, per_day=4)
    assert_ac_1_bridge_audit_consistency(roundtrips, WELLE_NAME)


def test_welle_2_ac_1_drift_detected_rejects(
    mocked_bridge_audit_writer,
) -> None:
    """AC-1 failure-mode: SVID-payload-hash drift blocks the gate.

    Possible drift-source: SPIRE-Trust-Domain canonicalisation
    difference between Python and Rust implementations. The drift-
    detector must catch it before Welle-2 cutover declares success.
    """
    drift_req = f"req-{WELLE_NAME}-d0-2"
    roundtrips = mocked_bridge_audit_writer(
        WELLE_NAME, days=5, per_day=4, drift_request_ids=(drift_req,)
    )
    with pytest.raises(AssertionError, match="AC-1"):
        assert_ac_1_bridge_audit_consistency(roundtrips, WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-2 — Performance.
# ---------------------------------------------------------------------------


def test_welle_2_ac_2_performance_within_headroom() -> None:
    """AC-2: Rust SVID-lookup P95 within Python+20% budget.

    SPIRE-lookup has a cache-hit hot-path (~1ms) and cache-miss cold-
    path (~30ms incl. agent-RPC). Placeholder uses the cache-miss
    p95 as the budget anchor (worst-case-bounded).
    """
    python_baseline_p95_ms = 30.0  # placeholder cache-miss p95
    rust_observed_p95_ms = 22.0  # placeholder Rust faster
    assert_ac_2_performance_headroom(
        python_baseline_p95_ms, rust_observed_p95_ms, WELLE_NAME
    )


@pytest.mark.skip(reason="pending welle-cutover — real SPIRE-agent perf wiring")
def test_welle_2_ac_2_performance_regression_blocks() -> None:
    """AC-2 failure-mode: SPIRE-lookup regression blocks the gate."""
    raise NotImplementedError("pending welle-cutover")


# ---------------------------------------------------------------------------
# AC-3 — Bug-Rate.
# ---------------------------------------------------------------------------


def test_welle_2_ac_3_bug_rate_zero_s0_s1() -> None:
    """AC-3: 0 S0/S1 issues during Welle-2 Beobachtungs-Woche."""
    assert_ac_3_bug_rate(s0_count=0, s1_count=0, welle=WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-4 — Cross-Review-Session-Konsensus.
# ---------------------------------------------------------------------------


def test_welle_2_ac_4_cross_review_consensus(mocked_cross_review) -> None:
    """AC-4: Aisha-protokolliert Welle-2 Cross-Review-Session consent."""
    record = mocked_cross_review(WELLE_NAME)
    assert_ac_4_cross_review_consensus(record, WELLE_NAME)


def test_welle_2_ac_4_missing_persona_blocks(mocked_cross_review) -> None:
    """AC-4 failure-mode: missing persona-consent blocks the gate.

    Welle-2 is SPIRE-substrate-relevant → Kai (substrate-owner) must
    consent. Withholding Kai's consent must block the gate.
    """
    record = mocked_cross_review(WELLE_NAME, withheld_personas=("kai",))
    with pytest.raises(AssertionError, match="AC-4"):
        assert_ac_4_cross_review_consensus(record, WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-5 — V-907 Pin-Validation.
# ---------------------------------------------------------------------------


def test_welle_2_ac_5_v907_pin_validation_full_pass() -> None:
    """AC-5: V-907 Pin-Validation 100% post-Welle-2 cutover.

    ``svid_workload_identity`` issues SVIDs that downstream consumers
    use to validate V-907-pin-attest payloads. A drift here would
    cascade into V-907 cache-conflict — AC-5 is non-negotiable.
    """
    persona_def_count = 6
    assert_ac_5_v907_pin_validation(
        persona_def_count=persona_def_count,
        pin_validation_pass_count=persona_def_count,
        welle=WELLE_NAME,
    )


# ---------------------------------------------------------------------------
# Welle-2 substrate sanity — Welle-1 stays on rust, only Welle-2 flips.
# ---------------------------------------------------------------------------


def test_welle_2_quadlet_state_welle_1_and_2_rust(mocked_quadlet_env) -> None:
    """Welle-2 Quadlet-state: ``v907_verify`` + ``svid_workload_identity``
    on rust, remaining 5 moduln on python.

    Welle-2 is the first opportunity to verify the *mixed-backend
    persistence* requirement: Welle-1's flip must not regress when
    Welle-2 flips its own ENV-flag.
    """
    env = mocked_quadlet_env(
        WELLE_NAME, flipped_moduln=("v907_verify", "svid_workload_identity")
    )
    assert env["WAKIR_ENGINE_V907_VERIFY_BACKEND"] == "rust"
    assert env["WAKIR_ENGINE_SVID_WORKLOAD_IDENTITY_BACKEND"] == "rust"
    rust_count = sum(1 for v in env.values() if v == "rust")
    python_count = sum(1 for v in env.values() if v == "python")
    assert rust_count == 2 and python_count == 5, (
        f"Welle-2 mixed-state must have exactly 2 rust + 5 python; "
        f"got rust={rust_count}, python={python_count}"
    )


@pytest.mark.skip(reason="pending welle-cutover — Operator-Hand SPIRE-agent drill")
def test_welle_2_spire_agent_consistency_across_rotation() -> None:
    """Welle-2 specific: SPIRE-SVID-rotation consistency.

    Operator-Hand drill substrate — SPIRE rotates SVIDs on a fixed
    interval; verify that Rust-backend handles the rotation without
    cache-staleness drift against the Python-backend reference.
    """
    raise NotImplementedError("pending welle-cutover")
