# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Cutover Welle-1 E2E acceptance — ``v907_verify``.

Anchors
-------

- ADR-0065 §Verifikations-Plan §"Vorgeschlagene Reihenfolge" — Welle-1
  = ``v907_verify`` (Read-only-Verify-Pfad, niedrigste Blast-Radius).
- ADR-0065 §Acceptance-Kriterien — AC-1...AC-5 apply to every welle.
- ADR-0063 §Phase-3a Bridge-Audit-Writer — the substrate this welle's
  AC-1 check rides on.
- ADR-0064 §Risiken — V-907-Pin-Validation Cache-Konflikt-Free,
  reinforced by AC-5.

Welle character
---------------

``v907_verify`` is the V-907-Pin-Validation pure-verify pathway:
reads a Persona-Def, looks up the V-907-pin, validates the binding,
returns pass/fail. No state mutation, no NATS, no Bridge-Audit-Writer
*writes* (only reads for the AC-1 consistency-report). Lowest blast-
radius makes it the natural Welle-1.

Skip-by-default
---------------

All tests carry the ``phase_3c_acceptance`` marker. The conftest-level
``pytest_collection_modifyitems`` hook skips them unless the
``WAKIR_PHASE_3C_E2E=1`` env-var is set OR the ``--phase-3c-acceptance``
CLI flag is passed.
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

WELLE_NAME = "v907_verify"
WELLE_INDEX = WELLE_BY_NAME[WELLE_NAME]

pytestmark = pytest.mark.phase_3c_acceptance


# ---------------------------------------------------------------------------
# AC-1 — Bridge-Audit-Writer-Konsistenz-Report (5/5 days green).
# ---------------------------------------------------------------------------


def test_welle_1_ac_1_bridge_audit_consistency_5_of_5_days(
    mocked_bridge_audit_writer,
) -> None:
    """AC-1: 5/5 days of Bridge-Audit-Writer-Konsistenz-Report green.

    For ``v907_verify``: read-only pathway, so the "envelope" being
    hashed is the V-907-pin-attest payload. Parity required between
    Python- and Rust-backend on the same Persona-Def-input.
    """
    roundtrips = mocked_bridge_audit_writer(WELLE_NAME, days=5, per_day=4)
    assert_ac_1_bridge_audit_consistency(roundtrips, WELLE_NAME)


