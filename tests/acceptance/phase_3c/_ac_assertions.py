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
    CROSS_MODUL_DRIFT_CONSISTENCY_PCT_FLOOR,
    CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD,
    CROSS_MODUL_DRIFT_WELLE_6_7_WIRE_FORM_ORACLES,
    CROSS_MODUL_DRIFT_WIRE_FORM_ORACLES,
    CROSS_REVIEW_REQUIRED_PERSONAS,
    HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD,
    HENRIK_CAUTION_INDEPENDENT_ORACLE_SOURCES,
    HENRIK_CAUTION_PRE_CUTOVER_CONSISTENCY_PCT_FLOOR,
    HENRIK_CAUTION_PRE_CUTOVER_WINDOW_DAYS,
    HENRIK_CAUTION_ROLLBACK_SLA_SECONDS,
    PERFORMANCE_HEADROOM_FACTOR,
    V907_PIN_VALIDATION_REQUIRED_RATE,
    BackendDecisionRecord,
    BridgeAuditRoundtripRecord,
    CrossModulDriftAtomicFlipRecord,
    CrossModulDriftDeserializationRecord,
    CrossModulDriftPerKomponenteConsistencyRecord,
    CrossModulDriftWelle6_7AckRoundTripRecord,
    CrossModulDriftWelle6_7AtomicFlipRecord,
    CrossModulDriftWelle6_7PerKomponenteConsistencyRecord,
    CrossModulDriftWelle6_7ResubscribeRecord,
    CrossModulDriftWriteBackRecord,
    CrossModulSchemaRecord,
    CrossModulStressTestRecord,
    CrossReviewRecord,
    EngineBootRecord,
    HenrikCautionAtomicRollbackRecord,
    HenrikCautionIndependentOracleRecord,
    HenrikCautionPreCutoverWindowRecord,
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


# ---------------------------------------------------------------------------
# Doppel-Welle-4+5 Cross-Modul-Drift Acceptance-Kriterien — CMD-AC-1 ...
# CMD-AC-4
#
# Anchor: ADR-0066 §Beschluss §"Doppel-Welle-4+5 Cross-Modul-Drift-
# Focus" + Priya CTO-Coordination-Plan v2 (Tag-32 Mini-Welle). These
# four criteria are layered atop DW-AC-1...DW-AC-5 specifically for
# the KW 26 Doppel-Welle-4+5 cutover (state_backing × lifecycle_state_
# machine) — the highest cross-modul-drift-risk Doppel-Welle slot.
#
# DW-AC-2 covers single-touchpoint byte-parity on the producer side;
# DW-AC-4 covers aggregate stress-test zero-failure. CMD-AC drills
# deeper into the Rust-Rust producer/consumer contract:
#
# * CMD-AC-1 — Producer→Consumer deserialization round-trip parity.
# * CMD-AC-2 — Consumer-triggered Producer write-back wire-form
#   parity vs. Python-baseline oracles.
# * CMD-AC-3 — Per-Komponente joint-consistency ≥99.5% (tighter
#   than DW-AC-4's zero-failure-floor).
# * CMD-AC-4 — Drift-triggered atomic single-Komponente rollback
#   when drift > 0.5pp; partner stays rust-Default.
# ---------------------------------------------------------------------------


def assert_cross_modul_drift_ac_1_deserialization_round_trip(
    records: Iterable[CrossModulDriftDeserializationRecord],
    welle_pair_label: str,
) -> None:
    """CMD-AC-1 — Producer→Consumer deserialization round-trip parity.

    ``state_backing-rust`` writes; ``lifecycle_state_machine-rust``
    reads + deserialises + re-serialises. Byte-identical round-trip
    plus schema-version field survival is the gate.

    Failure modes captured:

    * ``producer_serialized_sha256 !=
      consumer_deserialized_reserialized_sha256`` — deserialization
      mutates state (Unicode-normalisation drift, float-formatting
      drift, field-ordering drift).
    * ``schema_version_round_trip_ok == False`` — schema-version
      field dropped or rewritten on round-trip (a Welle-5-into-Welle-7-
      recovery-workflow-blocker since recovery reads terminal records
      to compute restart-points).
    """
    records_list = list(records)
    assert records_list, (
        f"CMD-AC-1[{welle_pair_label}]: must observe at least one "
        f"Producer→Consumer deserialization record; got empty set"
    )
    drift: list[str] = []
    schema_breakage: list[str] = []
    for rec in records_list:
        if (
            rec.producer_serialized_sha256
            != rec.consumer_deserialized_reserialized_sha256
        ):
            drift.append(
                f"{rec.record_id} "
                f"prod={rec.producer_serialized_sha256[:16]} "
                f"cons={rec.consumer_deserialized_reserialized_sha256[:16]}"
            )
        if not rec.schema_version_round_trip_ok:
            schema_breakage.append(rec.record_id)
    assert not drift, (
        f"CMD-AC-1[{welle_pair_label}]: Producer→Consumer "
        f"deserialization byte-drift at records: {drift}"
    )
    assert not schema_breakage, (
        f"CMD-AC-1[{welle_pair_label}]: schema-version round-trip "
        f"failure at records: {schema_breakage}"
    )


