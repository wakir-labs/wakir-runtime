# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Shared AC-1...AC-5 assertion helpers for the Phase-3c-Acceptance E2E
test-suite skeleton.

The five acceptance-criteria from ADR-0065 §Verifikations-Plan apply
welle-for-welle. Encoding the assertion-shape in a shared helper keeps
the seven welle-test files lean (each welle-file specialises only the
welle-specific behavioural fixtures + the modul-name binding) and
makes contract-drift surface in *one* place when the Phase-3c-trigger
sprint wires the real engine.

This is NOT a test-collector module — it carries no ``test_*``
functions and is imported as a plain helper.
"""

from __future__ import annotations

from typing import Iterable

from .conftest import (
    BUG_RATE_S0_S1_THRESHOLD,
    CONSISTENCY_REPORT_REQUIRED_GREEN_DAYS,
    CONSISTENCY_REPORT_WINDOW_DAYS,
    CROSS_REVIEW_REQUIRED_PERSONAS,
    PERFORMANCE_HEADROOM_FACTOR,
    V907_PIN_VALIDATION_REQUIRED_RATE,
    BridgeAuditRoundtripRecord,
    CrossReviewRecord,
)


def assert_ac_1_bridge_audit_consistency(
    roundtrips: Iterable[BridgeAuditRoundtripRecord],
    welle: str,
) -> None:
    """AC-1 — Bridge-Audit-Writer-Konsistenz-Report 5/5 days green.

    Iterates the ``BridgeAuditRoundtripRecord`` set, groups by
    ``day_index``, and asserts that *every* day inside the
    ``CONSISTENCY_REPORT_WINDOW_DAYS`` window has 100% parity.
    """
    by_day: dict[int, list[BridgeAuditRoundtripRecord]] = {}
    for rt in roundtrips:
        by_day.setdefault(rt.day_index, []).append(rt)

    observed_days = sorted(by_day.keys())
    expected_days = list(range(CONSISTENCY_REPORT_WINDOW_DAYS))
    assert observed_days == expected_days, (
        f"AC-1[{welle}]: must observe all {CONSISTENCY_REPORT_WINDOW_DAYS} "
        f"days of the consistency-report window; got {observed_days}"
    )

    green_days = 0
    drift_records: list[str] = []
    for day in observed_days:
        day_rts = by_day[day]
        day_consistent = all(rt.is_consistent for rt in day_rts)
        if day_consistent:
            green_days += 1
        else:
            for rt in day_rts:
                if not rt.is_consistent:
                    drift_records.append(
                        f"d{day}/{rt.request_id} "
                        f"py={rt.python_envelope_sha256[:16]} "
                        f"rust={rt.rust_envelope_sha256[:16]}"
                    )

    assert green_days >= CONSISTENCY_REPORT_REQUIRED_GREEN_DAYS, (
        f"AC-1[{welle}]: Bridge-Audit-Writer-Konsistenz-Report requires "
        f"{CONSISTENCY_REPORT_REQUIRED_GREEN_DAYS}/{CONSISTENCY_REPORT_WINDOW_DAYS} "
        f"green days; got {green_days}. Drift records: {drift_records}"
    )


def assert_ac_2_performance_headroom(
    python_baseline_p95_ms: float,
    rust_observed_p95_ms: float,
    welle: str,
) -> None:
    """AC-2 — Performance: P95-Latency ≤ Python-Baseline × headroom-factor.

    Mock-values pre-Welle-Start. Phase-3c-trigger sprint replaces with
    real Noa-Prometheus-Gauge readings (p95 over the 5-day Beobachtungs-
    Fenster window).
    """
    budget_ms = python_baseline_p95_ms * PERFORMANCE_HEADROOM_FACTOR
    assert rust_observed_p95_ms <= budget_ms, (
        f"AC-2[{welle}]: Rust-backend P95-Latency {rust_observed_p95_ms:.2f}ms "
        f"exceeds Python-baseline+20% headroom budget {budget_ms:.2f}ms "
        f"(python-baseline {python_baseline_p95_ms:.2f}ms × "
        f"{PERFORMANCE_HEADROOM_FACTOR})"
    )


def assert_ac_3_bug_rate(
    s0_count: int,
    s1_count: int,
    welle: str,
) -> None:
    """AC-3 — Bug-Rate: 0 substanz-relevante (S0/S1) Issues during
    Beobachtungs-Woche.
    """
    total = s0_count + s1_count
    assert total <= BUG_RATE_S0_S1_THRESHOLD, (
        f"AC-3[{welle}]: S0/S1 bug-count {total} exceeds threshold "
        f"{BUG_RATE_S0_S1_THRESHOLD} (S0={s0_count}, S1={s1_count})"
    )


def assert_ac_4_cross_review_consensus(
    record: CrossReviewRecord,
    welle: str,
) -> None:
    """AC-4 — Cross-Review-Session-Konsensus: alle Engineering-Personas
    zustimmend (Aisha-Protokoll).
    """
    missing = tuple(
        p
        for p in CROSS_REVIEW_REQUIRED_PERSONAS
        if p not in record.consenting_personas
    )
    assert not missing, (
        f"AC-4[{welle}]: Cross-Review-Session missing persona-consent: "
        f"{missing}. Required: {CROSS_REVIEW_REQUIRED_PERSONAS}, "
        f"observed: {record.consenting_personas}"
    )
    assert record.moderator == "aisha", (
        f"AC-4[{welle}]: Cross-Review-Session-Moderator must be Aisha "
        f"(HR-Protokoll); got {record.moderator!r}"
    )


def assert_ac_5_v907_pin_validation(
    persona_def_count: int,
    pin_validation_pass_count: int,
    welle: str,
) -> None:
    """AC-5 — V-907 Pin-Validation: 100% pass-rate on all Persona-Defs
    (Cache-Konflikt-Free, ADR-0064 §Risiken).
    """
    assert persona_def_count > 0, (
        f"AC-5[{welle}]: must validate against a non-empty Persona-Def set"
    )
    pass_rate = pin_validation_pass_count / persona_def_count
    assert pass_rate >= V907_PIN_VALIDATION_REQUIRED_RATE, (
        f"AC-5[{welle}]: V-907 Pin-Validation pass-rate {pass_rate:.4f} "
        f"below required {V907_PIN_VALIDATION_REQUIRED_RATE} "
        f"({pin_validation_pass_count}/{persona_def_count})"
    )