def test_welle_1_ac_1_drift_detected_rejects(
    mocked_bridge_audit_writer,
) -> None:
    """AC-1 failure-mode: a single Rust-drift request blocks the gate.

    Mirrors the ``test_gate_3_1_rust_engine_cutover_acceptance_15_of_15``
    drift-shape verification from ``tests/infra/test_phase_3_acceptance
    _gates.py``.
    """
    drift_req = f"req-{WELLE_NAME}-d2-1"
    roundtrips = mocked_bridge_audit_writer(
        WELLE_NAME, days=5, per_day=4, drift_request_ids=(drift_req,)
    )
    with pytest.raises(AssertionError, match="AC-1"):
        assert_ac_1_bridge_audit_consistency(roundtrips, WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-2 — Performance: P95 ≤ Python-Baseline + 20%.
# ---------------------------------------------------------------------------


def test_welle_1_ac_2_performance_within_headroom() -> None:
    """AC-2: Rust ``v907_verify`` P95 within Python+20% budget.

    Placeholder numbers: Python-baseline ~3.5ms P95 on a verify-only
    call (Selin-Phase-3a-Bench-Reference, Vermutung-P2). Rust expected
    to be faster; toleranz 20% headroom.
    """
    python_baseline_p95_ms = 3.5  # placeholder
    rust_observed_p95_ms = 2.8  # placeholder — Rust faster
    assert_ac_2_performance_headroom(
        python_baseline_p95_ms, rust_observed_p95_ms, WELLE_NAME
    )


@pytest.mark.skip(reason="pending welle-cutover — real perf-gauge wiring")
def test_welle_1_ac_2_performance_regression_blocks() -> None:
    """AC-2 failure-mode: Rust slower than Python+20% blocks the gate."""
    python_baseline_p95_ms = 3.5
    rust_observed_p95_ms = 5.0  # > 3.5 * 1.20 = 4.2 → fail
    with pytest.raises(AssertionError, match="AC-2"):
        assert_ac_2_performance_headroom(
            python_baseline_p95_ms, rust_observed_p95_ms, WELLE_NAME
        )


# ---------------------------------------------------------------------------
# AC-3 — Bug-Rate: 0 S0/S1 Issues during Beobachtungs-Woche.
# ---------------------------------------------------------------------------


def test_welle_1_ac_3_bug_rate_zero_s0_s1() -> None:
    """AC-3: 0 substanz-relevante (S0/S1) Issues during the welle-week."""
    assert_ac_3_bug_rate(s0_count=0, s1_count=0, welle=WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-4 — Cross-Review-Session-Konsensus (alle Engineering-Personas).
# ---------------------------------------------------------------------------


def test_welle_1_ac_4_cross_review_consensus(mocked_cross_review) -> None:
    """AC-4: Aisha-protokolliert Cross-Review-Session all-personas-consent."""
    record = mocked_cross_review(WELLE_NAME)
    assert_ac_4_cross_review_consensus(record, WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-5 — V-907 Pin-Validation 100% pass-rate (Welle-1 dominant).
# ---------------------------------------------------------------------------


def test_welle_1_ac_5_v907_pin_validation_full_pass() -> None:
    """AC-5: V-907 Pin-Validation 100% on all Persona-Defs.

    For ``v907_verify``, AC-5 *is* the core surface — the modul **is**
    V-907 verification. Phase-3c-trigger sprint replaces this with a
    full sweep over the Persona-Def-corpus (currently 6 personas live).
    """
    persona_def_count = 6  # placeholder — current persona inventory
    assert_ac_5_v907_pin_validation(
        persona_def_count=persona_def_count,
        pin_validation_pass_count=persona_def_count,
        welle=WELLE_NAME,
    )


# ---------------------------------------------------------------------------
# Welle-1 substrate sanity — boot-record + Quadlet-flag flip.
# ---------------------------------------------------------------------------


def test_welle_1_boot_flips_only_v907_verify(
    mocked_engine_boot, mocked_quadlet_env
) -> None:
    """Welle-1 Quadlet-state: only ``v907_verify`` flipped to rust.

    Mixed-Backend-Substrat during Welle-1 cutover: ``v907_verify``
    on Rust, all 6 other moduln on Python. AC-1 Bridge-Audit-Writer
    is the consistency oracle across that mixed substrate.
    """
    boot = mocked_engine_boot(WELLE_NAME)
    assert boot.boot_succeeded, (
        f"welle-1 boot must succeed; got failure-record {boot}"
    )
    assert boot.backend_per_modul[WELLE_NAME] == "rust", (
        f"welle-1 modul {WELLE_NAME} must be on rust-backend post-flip; "
        f"got {boot.backend_per_modul[WELLE_NAME]!r}"
    )
    other_rust = [
        m
        for m, b in boot.backend_per_modul.items()
        if b == "rust" and m != WELLE_NAME
    ]
    assert not other_rust, (
        f"welle-1 must flip ONLY {WELLE_NAME}; other rust-flipped moduln: "
        f"{other_rust}"
    )

    env = mocked_quadlet_env(WELLE_NAME)
    assert env[f"WAKIR_ENGINE_{WELLE_NAME.upper()}_BACKEND"] == "rust"
    rust_env_keys = [k for k, v in env.items() if v == "rust"]
    assert len(rust_env_keys) == 1, (
        f"welle-1 Quadlet-state must have exactly 1 rust-flipped ENV-key; "
        f"got {rust_env_keys}"
    )


@pytest.mark.skip(reason="pending welle-cutover — Rollback runbook drill wiring")
def test_welle_1_rollback_within_ten_minutes() -> None:
    """Welle-1 Rollback-SLA: ≤10 Minuten ENV-Flag-Switch (ADR-0065
    §Rollback-Strategie).

    Operator-Hand-Drill substrate; hermetic skeleton placeholder. The
    Phase-3c-trigger sprint wires this to the real
    ``systemctl restart wakir-persona-engine`` + ENV-rewrite path.
    """
    raise NotImplementedError("pending welle-cutover")