def assert_cross_modul_drift_ac_2_write_back_wire_form_parity(
    records: Iterable[CrossModulDriftWriteBackRecord],
    welle_pair_label: str,
) -> None:
    """CMD-AC-2 — Consumer-triggered Producer write-back wire-form parity.

    ``lifecycle_state_machine-rust`` triggers a state-transition; the
    resulting persist-write into ``state_backing-rust`` must produce
    a wire-form byte-identical to *every* reference oracle in
    ``CROSS_MODUL_DRIFT_WIRE_FORM_ORACLES``:

    * ``python-python-baseline`` — pre-Welle-4 cutover wire-form
      (the long-standing production state).
    * ``python-rust-welle-4-only`` — mid-Doppel-Welle hypothetical
      (state_backing rust, lifecycle still python). Never observed
      in production under the Doppel-Welle cutover-plan but a
      synthetic reference that catches Rust-side state_backing
      regressions independently of Rust-side lifecycle regressions.

    Asymmetric oracle drift (e.g. matches python-python but diverges
    from python-rust-welle-4-only) localises the bug to the Rust-
    side lifecycle modul. CMD-AC-2 fails on *any* oracle divergence.
    """
    records_list = list(records)
    assert records_list, (
        f"CMD-AC-2[{welle_pair_label}]: must observe at least one "
        f"Consumer→Producer write-back record; got empty set"
    )
    divergence: list[str] = []
    for rec in records_list:
        for oracle in CROSS_MODUL_DRIFT_WIRE_FORM_ORACLES:
            if not rec.matches_oracle(oracle):
                rust_rust = rec.rust_rust_wire_sha256[:16]
                oracle_hash = rec.oracle_wire_sha256_by_oracle.get(
                    oracle, "<missing>"
                )[:16]
                divergence.append(
                    f"{rec.transition_id}@{oracle} "
                    f"rust-rust={rust_rust} oracle={oracle_hash}"
                )
    assert not divergence, (
        f"CMD-AC-2[{welle_pair_label}]: write-back wire-form "
        f"divergence vs. reference oracles: {divergence}"
    )


def assert_cross_modul_drift_ac_3_per_komponente_consistency(
    record: CrossModulDriftPerKomponenteConsistencyRecord,
    welle_pair_label: str,
) -> None:
    """CMD-AC-3 — Cross-Modul-Stress-Test per-Komponente consistency
    ≥99.5%.

    DW-AC-4 sets zero-failure on aggregate; CMD-AC-3 sets a per-
    Komponente consistency-rate floor on the joint state_backing ⇆
    lifecycle_state_machine contract. Both per-Komponente rates must
    clear the 0.995 floor.

    The joint-consistency-rate (computed as ``min(rate_a, rate_b)``)
    is the gate-evaluation surface; a failure here means at least
    one of the two Doppel-Welle moduln has below-floor consistency
    even when the other is green.
    """
    modul_a, modul_b = record.welle_pair
    assert record.total_request_count > 0, (
        f"CMD-AC-3[{welle_pair_label}]: stress-test must observe ≥1 "
        f"request; got total={record.total_request_count}"
    )
    floor = CROSS_MODUL_DRIFT_CONSISTENCY_PCT_FLOOR
    failing: list[str] = []
    if record.modul_a_consistency_rate < floor:
        failing.append(
            f"{modul_a}={record.modul_a_consistency_rate:.4f}"
        )
    if record.modul_b_consistency_rate < floor:
        failing.append(
            f"{modul_b}={record.modul_b_consistency_rate:.4f}"
        )
    assert not failing, (
        f"CMD-AC-3[{welle_pair_label}]: per-Komponente consistency-"
        f"rate below {floor:.4f} floor: {failing}; "
        f"joint-rate={record.joint_consistency_rate:.4f}"
    )


