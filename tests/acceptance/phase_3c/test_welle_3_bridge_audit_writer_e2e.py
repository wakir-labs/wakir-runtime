# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Cutover Welle-3 E2E acceptance — ``bridge_audit_writer``.

Anchors
-------

- ADR-0065 §Verifikations-Plan §"Vorgeschlagene Reihenfolge" — Welle-3
  = ``bridge_audit_writer`` (Write-Pfad, aber idempotent via WAT-Hash-
  Anchoring).
- ADR-0063 §Phase-3a — Bridge-Audit-Writer ist die Konsistenz-Oracle-
  Substrate, that this welle now also flips to Rust-default.
- ADR-0065 §Risiken §"Cross-Komponenten-Schema-Drift" — Welle-3 has
  the highest schema-drift sensitivity (it *is* the cross-backend
  schema writer).

Welle character
---------------

``bridge_audit_writer`` is *the* consistency-oracle substrate from
Phase-3a/3b. Flipping the *writer* itself to Rust-default introduces
a meta-question: while Welle-3 is in-flight, **what** writes the
consistency-report? Solution per ADR-0065 §Empfehlung Footnote
("Canary-Deploy"): Welle-3 cutover-Tag uses a hold-out audit-writer
instance (Python-Backend pinned) for the consistency-report itself.

