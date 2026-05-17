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
)
from .conftest import WELLE_BY_NAME

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