def assert_cross_modul_drift_ac_4_atomic_flip_rollback(
    record: CrossModulDriftAtomicFlipRecord,
    welle_pair_label: str,
) -> None:
    """CMD-AC-4 — Drift-triggered atomic single-Komponente rollback.

    When measured cross-modul-drift exceeds 0.5pp, the affected modul
    flips back to python-Default while the partner stays on rust-
    Default (atomic-flip-pattern). The flip is single-shot, the
    elapsed time must clear the 10min ENV-Flag-Switch SLA, and the
    partner modul must not be touched.

    Gates:

    * The trigger-precondition must hold: ``measured_drift_pct >
      threshold_drift_pct`` (no spurious sub-threshold flips).
    * ``flip_was_atomic`` — single restart-cycle, no partial state.
    * Post-flip backend-per-modul: high-drift on python, partner
      on rust.
    * ``flip_elapsed_seconds`` ≤ ``ROLLBACK_SLA_SECONDS`` (600s).
    """
    modul_a, modul_b = record.welle_pair
    high_drift = record.high_drift_modul
    assert high_drift in (modul_a, modul_b), (
        f"CMD-AC-4[{welle_pair_label}]: high_drift_modul {high_drift!r} "
        f"must be a member of the welle-pair ({modul_a!r}, {modul_b!r})"
    )
    partner = modul_b if high_drift == modul_a else modul_a

    # Trigger-precondition: drift > threshold (0.5pp). Sub-threshold
    # flips are rejected as spurious.
    assert (
        record.measured_drift_pct > record.threshold_drift_pct
    ), (
        f"CMD-AC-4[{welle_pair_label}]: atomic-flip fired without a "
        f"trigger-precondition: measured drift "
        f"{record.measured_drift_pct:.4f}pp ≤ threshold "
        f"{record.threshold_drift_pct:.4f}pp (sub-threshold flips "
        f"are rejected as spurious)"
    )
    assert (
        record.threshold_drift_pct == CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD
    ), (
        f"CMD-AC-4[{welle_pair_label}]: threshold_drift_pct must equal "
        f"the ADR-0066-fixed {CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD}"
        f"pp; got {record.threshold_drift_pct}"
    )
    assert record.flip_was_atomic, (
        f"CMD-AC-4[{welle_pair_label}]: atomic-flip must be a single "
        f"restart-cycle; got non-atomic flip-record"
    )
    high_drift_state = record.post_flip_backend_per_modul.get(high_drift)
    assert high_drift_state == "python", (
        f"CMD-AC-4[{welle_pair_label}]: high-drift modul {high_drift!r} "
        f"must end on python-backend; got {high_drift_state!r}"
    )
    partner_state = record.post_flip_backend_per_modul.get(partner)
    assert partner_state == "rust", (
        f"CMD-AC-4[{welle_pair_label}]: partner modul {partner!r} must "
        f"stay on rust-Default (atomic-flip discipline); got "
        f"{partner_state!r}"
    )
    assert record.flip_elapsed_seconds <= ROLLBACK_SLA_SECONDS, (
        f"CMD-AC-4[{welle_pair_label}]: flip elapsed "
        f"{record.flip_elapsed_seconds:.1f}s exceeds "
        f"{ROLLBACK_SLA_SECONDS:.0f}s SLA"
    )


# ---------------------------------------------------------------------------
# Welle-3 Henrik-Caution Acceptance-Kriterien — HC-AC-1 ... HC-AC-3
#
# Anchor: ADR-0066 §Beschluss — Welle-3 (bridge_audit_writer) is the
# only Solo-Welle in the Doppel-Welle-Cadence because the writer *is*
# the consistency-oracle substrate. Three Henrik-Caution-Acceptance
# criteria layer on top of the per-welle AC-1...AC-5 baseline for KW
# 25 Solo-Welle-3 (Tag-31 Mini-Welle, ADR-0066-Folge):
#
# * HC-AC-1 — Independent-Oracle-Validation via PR #197 Cross-Modul-
#   Stress-Test substrate (or Operator-Hand-deployed hold-out Python-
#   writer-instance); bridge_audit_writer self-output rejected.
# * HC-AC-2 — Atomic ENV-Flag-Switch rollback ≤600s SLA, symmetric
#   gates for missed-rollback and spurious-rollback.
# * HC-AC-3 — Pre-Cutover-Observability-Window 7-day per-day
#   consistency ≥99.5%.
# ---------------------------------------------------------------------------


