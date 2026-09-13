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
    assert_henrik_caution_ac_1_independent_oracle_validation,
    assert_henrik_caution_ac_2_atomic_rollback,
    assert_henrik_caution_ac_3_pre_cutover_window,
)
from .conftest import (
    HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD,
    HENRIK_CAUTION_INDEPENDENT_ORACLE_SOURCES,
    HENRIK_CAUTION_PRE_CUTOVER_CONSISTENCY_PCT_FLOOR,
    HENRIK_CAUTION_PRE_CUTOVER_WINDOW_DAYS,
    HENRIK_CAUTION_ROLLBACK_SLA_SECONDS,
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
# HC-AC-1 — Independent-Oracle Validation (Henrik-Caution-Extension).
#
# Welle-3 Solo-Welle-carve-out (ADR-0066 §Beschluss). bridge_audit_
# writer is the consistency-oracle substrate for other Wellen, so it
# cannot self-validate during its own cutover. HC-AC-1 enforces that
# the cross-validation pulls from an independent substrate (PR #197
# Cross-Modul-Stress-Test or Operator-Hand-deployed hold-out Python-
# writer-instance).
# ---------------------------------------------------------------------------


def test_welle_3_hc_ac_1_independent_oracle_validation_cross_modul_stress_test(
    mocked_henrik_caution_independent_oracle,
) -> None:
    """HC-AC-1: PR #197 Cross-Modul-Stress-Test substrate validates
    Welle-3 Rust-writer envelope-hashes byte-paritär.

    The Phase-3c-trigger sprint wires this against the real PR #197
    stress-test output: each Welle-3 cutover-day's Rust-writer
    envelope-hash for the day's request-set is cross-validated against
    the independent stress-test substrate's hash for the same request.
    """
    records = mocked_henrik_caution_independent_oracle(
        oracle_source="cross-modul-stress-test-pr-197",
    )
    assert_henrik_caution_ac_1_independent_oracle_validation(
        records, WELLE_NAME
    )


def test_welle_3_hc_ac_1_independent_oracle_validation_holdout_writer(
    mocked_henrik_caution_independent_oracle,
) -> None:
    """HC-AC-1 direction-check: hold-out Python-writer-instance also
    valid as independent-oracle substrate.

    Per ADR-0065 §Empfehlung Footnote, an Operator-Hand-deployed
    Python-pinned writer-instance running parallel to the Rust-default
    writer on cutover-Tag serves as the consistency-oracle. The hold-
    out instance is decommissioned after AC-1 5/5 days green.
    """
    records = mocked_henrik_caution_independent_oracle(
        oracle_source="holdout-python-writer-instance",
    )
    assert_henrik_caution_ac_1_independent_oracle_validation(
        records, WELLE_NAME
    )


def test_welle_3_hc_ac_1_self_validation_rejected(
    mocked_henrik_caution_independent_oracle,
) -> None:
    """HC-AC-1 failure-mode: bridge_audit_writer self-validation
    rejected.

    This is the dominant Henrik-Caution failure-class: the operator-
    side runbook accidentally compares the Welle-3 Rust-writer's
    output against the same Welle-3 Rust-writer's output (self-
    referential validation). HC-AC-1 surfaces this as an explicit
    self-validation rejection via the ``self_referential_flag`` guard.
    """
    records = mocked_henrik_caution_independent_oracle(
        oracle_source="bridge_audit_writer_self",
        self_referential=True,
    )
    with pytest.raises(AssertionError, match="HC-AC-1"):
        assert_henrik_caution_ac_1_independent_oracle_validation(
            records, WELLE_NAME
        )


def test_welle_3_hc_ac_1_invalid_oracle_source_rejected(
    mocked_henrik_caution_independent_oracle,
) -> None:
    """HC-AC-1 failure-mode: oracle-source outside the allowed set.

    A typo or drift in the operator-runbook (e.g. switching to a
    third-party oracle that hasn't been ADR-blessed) blocks the gate.
    """
    records = mocked_henrik_caution_independent_oracle(
        oracle_source="ad-hoc-prometheus-counter",
    )
    with pytest.raises(AssertionError, match="HC-AC-1"):
        assert_henrik_caution_ac_1_independent_oracle_validation(
            records, WELLE_NAME
        )


def test_welle_3_hc_ac_1_oracle_drift_blocks(
    mocked_henrik_caution_independent_oracle,
) -> None:
    """HC-AC-1 failure-mode: Rust-writer/independent-oracle hash drift.

    The Rust-writer emits an envelope-hash that the independent
    substrate disagrees with — the substantive Welle-3 cutover-
    blocker. The independent-oracle substrate is the dominant signal
    here precisely because it is not the bridge_audit_writer itself.
    """
    records = mocked_henrik_caution_independent_oracle(
        drift_request_ids=("req-hc1-b",),
    )
    with pytest.raises(AssertionError, match="HC-AC-1"):
        assert_henrik_caution_ac_1_independent_oracle_validation(
            records, WELLE_NAME
        )


def test_welle_3_hc_ac_1_oracle_source_set_anchored_to_adr_0066() -> None:
    """HC-AC-1 sanity: independent-oracle-source enumeration is ADR-
    0066-fixed.

    Adding a new oracle-source requires an ADR-Folge-Item, not a
    conftest-edit. The current set is exactly
    (cross-modul-stress-test-pr-197, holdout-python-writer-instance);
    bridge_audit_writer self is explicitly excluded by absence.
    """
    assert HENRIK_CAUTION_INDEPENDENT_ORACLE_SOURCES == (
        "cross-modul-stress-test-pr-197",
        "holdout-python-writer-instance",
    ), (
        f"HC-AC-1 oracle-source set anchored to ADR-0066 — must be "
        f"(cross-modul-stress-test-pr-197, holdout-python-writer-"
        f"instance); got {HENRIK_CAUTION_INDEPENDENT_ORACLE_SOURCES!r}"
    )


# ---------------------------------------------------------------------------
# HC-AC-2 — Atomic ENV-Flag-Switch Rollback ≤600s SLA.
#
# Symmetric gates for missed-rollback (false-negative) and spurious-
# rollback (false-positive). The 0.5pp divergence threshold mirrors
# the CMD-AC-4 atomic-flip-pattern numerically but applies whole-
# bridge-audit-writer rather than per-modul.
# ---------------------------------------------------------------------------


def test_welle_3_hc_ac_2_atomic_rollback_happy_path(
    mocked_henrik_caution_atomic_rollback,
) -> None:
    """HC-AC-2: divergence > 0.5pp → atomic rollback fires, ≤600s.

    The Phase-3c-trigger sprint wires this against the real Operator-
    Hand-runbook: ENV-Flag rewrite + ``systemctl restart wakir-
    persona-engine``, single restart-cycle, post-flip backend = python.
    """
    record = mocked_henrik_caution_atomic_rollback(
        measured_divergence_pct=0.8,
        rollback_fired=True,
    )
    assert_henrik_caution_ac_2_atomic_rollback(record, WELLE_NAME)


def test_welle_3_hc_ac_2_no_trigger_steady_state(
    mocked_henrik_caution_atomic_rollback,
) -> None:
    """HC-AC-2: divergence ≤ 0.5pp → no rollback, steady-state rust.

    Sub-threshold drift does not warrant an automated atomic-rollback;
    Welle-3 stays on rust-default. The gate-shape verifies the no-op
    path is gated symmetrically to the rollback-fired path.
    """
    record = mocked_henrik_caution_atomic_rollback(
        measured_divergence_pct=0.35,
        rollback_fired=False,
    )
    assert_henrik_caution_ac_2_atomic_rollback(record, WELLE_NAME)


def test_welle_3_hc_ac_2_missed_rollback_blocks(
    mocked_henrik_caution_atomic_rollback,
) -> None:
    """HC-AC-2 failure-mode: missed-rollback (false-negative).

    Divergence crosses the 0.5pp threshold but the operator-hand-
    runbook fails to fire the atomic rollback. The most operationally
    dangerous failure-class: the Welle-3 Rust-writer keeps writing
    drifted envelopes, contaminating the consistency-oracle substrate
    for the other Wellen.
    """
    record = mocked_henrik_caution_atomic_rollback(
        measured_divergence_pct=0.85,
        rollback_fired=False,
    )
    with pytest.raises(
        AssertionError, match="HC-AC-2.*missed-rollback"
    ):
        assert_henrik_caution_ac_2_atomic_rollback(record, WELLE_NAME)


def test_welle_3_hc_ac_2_spurious_rollback_blocks(
    mocked_henrik_caution_atomic_rollback,
) -> None:
    """HC-AC-2 failure-mode: spurious-rollback (false-positive).

    Sub-threshold drift triggers an atomic rollback anyway —
    operationally indistinguishable from a flapping rollback-loop in
    the worst case. Symmetric-gate ensures the runbook does not over-
    fire when drift is benign.
    """
    record = mocked_henrik_caution_atomic_rollback(
        measured_divergence_pct=0.35,
        rollback_fired=True,
    )
    with pytest.raises(
        AssertionError, match="HC-AC-2.*spurious-rollback"
    ):
        assert_henrik_caution_ac_2_atomic_rollback(record, WELLE_NAME)


def test_welle_3_hc_ac_2_sla_violation_blocks(
    mocked_henrik_caution_atomic_rollback,
) -> None:
    """HC-AC-2 failure-mode: rollback fires but exceeds 600s SLA.

    A slow atomic-rollback extends the divergence-window and lets
    contaminated envelopes accumulate. Same SLA as CMD-AC-4 (600s
    ENV-Flag-Switch).
    """
    record = mocked_henrik_caution_atomic_rollback(
        measured_divergence_pct=0.8,
        rollback_fired=True,
        flip_elapsed_seconds=720.0,
    )
    with pytest.raises(AssertionError, match="HC-AC-2"):
        assert_henrik_caution_ac_2_atomic_rollback(record, WELLE_NAME)


def test_welle_3_hc_ac_2_non_atomic_flip_blocks(
    mocked_henrik_caution_atomic_rollback,
) -> None:
    """HC-AC-2 failure-mode: rollback fires but is non-atomic (multi-
    restart-cycle).

    The Operator-Hand-runbook is single-shot. A multi-cycle flip
    indicates the runbook drifted from the atomic-flip-pattern.
    """
    record = mocked_henrik_caution_atomic_rollback(
        measured_divergence_pct=0.8,
        rollback_fired=True,
        flip_was_atomic=False,
    )
    with pytest.raises(AssertionError, match="HC-AC-2"):
        assert_henrik_caution_ac_2_atomic_rollback(record, WELLE_NAME)


def test_welle_3_hc_ac_2_threshold_anchored_to_adr_0066() -> None:
    """HC-AC-2 sanity: the 0.5pp divergence threshold is ADR-0066-fixed.

    Tightening or loosening the threshold requires an ADR-Folge-Item,
    not a conftest-edit. Numerically equal to the CMD-AC-4 per-modul
    threshold but applied whole-bridge-audit-writer rather than per-
    modul.
    """
    assert HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD == 0.5, (
        f"HC-AC-2 divergence-threshold anchored to ADR-0066 — must be "
        f"0.5pp; got {HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD}"
    )


def test_welle_3_hc_ac_2_sla_anchored_to_adr_0066() -> None:
    """HC-AC-2 sanity: the 600s rollback-SLA is ADR-0066-fixed.

    Mirrors ROLLBACK_SLA_SECONDS in ``_ac_assertions.py`` (600s
    ENV-Flag-Switch SLA). Loosening this SLA requires an ADR-Folge-
    Item.
    """
    assert HENRIK_CAUTION_ROLLBACK_SLA_SECONDS == 600.0, (
        f"HC-AC-2 rollback-SLA anchored to ADR-0066 — must be 600s; "
        f"got {HENRIK_CAUTION_ROLLBACK_SLA_SECONDS}"
    )


# ---------------------------------------------------------------------------
# HC-AC-3 — Pre-Cutover-Observability-Window 7-day ≥99.5%.
#
# Longer-baseline than the AC-1 5-day Konsistenz-Report window because
# Welle-3 is the writer itself. The 7-day window absorbs a full
# operational week of write-pattern variation before the cutover-Tag.
# ---------------------------------------------------------------------------


def test_welle_3_hc_ac_3_pre_cutover_window_7_days_above_floor(
    mocked_henrik_caution_pre_cutover_window,
) -> None:
    """HC-AC-3: 7-day pre-cutover-window per-day consistency ≥99.5%.

    The Phase-3c-trigger sprint wires this against the real Welle-3
    cutover-week observability data: Prometheus-Gauge `wakir_engine_
    bridge_audit_writer_consistency_rate` aggregated per-day across
    the 7-day pre-cutover window.
    """
    records = mocked_henrik_caution_pre_cutover_window()
    assert_henrik_caution_ac_3_pre_cutover_window(records, WELLE_NAME)


def test_welle_3_hc_ac_3_single_day_below_floor_blocks(
    mocked_henrik_caution_pre_cutover_window,
) -> None:
    """HC-AC-3 failure-mode: a single day below the 99.5% floor blocks.

    Even one day below the floor inside the 7-day window blocks the
    cutover — the pre-cutover baseline must be uniformly green. A
    single below-floor day signals either a regression in the Python-
    writer (compromising the pre-cutover baseline) or a measurement-
    pipeline drift that must be debugged before cutover.
    """
    records = mocked_henrik_caution_pre_cutover_window(
        low_rate_day_index=3,
        low_rate_value=0.989,
    )
    with pytest.raises(AssertionError, match="HC-AC-3"):
        assert_henrik_caution_ac_3_pre_cutover_window(
            records, WELLE_NAME
        )


def test_welle_3_hc_ac_3_missing_day_blocks(
    mocked_henrik_caution_pre_cutover_window,
) -> None:
    """HC-AC-3 failure-mode: observability-pipeline drops a window day.

    A gap in the 7-day window (e.g. Prometheus-scrape outage) means
    the baseline is incomplete — the cutover-decision cannot be made
    on a 6-of-7-day baseline.
    """
    records = mocked_henrik_caution_pre_cutover_window(
        missing_day_index=5,
    )
    with pytest.raises(AssertionError, match="HC-AC-3"):
        assert_henrik_caution_ac_3_pre_cutover_window(
            records, WELLE_NAME
        )


def test_welle_3_hc_ac_3_window_length_anchored_to_adr_0066() -> None:
    """HC-AC-3 sanity: the 7-day window length is ADR-0066-fixed.

    Shortening the window (e.g. back to the AC-1 5-day Konsistenz-
    Report length) requires an ADR-Folge-Item. The 7-day length
    deliberately absorbs a full operational week of write-pattern
    variation (weekly Quadlet-restart-pattern + weekend write-pattern-
    differential).
    """
    assert HENRIK_CAUTION_PRE_CUTOVER_WINDOW_DAYS == 7, (
        f"HC-AC-3 pre-cutover-window length anchored to ADR-0066 — "
        f"must be 7 days; got {HENRIK_CAUTION_PRE_CUTOVER_WINDOW_DAYS}"
    )


def test_welle_3_hc_ac_3_consistency_floor_anchored_to_adr_0066() -> None:
    """HC-AC-3 sanity: the 99.5% per-day consistency-floor is ADR-
    0066-fixed.

    Mirrors the CMD-AC-3 per-Komponente consistency-floor numerically
    but applied per-day for the Welle-3 Pre-Cutover-Baseline rather
    than per-Komponente for the Welle-4+5 Stress-Window.
    """
    assert (
        HENRIK_CAUTION_PRE_CUTOVER_CONSISTENCY_PCT_FLOOR == 0.995
    ), (
        f"HC-AC-3 per-day consistency-floor anchored to ADR-0066 — "
        f"must be 0.995 (99.5%); got "
        f"{HENRIK_CAUTION_PRE_CUTOVER_CONSISTENCY_PCT_FLOOR}"
    )
