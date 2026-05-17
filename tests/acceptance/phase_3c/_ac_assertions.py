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
    BackendDecisionRecord,
    BridgeAuditRoundtripRecord,
    CrossModulSchemaRecord,
    CrossModulStressTestRecord,
    CrossReviewRecord,
    EngineBootRecord,
    SingleKomponenteRollbackRecord,
)

# Rollback-SLA constant (ADR-0065 §Rollback-Strategie, retained
# ADR-0066): ENV-Flag-Switch ≤10min pro Komponente. Used by DW-AC-3.
ROLLBACK_SLA_SECONDS = 600.0


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


# ---------------------------------------------------------------------------
# Doppel-Welle Acceptance-Kriterien — DW-AC-1 ... DW-AC-5
#
# Anchor: ADR-0066 §Beschluss + §Mitigations. Five criteria specialise
# the per-welle AC-1 ... AC-5 to the parallel-cutover context:
#
# * DW-AC-1: both moduln boot with rust-backend in same boot-cycle.
# * DW-AC-2: cross-modul schema-byte-parity across the touchpoints.
# * DW-AC-3: asymmetric rollback works (one rolls back, other stays
#   rust) under the ≤10min ENV-Flag-Switch SLA.
# * DW-AC-4: cross-modul-stress-test green (Phase-2-Acceptance-Gate-
#   Erweiterung per ADR-0066 §Mitigation 1, references Tomás Tag-29
#   substrate).
# * DW-AC-5: Backend-Decision-Audit emits exactly 2 records, same
#   cutover-cycle-id, both target rust.
# ---------------------------------------------------------------------------


def assert_dw_ac_1_both_moduln_boot_rust(
    boot: EngineBootRecord,
    modul_a: str,
    modul_b: str,
    welle_pair_label: str,
) -> None:
    """DW-AC-1 — Both Doppel-Welle moduln boot with rust-backend in the
    same engine-boot-cycle.

    Asserts:
    * Boot succeeded.
    * Both pair-moduln resolved to ``rust``.
    * No third modul accidentally flipped to ``rust`` (Cutover-
      Mittwoch-Doppel-Cutover discipline — exactly the pair, no extras).
    """
    assert boot.boot_succeeded, (
        f"DW-AC-1[{welle_pair_label}]: engine-boot must succeed under "
        f"Doppel-Welle cutover; got failure-record {boot}"
    )
    for modul in (modul_a, modul_b):
        observed = boot.backend_per_modul.get(modul)
        assert observed == "rust", (
            f"DW-AC-1[{welle_pair_label}]: Doppel-Welle modul {modul!r} "
            f"must boot on rust-backend; got {observed!r}"
        )
    extra_rust = [
        m
        for m, b in boot.backend_per_modul.items()
        if b == "rust" and m not in (modul_a, modul_b)
    ]
    assert not extra_rust, (
        f"DW-AC-1[{welle_pair_label}]: Doppel-Welle must flip ONLY the "
        f"pair ({modul_a!r}, {modul_b!r}); extra rust-flipped moduln: "
        f"{extra_rust}"
    )


def assert_dw_ac_2_cross_modul_schema_byte_parity(
    records: Iterable[CrossModulSchemaRecord],
    welle_pair_label: str,
) -> None:
    """DW-AC-2 — Cross-Modul-Schema byte-paritär across all touchpoints.

    Any byte-divergence on a producer→consumer touchpoint blocks the
    gate. The Phase-3c-trigger-sprint wires this against real JCS
    output from both rust-backed moduln of the pair.
    """
    records_list = list(records)
    assert records_list, (
        f"DW-AC-2[{welle_pair_label}]: must observe at least one cross-"
        f"modul touchpoint record; got empty set"
    )
    drift: list[str] = []
    for rec in records_list:
        if not rec.is_byte_parity:
            drift.append(
                f"{rec.touchpoint_id} "
                f"prod={rec.producer_bytes_sha256[:16]} "
                f"cons={rec.consumer_bytes_sha256[:16]}"
            )
    assert not drift, (
        f"DW-AC-2[{welle_pair_label}]: Cross-Modul-Schema byte-parity "
        f"violated at touchpoints: {drift}"
    )