def assert_henrik_caution_ac_1_independent_oracle_validation(
    records: Iterable[HenrikCautionIndependentOracleRecord],
    welle: str,
) -> None:
    """HC-AC-1 — Independent-Oracle cross-validates Rust-writer output.

    The bridge_audit_writer is the consistency-oracle for *other*
    Wellen, so it cannot self-validate during its own Solo-cutover.
    HC-AC-1 enforces that:

    * The ``oracle_source`` field references an entry in
      ``HENRIK_CAUTION_INDEPENDENT_ORACLE_SOURCES`` (PR #197 stress-
      test substrate or hold-out Python-writer).
    * The ``self_referential_flag`` is False on every record (the
      validator is explicitly NOT bridge_audit_writer itself).
    * Every Rust-writer envelope-hash matches the independent oracle.

    Failure modes captured:

    * ``oracle_source == "bridge_audit_writer_self"`` — self-
      validation attempted.
    * ``self_referential_flag == True`` — operator-side guard tripped
      saying this is a self-validation record.
    * Hash divergence between Rust-writer and the independent oracle.
    """
    records_list = list(records)
    assert records_list, (
        f"HC-AC-1[{welle}]: must observe at least one independent-"
        f"oracle validation record; got empty set"
    )

    self_referential: list[str] = []
    invalid_oracle_sources: list[str] = []
    drift: list[str] = []
    for rec in records_list:
        if rec.self_referential_flag:
            self_referential.append(rec.request_id)
        if rec.oracle_source not in HENRIK_CAUTION_INDEPENDENT_ORACLE_SOURCES:
            invalid_oracle_sources.append(
                f"{rec.request_id}@{rec.oracle_source}"
            )
        if not rec.is_consistent:
            drift.append(
                f"{rec.request_id} "
                f"rust={rec.rust_writer_envelope_sha256[:16]} "
                f"oracle={rec.independent_oracle_envelope_sha256[:16]}"
            )

    assert not self_referential, (
        f"HC-AC-1[{welle}]: bridge_audit_writer self-validation "
        f"rejected — oracle must be independent; self-referential "
        f"records: {self_referential}"
    )
    assert not invalid_oracle_sources, (
        f"HC-AC-1[{welle}]: oracle-source must be one of "
        f"{list(HENRIK_CAUTION_INDEPENDENT_ORACLE_SOURCES)}; got "
        f"invalid sources: {invalid_oracle_sources}"
    )
    assert not drift, (
        f"HC-AC-1[{welle}]: Rust-writer/independent-oracle drift "
        f"at requests: {drift}"
    )