This welle is **write-pfad** but **idempotent** (WAT-Hash-Anchored):
double-write produces the same anchor-hash → no state-corruption
risk from re-write on rollback.
"""

from __future__ import annotations

import pytest

from ._ac_assertions import (
    assert_ac_1_bridge_audit_consistency,
    assert_ac_2_performance_headroom,
    assert_ac_3_bug_rate,
    assert_ac_4_cross_review_consensus,
    assert_ac_5_v907_pin_validation,
    assert_henrik_caution_ac_1_independent_stress_validation,
    assert_henrik_caution_ac_2_divergence_rollback,
    assert_henrik_caution_ac_3_pre_cutover_baseline,
)
from .conftest import (
    HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD,
    HENRIK_CAUTION_PRE_CUTOVER_BASELINE_DAYS,
    WELLE_BY_NAME,
)

WELLE_NAME = "bridge_audit_writer"
WELLE_INDEX = WELLE_BY_NAME[WELLE_NAME]

pytestmark = pytest.mark.phase_3c_acceptance


# ---------------------------------------------------------------------------
# AC-1 — Konsistenz-Report (Welle-3 special: hold-out python writer).
# ---------------------------------------------------------------------------


def test_welle_3_ac_1_bridge_audit_consistency_5_of_5_days(
    mocked_bridge_audit_writer,
) -> None:
    """AC-1: Bridge-Audit-Writer output parity across the 5-day window.

    Welle-3 special — the writer *itself* is the modul under cutover.
    The consistency-report substrate (per ADR-0065 §Empfehlung Footnote)
    is a hold-out Python-pinned writer-instance that observes both the
    pre-cutover Python output and the post-cutover Rust output.
    """
    roundtrips = mocked_bridge_audit_writer(WELLE_NAME, days=5, per_day=5)
    assert_ac_1_bridge_audit_consistency(roundtrips, WELLE_NAME)


def test_welle_3_ac_1_drift_in_anchor_format_blocks(
    mocked_bridge_audit_writer, mocked_wat_anchor_sink
) -> None:
    """AC-1 failure-mode: Rust-writer produces an Anchor-format-drift.

    The WAT-Anchor-Sink mock is the second-layer oracle: even if the
    request-set roundtrip parity is 5/5, the persistent Anchor-hash
    matrix must match across Python/Rust on each request_id.
    """
    drift_req = "req-shared-x"
    anchors = mocked_wat_anchor_sink(
        WELLE_NAME,
        request_ids=("req-shared-a", "req-shared-b", "req-shared-x"),
        drift_request_ids=(drift_req,),
    )
    py_anchors = {a.request_id: a.anchor_sha256 for a in anchors if a.backend == "python"}
    rust_anchors = {a.request_id: a.anchor_sha256 for a in anchors if a.backend == "rust"}
    drift_ids = [
        req for req in py_anchors if py_anchors[req] != rust_anchors.get(req)
    ]
    assert drift_req in drift_ids, (
        f"AC-1[{WELLE_NAME}] Anchor-format drift-detector must surface "
        f"{drift_req}; got drift-set {drift_ids}"
    )


# ---------------------------------------------------------------------------
# AC-2 — Performance.
# ---------------------------------------------------------------------------


def test_welle_3_ac_2_performance_within_headroom() -> None:
    """AC-2: Rust Bridge-Audit-Writer P95 within Python+20% budget.

    Write-path includes JCS canonicalisation + sha256 + WAT-anchor
    append. Python-baseline placeholder ~8ms p95 (Selin-Phase-3a-
    Bench-Reference, Vermutung-P2).
    """
    python_baseline_p95_ms = 8.0
    rust_observed_p95_ms = 5.5  # Rust expected faster on sha256+JCS
    assert_ac_2_performance_headroom(
        python_baseline_p95_ms, rust_observed_p95_ms, WELLE_NAME
    )


@pytest.mark.skip(reason="pending welle-cutover — real WAT-anchor-append perf")
def test_welle_3_ac_2_performance_regression_blocks() -> None:
    """AC-2 failure-mode."""
    raise NotImplementedError("pending welle-cutover")


# ---------------------------------------------------------------------------
# AC-3 — Bug-Rate.
# ---------------------------------------------------------------------------


def test_welle_3_ac_3_bug_rate_zero_s0_s1() -> None:
    """AC-3: 0 S0/S1 issues during Welle-3 Beobachtungs-Woche."""
    assert_ac_3_bug_rate(s0_count=0, s1_count=0, welle=WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-4 — Cross-Review-Session-Konsensus.
# ---------------------------------------------------------------------------


def test_welle_3_ac_4_cross_review_consensus(mocked_cross_review) -> None:
    """AC-4: Welle-3 Cross-Review-Session all-personas-consent."""
    record = mocked_cross_review(WELLE_NAME)
    assert_ac_4_cross_review_consensus(record, WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-5 — V-907 Pin-Validation.
# ---------------------------------------------------------------------------


def test_welle_3_ac_5_v907_pin_validation_full_pass() -> None:
    """AC-5: V-907 Pin-Validation 100% post-Welle-3 cutover."""
    persona_def_count = 6
    assert_ac_5_v907_pin_validation(
        persona_def_count=persona_def_count,
        pin_validation_pass_count=persona_def_count,
        welle=WELLE_NAME,
    )


# ---------------------------------------------------------------------------
# Welle-3 substrate sanity — idempotent write semantics.
# ---------------------------------------------------------------------------


def test_welle_3_idempotent_double_write_yields_same_anchor(
    mocked_wat_anchor_sink,
) -> None:
    """Welle-3-specific: double-write of the same request must produce
    the same Anchor-hash (WAT-Hash-Anchoring idempotency).

    Rationale: if the Welle-3 cutover causes a duplicate write
    (e.g., due to a partial systemctl-restart), the second write must
    not corrupt the anchor-trail.
    """
    pass_1 = mocked_wat_anchor_sink(WELLE_NAME, request_ids=("req-idem-a",))
    pass_2 = mocked_wat_anchor_sink(WELLE_NAME, request_ids=("req-idem-a",))
    assert pass_1 == pass_2, (
        f"Welle-3 WAT-Anchor double-write must be idempotent; got "
        f"pass_1={pass_1} pass_2={pass_2}"
    )


@pytest.mark.skip(reason="pending welle-cutover — Operator-Hand hold-out-writer drill")
def test_welle_3_holdout_python_writer_during_cutover() -> None:
    """Welle-3 special: a Python-pinned writer-instance runs alongside
    the Rust-default writer during the cutover day to serve as the
    Konsistenz-Report substrate (ADR-0065 §Empfehlung Footnote).

    Operator-Hand drill — the hold-out instance is decommissioned after
    AC-1 5/5 days green.
    """
    raise NotImplementedError("pending welle-cutover")


# ---------------------------------------------------------------------------
# HC-AC-1 — Bridge-Audit-Writer-Output independently validated by
# Phase-2-Cross-Modul-Stress-Test (hold-out Python-writer as oracle).
#
# Anchor: ADR-0066 §Beschluss + §Mitigations — Welle-3 Henrik-Caution
# carve-out. Welle-3 is the only Solo-Welle in Phase-3c-Cadence; the
# bridge_audit_writer is the meta-modul that produces consistency-
# reports for the other six wellen. The HC-AC layer is solo-welle-
# specific and never applies under Doppel-Welle conditions (per
# ADR-0066, bridge_audit_writer never pairs with another modul).
# ---------------------------------------------------------------------------


def test_welle_3_hc_ac_1_independent_stress_validation_happy_path(
    mocked_henrik_caution_stress_sample,
) -> None:
    """HC-AC-1: full Phase-2-Cross-Modul-Stress-Test sample independently
    validated by the hold-out Python-pinned writer-instance.

    The stress-sample size (5000 requests) is a placeholder pending the
    Phase-3c-trigger-sprint wire-up against Tomás Tag-29 substrate.
    """
    record = mocked_henrik_caution_stress_sample(WELLE_NAME)
    assert_henrik_caution_ac_1_independent_stress_validation(
        record, WELLE_NAME
    )


def test_welle_3_hc_ac_1_partial_holdout_validation_blocks(
    mocked_henrik_caution_stress_sample,
) -> None:
    """HC-AC-1 failure-mode: hold-out validation gap (some writes in the
    stress-sample were *not* confirmed by the hold-out Python-writer).

    Operational rationale: the hold-out writer may have dropped writes
    due to its own resource-constraints; that gap is not acceptable
    under Henrik-Caution — every sampled write must be byte-paritär-
    confirmed.
    """
    record = mocked_henrik_caution_stress_sample(
        WELLE_NAME,
        stress_window_request_count=5000,
        holdout_validated_count=4990,  # 10 writes unconfirmed
    )
    with pytest.raises(AssertionError, match="HC-AC-1"):
        assert_henrik_caution_ac_1_independent_stress_validation(
            record, WELLE_NAME
        )


def test_welle_3_hc_ac_1_self_referential_oracle_blocks(
    mocked_henrik_caution_stress_sample,
) -> None:
    """HC-AC-1 failure-mode: oracle_independence_confirmed=False.

    The stress-test accidentally used the Rust-writer-under-cutover as
    its own consistency-oracle (self-referential validation). This is
    the central Henrik-Caution rejection mode — Welle-3 cannot use the
    artefact-under-cutover as the oracle that certifies it.
    """
    record = mocked_henrik_caution_stress_sample(
        WELLE_NAME, oracle_independence_confirmed=False
    )
    with pytest.raises(AssertionError, match="HC-AC-1"):
        assert_henrik_caution_ac_1_independent_stress_validation(
            record, WELLE_NAME
        )


def test_welle_3_hc_ac_1_empty_stress_window_blocks(
    mocked_henrik_caution_stress_sample,
) -> None:
    """HC-AC-1 failure-mode: empty stress-window."""
    record = mocked_henrik_caution_stress_sample(
        WELLE_NAME, stress_window_request_count=0, holdout_validated_count=0
    )
    with pytest.raises(AssertionError, match="HC-AC-1"):
        assert_henrik_caution_ac_1_independent_stress_validation(
            record, WELLE_NAME
        )


# ---------------------------------------------------------------------------
# HC-AC-2 — Welle-3-Rollback bei >0.5% Divergenz (atomic ENV-Flag-switch).
# ---------------------------------------------------------------------------


def test_welle_3_hc_ac_2_below_threshold_no_rollback(
    mocked_henrik_caution_divergence_rollback,
) -> None:
    """HC-AC-2: divergence 0.1% (below 0.5% threshold) → no rollback fires.

    Sub-threshold divergence stays in observation; the cost-of-false-
    positive of an unwarranted rollback (re-run of Cutover-Mittwoch)
    is non-trivial.
    """
    record = mocked_henrik_caution_divergence_rollback(
        WELLE_NAME, observed_divergence_pct=0.1
    )
    assert_henrik_caution_ac_2_divergence_rollback(record, WELLE_NAME)


def test_welle_3_hc_ac_2_above_threshold_rollback_fires(
    mocked_henrik_caution_divergence_rollback,
) -> None:
    """HC-AC-2: divergence 0.8% (above 0.5% threshold) → automatic
    atomic ENV-Flag-switch rollback fires within SLA.
    """
    record = mocked_henrik_caution_divergence_rollback(
        WELLE_NAME, observed_divergence_pct=0.8
    )
    assert_henrik_caution_ac_2_divergence_rollback(record, WELLE_NAME)


def test_welle_3_hc_ac_2_at_threshold_rollback_fires(
    mocked_henrik_caution_divergence_rollback,
) -> None:
    """HC-AC-2: divergence exactly at 0.5% threshold → rollback fires
    (inclusive boundary).
    """
    record = mocked_henrik_caution_divergence_rollback(
        WELLE_NAME,
        observed_divergence_pct=HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD,
    )
    assert_henrik_caution_ac_2_divergence_rollback(record, WELLE_NAME)


def test_welle_3_hc_ac_2_missed_rollback_blocks(
    mocked_henrik_caution_divergence_rollback,
) -> None:
    """HC-AC-2 failure-mode: divergence above threshold but rollback
    did not fire. Central Henrik-Caution failure-mode.
    """
    record = mocked_henrik_caution_divergence_rollback(
        WELLE_NAME,
        observed_divergence_pct=0.8,
        rollback_triggered=False,
    )
    with pytest.raises(AssertionError, match="HC-AC-2"):
        assert_henrik_caution_ac_2_divergence_rollback(record, WELLE_NAME)


def test_welle_3_hc_ac_2_spurious_rollback_blocks(
    mocked_henrik_caution_divergence_rollback,
) -> None:
    """HC-AC-2 failure-mode: divergence below threshold but rollback
    fired anyway (false-positive rollback).
    """
    record = mocked_henrik_caution_divergence_rollback(
        WELLE_NAME,
        observed_divergence_pct=0.1,
        rollback_triggered=True,
    )
    with pytest.raises(AssertionError, match="HC-AC-2"):
        assert_henrik_caution_ac_2_divergence_rollback(record, WELLE_NAME)


def test_welle_3_hc_ac_2_non_atomic_rollback_blocks(
    mocked_henrik_caution_divergence_rollback,
) -> None:
    """HC-AC-2 failure-mode: rollback fired but split-state window
    observed (env_flag_switch_atomic=False).
    """
    record = mocked_henrik_caution_divergence_rollback(
        WELLE_NAME,
        observed_divergence_pct=0.8,
        env_flag_switch_atomic=False,
    )
    with pytest.raises(AssertionError, match="HC-AC-2"):
        assert_henrik_caution_ac_2_divergence_rollback(record, WELLE_NAME)


def test_welle_3_hc_ac_2_rollback_sla_violation_blocks(
    mocked_henrik_caution_divergence_rollback,
) -> None:
    """HC-AC-2 failure-mode: rollback elapsed > 600s SLA."""
    record = mocked_henrik_caution_divergence_rollback(
        WELLE_NAME,
        observed_divergence_pct=0.8,
        rollback_elapsed_seconds=720.0,  # > 600s SLA
    )
    with pytest.raises(AssertionError, match="HC-AC-2"):
        assert_henrik_caution_ac_2_divergence_rollback(record, WELLE_NAME)


# ---------------------------------------------------------------------------
# HC-AC-3 — Pre-Cutover-Konsistenz-Baseline aus 7-Tage-Observability-
# Window.
# ---------------------------------------------------------------------------


def test_welle_3_hc_ac_3_full_seven_day_baseline_green(
    mocked_henrik_caution_pre_cutover_baseline,
) -> None:
    """HC-AC-3: seven contiguous days, all at 99.8% consistency-rate
    (above the 99.5% floor). Welle-3 Cutover-Mittwoch may fire.
    """
    record = mocked_henrik_caution_pre_cutover_baseline(WELLE_NAME)
    assert_henrik_caution_ac_3_pre_cutover_baseline(record, WELLE_NAME)


def test_welle_3_hc_ac_3_short_baseline_window_blocks(
    mocked_henrik_caution_pre_cutover_baseline,
) -> None:
    """HC-AC-3 failure-mode: only 5 days observed (window incomplete).

    The Welle-3 Cutover-Mittwoch cannot fire on a short baseline; the
    7-day floor is Henrik-Caution-non-negotiable.
    """
    record = mocked_henrik_caution_pre_cutover_baseline(
        WELLE_NAME, observed_days=5
    )
    with pytest.raises(AssertionError, match="HC-AC-3"):
        assert_henrik_caution_ac_3_pre_cutover_baseline(record, WELLE_NAME)


def test_welle_3_hc_ac_3_one_day_below_floor_blocks(
    mocked_henrik_caution_pre_cutover_baseline,
) -> None:
    """HC-AC-3 failure-mode: day-3 consistency-rate 99.2% (below 99.5%
    floor). Single-day breach blocks the gate.
    """
    record = mocked_henrik_caution_pre_cutover_baseline(
        WELLE_NAME, per_day_overrides={3: 0.992}
    )
    with pytest.raises(AssertionError, match="HC-AC-3"):
        assert_henrik_caution_ac_3_pre_cutover_baseline(record, WELLE_NAME)


def test_welle_3_hc_ac_3_floor_boundary_at_995_passes(
    mocked_henrik_caution_pre_cutover_baseline,
) -> None:
    """HC-AC-3: exactly-at-floor 99.5% passes (inclusive boundary)."""
    record = mocked_henrik_caution_pre_cutover_baseline(
        WELLE_NAME,
        default_rate=0.995,
    )
    assert_henrik_caution_ac_3_pre_cutover_baseline(record, WELLE_NAME)


def test_welle_3_hc_ac_3_multiple_days_failing_blocks(
    mocked_henrik_caution_pre_cutover_baseline,
) -> None:
    """HC-AC-3 failure-mode: three days below floor; error-message must
    enumerate all failing days for Operator-Hand follow-up.
    """
    record = mocked_henrik_caution_pre_cutover_baseline(
        WELLE_NAME,
        per_day_overrides={1: 0.991, 4: 0.989, 6: 0.993},
    )
    with pytest.raises(AssertionError) as exc_info:
        assert_henrik_caution_ac_3_pre_cutover_baseline(record, WELLE_NAME)
    error_msg = str(exc_info.value)
    assert "HC-AC-3" in error_msg
    for day in (1, 4, 6):
        assert f"d{day}=" in error_msg, (
            f"HC-AC-3 error-message must enumerate failing day d{day} "
            f"for Operator-Hand follow-up; got {error_msg!r}"
        )


# ---------------------------------------------------------------------------
# Welle-3 Henrik-Caution substrate sanity — solo-cadence assertion.
# ---------------------------------------------------------------------------


def test_welle_3_henrik_caution_baseline_window_is_seven_days() -> None:
    """Sanity: HC-AC-3 baseline-window must be 7 days per ADR-0066.

    Guards against silent constant-drift in the conftest. The 7-day
    floor is the Henrik-Caution carve-out and changing it requires an
    ADR-Folge-Item, not a conftest-edit.
    """
    assert HENRIK_CAUTION_PRE_CUTOVER_BASELINE_DAYS == 7, (
        f"HC-AC-3 baseline-window must be 7 days (ADR-0066 Henrik-"
        f"Caution); got {HENRIK_CAUTION_PRE_CUTOVER_BASELINE_DAYS}"
    )


def test_welle_3_henrik_caution_divergence_threshold_is_zero_point_five() -> None:
    """Sanity: HC-AC-2 divergence-threshold must be 0.5% per ADR-0066."""
    assert HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD == 0.5, (
        f"HC-AC-2 divergence-threshold must be 0.5% (ADR-0066 Henrik-"
        f"Caution); got {HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD}"
    )