def assert_dw_ac_3_asymmetric_rollback(
    rollback: SingleKomponenteRollbackRecord,
    welle_pair_label: str,
) -> None:
    """DW-AC-3 — Single-Komponente-Rollback bei Bug: only the affected
    modul rolls back, the partner stays on rust.

    Gates:
    * Rolled-back modul is post-state ``python``.
    * Partner modul is post-state ``rust``.
    * Elapsed-seconds ≤ ROLLBACK_SLA_SECONDS (10min SLA).

    The Phase-3c-trigger-sprint wires this against the real
    ``systemctl restart wakir-persona-engine`` + ENV-rewrite drill
    (Operator-Hand-runbook).
    """
    modul_a, modul_b = rollback.welle_pair
    rolled = rollback.rolled_back_modul
    assert rolled in (modul_a, modul_b), (
        f"DW-AC-3[{welle_pair_label}]: rolled_back_modul {rolled!r} must "
        f"be a member of the welle-pair ({modul_a!r}, {modul_b!r})"
    )
    partner = modul_b if rolled == modul_a else modul_a

    rolled_state = rollback.post_rollback_backend_per_modul.get(rolled)
    assert rolled_state == "python", (
        f"DW-AC-3[{welle_pair_label}]: rolled-back modul {rolled!r} must "
        f"end on python-backend; got {rolled_state!r}"
    )
    partner_state = rollback.post_rollback_backend_per_modul.get(partner)
    assert partner_state == "rust", (
        f"DW-AC-3[{welle_pair_label}]: partner modul {partner!r} must "
        f"stay on rust-backend (asymmetric rollback discipline); got "
        f"{partner_state!r}"
    )
    assert rollback.rollback_elapsed_seconds <= ROLLBACK_SLA_SECONDS, (
        f"DW-AC-3[{welle_pair_label}]: rollback elapsed "
        f"{rollback.rollback_elapsed_seconds:.1f}s exceeds "
        f"{ROLLBACK_SLA_SECONDS:.0f}s SLA"
    )


def assert_dw_ac_4_cross_modul_stress_test_green(
    record: CrossModulStressTestRecord,
    welle_pair_label: str,
) -> None:
    """DW-AC-4 — Cross-Modul-Stress-Test grün (Phase-2-Acceptance-Gate-
    Erweiterung per ADR-0066 §Mitigation 1, Tomás Tag-29 substrate).

    Three sub-gates: zero failures, zero p99-latency-excursions, zero
    cross-modul-schema-drifts over the stress-window.
    """
    assert record.total_request_count > 0, (
        f"DW-AC-4[{welle_pair_label}]: stress-test must observe ≥1 "
        f"request; got total={record.total_request_count}"
    )
    assert record.failure_count == 0, (
        f"DW-AC-4[{welle_pair_label}]: Cross-Modul-Stress-Test "
        f"failure_count={record.failure_count} > 0"
    )
    assert record.p99_latency_excursion_count == 0, (
        f"DW-AC-4[{welle_pair_label}]: Cross-Modul-Stress-Test "
        f"p99_latency_excursion_count={record.p99_latency_excursion_count}"
        f" > 0"
    )
    assert record.cross_modul_schema_drift_count == 0, (
        f"DW-AC-4[{welle_pair_label}]: Cross-Modul-Stress-Test "
        f"cross_modul_schema_drift_count="
        f"{record.cross_modul_schema_drift_count} > 0"
    )


def assert_dw_ac_5_backend_decision_audit_two_records_consistent(
    records: Iterable[BackendDecisionRecord],
    modul_a: str,
    modul_b: str,
    welle_pair_label: str,
) -> None:
    """DW-AC-5 — Backend-Decision-Audit emits exactly 2 records in the
    same cutover-cycle, both targeting rust, both naming the pair-moduln.

    Asymmetric-rollback paths emit different audit-trails — DW-AC-5
    is the *cutover-flip* audit-trail. The rollback-trail is covered
    by DW-AC-3 plus Henrik's audit-sample (Zone-N).
    """
    records_list = list(records)
    assert len(records_list) == 2, (
        f"DW-AC-5[{welle_pair_label}]: Backend-Decision-Audit must emit "
        f"exactly 2 records on Doppel-Welle cutover; got "
        f"{len(records_list)}: {records_list}"
    )
    observed_moduln = {r.modul for r in records_list}
    expected_moduln = {modul_a, modul_b}
    assert observed_moduln == expected_moduln, (
        f"DW-AC-5[{welle_pair_label}]: audit records must name both "
        f"pair-moduln {expected_moduln}; got {observed_moduln}"
    )
    cycle_ids = {r.cutover_cycle_id for r in records_list}
    assert len(cycle_ids) == 1, (
        f"DW-AC-5[{welle_pair_label}]: both audit records must share a "
        f"single cutover-cycle-id; got {cycle_ids}"
    )
    wrong_target = [
        r.modul for r in records_list if r.target_backend != "rust"
    ]
    assert not wrong_target, (
        f"DW-AC-5[{welle_pair_label}]: cutover-target_backend must be "
        f"'rust' for all records; deviating moduln: {wrong_target}"
    )