def assert_henrik_caution_ac_2_atomic_rollback(
    record: HenrikCautionAtomicRollbackRecord,
    welle: str,
) -> None:
    """HC-AC-2 — Atomic ENV-Flag-Switch rollback with symmetric gates.

    Gates:

    * Trigger-symmetry: ``rollback_fired`` must align with whether
      ``measured_divergence_pct`` crossed
      ``threshold_divergence_pct``. A fired-without-trigger is a
      spurious-rollback (false-positive); a not-fired-when-trigger-
      crossed is a missed-rollback (false-negative).
    * ``threshold_divergence_pct`` equals the ADR-0066-fixed 0.5pp.
    * If rollback fired: ``flip_was_atomic`` True, ``flip_elapsed_
      seconds`` ≤ 600s, post-flip backend = python.
    * If rollback did NOT fire (sub-threshold-no-trigger path):
      post-flip backend = rust (no-op steady-state).
    """
    above_threshold = (
        record.measured_divergence_pct > record.threshold_divergence_pct
    )

    # Symmetric gate-evaluation: rollback_fired must match
    # above_threshold.
    if above_threshold and not record.rollback_fired:
        raise AssertionError(
            f"HC-AC-2[{welle}]: missed-rollback (false-negative) — "
            f"measured divergence "
            f"{record.measured_divergence_pct:.4f}pp > threshold "
            f"{record.threshold_divergence_pct:.4f}pp but rollback "
            f"did not fire"
        )
    if not above_threshold and record.rollback_fired:
        raise AssertionError(
            f"HC-AC-2[{welle}]: spurious-rollback (false-positive) — "
            f"measured divergence "
            f"{record.measured_divergence_pct:.4f}pp ≤ threshold "
            f"{record.threshold_divergence_pct:.4f}pp but rollback "
            f"fired anyway"
        )

    assert (
        record.threshold_divergence_pct
        == HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD
    ), (
        f"HC-AC-2[{welle}]: threshold_divergence_pct must equal the "
        f"ADR-0066-fixed {HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD}pp; "
        f"got {record.threshold_divergence_pct}"
    )

    if record.rollback_fired:
        assert record.flip_was_atomic, (
            f"HC-AC-2[{welle}]: rollback fired but flip was non-atomic "
            f"(multi-restart-cycle); atomic-flip discipline broken"
        )
        assert (
            record.flip_elapsed_seconds <= HENRIK_CAUTION_ROLLBACK_SLA_SECONDS
        ), (
            f"HC-AC-2[{welle}]: rollback elapsed "
            f"{record.flip_elapsed_seconds:.1f}s exceeds "
            f"{HENRIK_CAUTION_ROLLBACK_SLA_SECONDS:.0f}s SLA"
        )
        assert record.post_flip_backend == "python", (
            f"HC-AC-2[{welle}]: post-rollback backend must be python; "
            f"got {record.post_flip_backend!r}"
        )
    else:
        # No-trigger steady-state: backend stays rust.
        assert record.post_flip_backend == "rust", (
            f"HC-AC-2[{welle}]: no-trigger steady-state must keep "
            f"backend=rust; got {record.post_flip_backend!r}"
        )


def assert_henrik_caution_ac_3_pre_cutover_window(
    records: Iterable[HenrikCautionPreCutoverWindowRecord],
    welle: str,
) -> None:
    """HC-AC-3 — Pre-Cutover-Observability-Window 7-day consistency.

    Gates:

    * The window covers exactly
      ``HENRIK_CAUTION_PRE_CUTOVER_WINDOW_DAYS`` (7) days with
      day_index 0..6, no missing/extra days.
    * Every day's ``per_day_consistency_rate`` clears the 0.995 floor.
    * Every day's ``per_day_total_request_count`` > 0 (no empty-day
      observations).
    """
    records_list = list(records)
    assert records_list, (
        f"HC-AC-3[{welle}]: must observe at least one pre-cutover "
        f"window day; got empty set"
    )

    observed_days = sorted({rec.day_index for rec in records_list})
    expected_days = list(range(HENRIK_CAUTION_PRE_CUTOVER_WINDOW_DAYS))
    assert observed_days == expected_days, (
        f"HC-AC-3[{welle}]: pre-cutover-window must observe all "
        f"{HENRIK_CAUTION_PRE_CUTOVER_WINDOW_DAYS} days (0..{HENRIK_CAUTION_PRE_CUTOVER_WINDOW_DAYS - 1}); "
        f"got {observed_days}"
    )

    empty_days: list[int] = []
    below_floor: list[str] = []
    floor = HENRIK_CAUTION_PRE_CUTOVER_CONSISTENCY_PCT_FLOOR
    for rec in records_list:
        if rec.per_day_total_request_count <= 0:
            empty_days.append(rec.day_index)
        if rec.per_day_consistency_rate < floor:
            below_floor.append(
                f"day={rec.day_index} rate={rec.per_day_consistency_rate:.4f}"
            )

    assert not empty_days, (
        f"HC-AC-3[{welle}]: pre-cutover-window observed empty days "
        f"(total_request_count=0): {empty_days}"
    )
    assert not below_floor, (
        f"HC-AC-3[{welle}]: pre-cutover per-day consistency-rate "
        f"below {floor:.4f} floor: {below_floor}"
    )


# ---------------------------------------------------------------------------
# Welle-6+7 Cross-Modul-Drift Acceptance-Kriterien — CMD-AC-6-7-1 ...
# CMD-AC-6-7-4
#
# Anchor: ADR-0066 §Beschluss + Priya CTO-Coordination-Plan v3 (Tag-32
# Mini-Welle Welle-6+7-Extension). Mirrors the Welle-4+5 CMD-AC layer
# shape but specialised for the stateful-loop-paar bidirectional
# contract (subscribe_loop ack-records → recovery_workflow consume;
# recovery_workflow R1..R4 → subscribe_loop Re-subscribe).
# ---------------------------------------------------------------------------


def assert_cross_modul_drift_welle_6_7_ac_1_ack_consume_round_trip(
    records: Iterable[CrossModulDriftWelle6_7AckRoundTripRecord],
    welle_pair_label: str,
) -> None:
    """CMD-AC-6-7-1 — subscribe_loop ack-record → recovery_workflow
    consume round-trip parity + cursor-delta-survival.

    Failure modes captured:

    * ``producer_ack_sha256 != consumer_consumed_reserialized_sha256``
      — ack-bytes mutate on consumer-side consume + re-serialize.
    * ``cursor_delta_round_trip_ok == False`` — cursor-delta field
      dropped or rewritten (Bug-42-adjacent surface).
    """
    records_list = list(records)
    assert records_list, (
        f"CMD-AC-6-7-1[{welle_pair_label}]: must observe at least one "
        f"ack-record round-trip; got empty set"
    )
    drift: list[str] = []
    cursor_breakage: list[str] = []
    for rec in records_list:
        if (
            rec.producer_ack_sha256
            != rec.consumer_consumed_reserialized_sha256
        ):
            drift.append(
                f"{rec.ack_record_id} "
                f"prod={rec.producer_ack_sha256[:16]} "
                f"cons={rec.consumer_consumed_reserialized_sha256[:16]}"
            )
        if not rec.cursor_delta_round_trip_ok:
            cursor_breakage.append(rec.ack_record_id)
    assert not drift, (
        f"CMD-AC-6-7-1[{welle_pair_label}]: ack-record round-trip "
        f"byte-drift at records: {drift}"
    )
    assert not cursor_breakage, (
        f"CMD-AC-6-7-1[{welle_pair_label}]: cursor-delta round-trip "
        f"failure at records: {cursor_breakage}"
    )


def assert_cross_modul_drift_welle_6_7_ac_2_resubscribe_trigger_wire_form(
    records: Iterable[CrossModulDriftWelle6_7ResubscribeRecord],
    welle_pair_label: str,
) -> None:
    """CMD-AC-6-7-2 — R1..R4 Re-subscribe-trigger wire-form parity vs
    python-python-baseline oracle.

    Singleton oracle-set (``python-python-baseline`` only). The
    mid-Doppel-Welle ``python-rust-welle-6-only`` hypothetical
    state is operationally unreachable because the subscribe/
    recovery contract crosses no bisectable schema touchpoint.

    Failure mode: any R1..R4 trigger's Rust-Rust wire-form diverges
    from the python-python-baseline.
    """
    records_list = list(records)
    assert records_list, (
        f"CMD-AC-6-7-2[{welle_pair_label}]: must observe at least one "
        f"R1..R4 Re-subscribe-trigger record; got empty set"
    )
    divergence: list[str] = []
    for rec in records_list:
        for oracle in CROSS_MODUL_DRIFT_WELLE_6_7_WIRE_FORM_ORACLES:
            if not rec.matches_oracle(oracle):
                rust_rust = rec.rust_rust_wire_sha256[:16]
                oracle_hash = rec.oracle_wire_sha256_by_oracle.get(
                    oracle, "<missing>"
                )[:16]
                divergence.append(
                    f"{rec.trigger_id}@{oracle} "
                    f"rust-rust={rust_rust} oracle={oracle_hash}"
                )
    assert not divergence, (
        f"CMD-AC-6-7-2[{welle_pair_label}]: R1..R4 Re-subscribe-"
        f"trigger wire-form divergence vs reference oracles: "
        f"{divergence}"
    )


def assert_cross_modul_drift_welle_6_7_ac_3_per_komponente_consistency(
    record: CrossModulDriftWelle6_7PerKomponenteConsistencyRecord,
    welle_pair_label: str,
) -> None:
    """CMD-AC-6-7-3 — per-Komponente consistency ≥99.5% on Welle-6+7
    joint stress-load (subscribe-event-flood + simultaneous recovery-
    restart-points profile).
    """
    modul_a, modul_b = record.welle_pair
    assert record.total_request_count > 0, (
        f"CMD-AC-6-7-3[{welle_pair_label}]: stress-test must observe "
        f"≥1 request; got total={record.total_request_count}"
    )
    floor = CROSS_MODUL_DRIFT_CONSISTENCY_PCT_FLOOR
    failing: list[str] = []
    if record.modul_a_consistency_rate < floor:
        failing.append(
            f"{modul_a}={record.modul_a_consistency_rate:.4f}"
        )
    if record.modul_b_consistency_rate < floor:
        failing.append(
            f"{modul_b}={record.modul_b_consistency_rate:.4f}"
        )
    assert not failing, (
        f"CMD-AC-6-7-3[{welle_pair_label}]: per-Komponente "
        f"consistency-rate below {floor:.4f} floor: {failing}; "
        f"joint-rate={record.joint_consistency_rate:.4f}"
    )


def assert_cross_modul_drift_welle_6_7_ac_4_atomic_flip_rollback(
    record: CrossModulDriftWelle6_7AtomicFlipRecord,
    welle_pair_label: str,
) -> None:
    """CMD-AC-6-7-4 — Drift-triggered atomic-flip rollback with
    Phase-3c-Ende-delay impact-classification.

    Same gate-shape as CMD-AC-4 plus the Welle-6+7-specific risk
    surface: a ``recovery_workflow`` rollback delays Phase-3c-Ende
    by +1 week (Welle-7 is the closing welle). The delay-classification
    is surfaced in the error message but does not block the gate (a
    correctly-fired recovery_workflow atomic-flip is still a valid
    cutover-recovery, just with operational delay).
    """
    modul_a, modul_b = record.welle_pair
    high_drift = record.high_drift_modul
    assert high_drift in (modul_a, modul_b), (
        f"CMD-AC-6-7-4[{welle_pair_label}]: high_drift_modul "
        f"{high_drift!r} must be a member of the welle-pair "
        f"({modul_a!r}, {modul_b!r})"
    )
    partner = modul_b if high_drift == modul_a else modul_a

    assert (
        record.measured_drift_pct > record.threshold_drift_pct
    ), (
        f"CMD-AC-6-7-4[{welle_pair_label}]: atomic-flip fired "
        f"without a trigger-precondition: measured drift "
        f"{record.measured_drift_pct:.4f}pp ≤ threshold "
        f"{record.threshold_drift_pct:.4f}pp (sub-threshold flips "
        f"rejected as spurious)"
    )
    assert (
        record.threshold_drift_pct == CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD
    ), (
        f"CMD-AC-6-7-4[{welle_pair_label}]: threshold_drift_pct must "
        f"equal the ADR-0066-fixed "
        f"{CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD}pp; got "
        f"{record.threshold_drift_pct}"
    )
    assert record.flip_was_atomic, (
        f"CMD-AC-6-7-4[{welle_pair_label}]: atomic-flip must be a "
        f"single restart-cycle; got non-atomic flip-record"
    )
    high_drift_state = record.post_flip_backend_per_modul.get(high_drift)
    assert high_drift_state == "python", (
        f"CMD-AC-6-7-4[{welle_pair_label}]: high-drift modul "
        f"{high_drift!r} must end on python-backend; got "
        f"{high_drift_state!r}"
    )
    partner_state = record.post_flip_backend_per_modul.get(partner)
    assert partner_state == "rust", (
        f"CMD-AC-6-7-4[{welle_pair_label}]: partner modul {partner!r} "
        f"must stay on rust-Default (atomic-flip discipline); got "
        f"{partner_state!r}"
    )
    assert record.flip_elapsed_seconds <= ROLLBACK_SLA_SECONDS, (
        f"CMD-AC-6-7-4[{welle_pair_label}]: flip elapsed "
        f"{record.flip_elapsed_seconds:.1f}s exceeds "
        f"{ROLLBACK_SLA_SECONDS:.0f}s SLA"
    )
    # Operational-impact classification — surfaces non-blocking
    # delay-weeks in the record for downstream operator-hand triage.
    # recovery_workflow flip → +1 week Phase-3c-Ende delay.
    expected_delay = 1 if high_drift == "recovery_workflow" else 0
    assert record.phase_3c_ende_delay_weeks == expected_delay, (
        f"CMD-AC-6-7-4[{welle_pair_label}]: phase_3c_ende_delay_weeks "
        f"misclassified — high-drift on {high_drift!r} should "
        f"surface delay={expected_delay}; got "
        f"{record.phase_3c_ende_delay_weeks}"
    )
