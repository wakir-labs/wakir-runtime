# Quality-Gate — Phase-3c Cutover-Day-E2E-Drill Definition-of-Done

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Draft — pending Phase-3c-Welle-Marathon execution (ADR-0066 §Beschluss four-Wochen-Cadence KW 24 -> KW 27) |
| Phase | 3 (executing): per-day Cutover-Mittwoch walkthrough Definition-of-Done |
| Source | Tag-41 Amara Auftrag (Continuous-Mode, 2026-05-18); ADR-0066 §Beschluss + §Wochen-Plan; ADR-0065 §Verifikations-Plan + §Welle-Ende-Acceptance; ADR-0058 §Phase-3 + §Nachtrag (live-VM-lane) |
| Date | 2026-05-18 (creation, Tag-41 cutover-day-drill spawn) |
| Test-File | `tests/phase_3c/test_cutover_day_e2e_drill.py` |
| Companion (aggregate) | `tests/phase_3c/test_phase_3_final_regression.py` (Tag-40, marker state-machine oracle) |
| Companion (live) | `scripts/phase-3c/live-vm-cutover-drill.sh` (Tag-40, operator-hand-territory) |

## 0. Cutover-Day contract

This document is the **per-day** Definition-of-Done for one cutover-
Mittwoch event in the Phase-3c marathon (ADR-0066 §Wochen-Plan,
KW-24 -> KW-27). Where the Tag-40 final-regression-suite
(`test_phase_3_final_regression.py`) pins the *aggregate* Phase-3-
COMPLETE marker contract across the seven wellen, this document pins
the *per-Welle Cutover-Mittwoch* walkthrough: the seven-step real-day
sequence operators execute on cutover-day.

The two suites are complementary:

* **Tag-40 final-regression** — given seven sign-off-records, does the
  Phase-3-COMPLETE marker fire? (marker state-machine logic)
* **Tag-41 cutover-day-drill** — does the seven-step Cutover-Mittwoch
  workflow produce a correctly-shaped sign-off-record? (per-day
  workflow oracle)

Together, the two suites form the *atomic* QA-evidence layer the
Tomás Tag-40 Phase-3-COMPLETE-Marker-Workflow consumes.

## 1. The seven-step Cutover-Mittwoch sequence

Each Cutover-Mittwoch consists of exactly seven steps, executed in
order. The drill simulator enforces this order; the live-VM-lane
operator runbook (Kai Tag-41) mirrors it step-for-step.

| Step | Name | Phase Marker | Purpose |
|------|------|--------------|---------|
| 1 | `step_1_pre_conditions_verify` | PHASE_PRE | Consume Kai runbook §1 pre-conditions checklist (container-image-tag, env-var settable, previous welle signed off). |
| 2 | `step_2_pre_flight_smoke` | PHASE_PRE | Invoke the welle's per-Welle smoke in PHASE_PRE mode. Verifies focus env-var resolves to `python` baseline. |
| 3 | `step_3_cutover_engine_reboot` | PHASE_POST | Simulate the engine-reboot + ENV-flip. Verifies focus env-var carries a rust-flavoured value (`rust` or `rust_inmemory` for Welle-4). |
| 4 | `step_4_soak_window` | PHASE_SOAK | Advance mock-time by `SOAK_WINDOW_MINUTES[welle]` (15 min for Welle-1+2, 30 min for Welle-3..7). |
| 5 | `step_5_post_cutover_verify` | PHASE_POST | Re-run smoke + parse BackendDecision-stream. Detect cross-modul drift (A7) by comparing non-focus latencies. |
| 6 | `step_6_sign_off` | PHASE_SIGNOFF | Emit a `HenrikAuditSignOffRecord` if all gates green. JCS-canonical for audit-trail. |
| 7 | `step_7_rollback_path_verify` | PHASE_ROLLBACK | Run smoke in PHASE_ROLLBACK mode. Verifies focus env-var is unset (python-default restored). |

The seven phase markers are: `PHASE_PRE`, `PHASE_POST`, `PHASE_SOAK`,
`PHASE_SIGNOFF`, `PHASE_ROLLBACK`. Every step record carries one of
the five markers, plus a verdict in `{"green", "caution", "blocker"}`.

## 2. Cross-Welle coordination (KW-24 -> KW-27)

ADR-0066 §Wochen-Plan four-Wochen-Doppel-Welle-Cadence:

| KW | Pattern | Wellen | Cutover ISO | Sign-Off ISO |
|----|---------|--------|-------------|--------------|
| 24 | Doppel-Welle | 1 (`v907_verify`) + 2 (`svid_workload_identity`) | 2026-06-10T09:00:00+02:00 | 2026-06-12T17:00:00+02:00 |
| 25 | Solo (Henrik-Caution) | 3 (`bridge_audit_writer`) | 2026-06-17T09:00:00+02:00 | 2026-06-19T17:00:00+02:00 |
| 26 | Doppel-Welle (symmetric A7 drift expectation) | 4 (`state_backing`) + 5 (`lifecycle_state_machine`) | 2026-06-24T09:00:00+02:00 | 2026-06-26T17:00:00+02:00 |
| 27 | Doppel-Welle (Marathon-Schluss-Acceptance) | 6 (`subscribe_loop`) + 7 (`recovery_workflow`) | 2026-07-01T09:00:00+02:00 | 2026-07-03T17:00:00+02:00 |

Cross-KW quiet-window invariants:

* Each KW's sign-off ISO must strictly precede the next KW's cutover
  ISO (allows for Welle-Ende-Acceptance review between cutovers).
* Each Doppel-Welle pair (DW-1+2, DW-4+5, DW-6+7) shares the same
  cutover ISO and the same sign-off ISO.
* Solo-Welle-3 is the only Solo-Welle in the cadence; if it rolls
  back, KW-26 and KW-27 wellen cannot start (cascade-block).

## 3. Phase-3-Marathon-Schluss-Acceptance

The Phase-3-COMPLETE marker fires **only when**:

1. All seven welle drills produced a sign-off record.
2. All seven sign-offs are `status="signed-off"` with `drill_verdict`
   in `{"green", "caution"}` (single-or-many `"caution"` aggregates to
   `"caution"` verdict, which does not block the marker; only
   `"blocker"` cancels).
3. Every sign-off carries `henrik_audit_compliance=True` (Henrik-
   Ratifikation).
4. The 7/7-reached-with-Henrik-Ratifikation state implies the AR-
   hand stamp (in the live process the AR explicitly stamps;
   the drill mocks this gate as a function of 7/7 + Henrik).

When the marker fires, its payload carries:

| Field | Type | Meaning |
|-------|------|---------|
| `phase_3_complete` | bool | `True` (marker fires only when True) |
| `signoff_count` | int | 7 (must equal 7 for marker to fire) |
| `henrik_ratifikation` | bool | aggregate Henrik-Audit-Compliance across all 7 |
| `ar_hand_stamp` | bool | AR-hand stamp marker (mocked as `henrik_ratifikation && 7/7`) |
| `welle_focus_list` | sorted str[] | the seven modul names (`v907_verify`, ..., `recovery_workflow`) |
| `cutover_iso_range` | [iso, iso] | KW-24 cutover ISO to KW-27 cutover ISO |
| `signoff_iso_range` | [iso, iso] | KW-24 sign-off ISO to KW-27 sign-off ISO |
| `drill_aggregate_verdict` | "green" \| "caution" | aggregate verdict over the seven sign-offs |
| `schema` | str | `wakir.phase_3.complete_marker/1` |

## 4. Henrik-Audit-Sign-Off JSON shape (test-side oracle)

Each per-day sign-off record is the unit of QA-evidence Henrik (Zone-N)
audit-samples. The shape (test-side oracle, mirrors ADR-0065 §AC-5 +
Henrik Tag-40 Cutover-Day-Audit-Spec):

| Field | Type | Meaning |
|-------|------|---------|
| `schema` | str | `wakir.phase_3c.cutover_day_sign_off/1` |
| `welle_number` | int (1..7) | the welle ordinal |
| `welle_focus` | str | ADR-0065 long-form modul name (e.g. `bridge_audit_writer`) |
| `welle_env_var` | str | ADR-0065 env-var spelling (e.g. `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND`) |
| `kw` | int (24..27) | Kalenderwoche of the cutover |
| `cutover_iso` | iso str | Mittwoch 09:00 CEST of the KW |
| `signoff_iso` | iso str | Freitag 17:00 CEST of the KW |
| `status` | "signed-off" \| "rolled-back" | sign-off status |
| `ac_1_5_green` | bool | AC-1..AC-5 acceptance (ADR-0065) |
| `ac_4_consensus_personas` | sorted str[] | 6-persona Cross-Review-Session consent |
| `henrik_audit_compliance` | bool | Henrik-Audit-Compliance gate |
| `audit_trail_anchor` | str (sha256-hex) | SHA-256 of the day's audit-trail (placeholder in drill) |
| `drill_verdict` | "green" \| "caution" \| "blocker" | aggregate per-day drill verdict |

The shape is **JCS-canonical**: keys are lexicographically sorted, no
whitespace, ASCII-only JSON. The `to_jcs_bytes()` helper produces
stable byte-shape across builds — required for audit-trail anchoring.

## 5. Test-suite scope (51 tests)

The test-suite covers nine drill-axes. Each axis carries the minimum-
test-count needed for substantive coverage; collectively they satisfy
the Auftrag-Tag-41 minimum walkthrough coverage.

### 5.1 PCD — Per-Welle Cutover-Day Walkthrough (19 tests)

Seven parametrised per-welle full-sequence tests + seven explicit
named per-welle tests + five aggregate per-step evidence tests:

1. `test_pcd_drill_runs_full_seven_step_sequence_for_welle[welle_1..welle_7]` (7 parametrised)
2. `test_pcd_drill_runs_full_seven_step_sequence_for_welle_1..7` (7 explicit)
3. `test_pcd_each_step_emits_evidence_record_with_phase_marker`
4. `test_pcd_soak_window_duration_matches_welle_risk_class`
5. `test_pcd_pre_conditions_check_consumes_kai_runbook_section_1`
6. `test_pcd_post_cutover_verify_parses_backend_decision_stream`
7. `test_pcd_sign_off_emits_henrik_audit_sign_off_json_record`

PCD pins the per-Welle walkthrough: each of the seven wellen runs all
seven steps in order, each step emits a phase-marked evidence record,
the soak-window honours the welle's risk-class, the pre-conditions
gate consumes Kai's runbook §1, the post-cutover-verify parses the
BackendDecision-stream, and the sign-off emits a JCS-canonical record.

### 5.2 COORD — Cross-Welle Coordination Drill (8 tests)

8. `test_coord_kw_24_dw_1_2_runs_in_parallel`
9. `test_coord_kw_25_w_3_runs_solo_with_henrik_sign_off_gate`
10. `test_coord_kw_26_dw_4_5_runs_in_parallel_with_symmetric_a7_drift`
11. `test_coord_kw_27_dw_6_7_runs_in_parallel_with_marathon_schluss_acceptance`
12. `test_coord_parallel_partners_share_cutover_iso_and_signoff_iso`
13. `test_coord_solo_welle_3_signoff_gate_blocks_later_kws`
14. `test_coord_cross_kw_quiet_window_separates_kw_n_signoff_from_kw_n_plus_1`
15. `test_coord_no_two_kws_overlap_in_drill_schedule`

COORD pins the four-Wochen-Cadence: doppel-welle partners share
cutover + sign-off ISO; Welle-3 is the only solo welle and its
sign-off gates KW-26 + KW-27; cross-KW windows are disjoint and
strictly ordered.

### 5.3 SOAK — Soak-Window timing + invariants (5 tests)

16. `test_soak_low_risk_welle_uses_15_min_soak_window`
17. `test_soak_high_risk_welle_uses_30_min_soak_window`
18. `test_soak_mock_time_advances_strictly_during_soak_window`
19. `test_soak_no_step_can_advance_before_soak_window_elapses`
20. `test_soak_post_cutover_verify_runs_strictly_after_soak`

SOAK pins the soak-window timing: low/lowest risk wellen use 15 min,
moderate/elevated/high/highest risk wellen use 30 min, mock-time
strictly advances, step-5 runs strictly after the soak ends.

### 5.4 ROLLBACK — Rollback-Path verification (4 tests)

21. `test_rollback_trigger_fires_when_post_cutover_verify_caution`
22. `test_rollback_trigger_fires_when_a7_drift_exceeds_threshold`
23. `test_rollback_restores_python_default_in_quadlet_env`
24. `test_rollback_emits_audit_record_with_rollback_status`

ROLLBACK pins the rollback-path: A7 cross-modul drift trips the
caution/blocker verdict, the rollback phase restores the python
default (focus env-var unset), and pre-conditions-failure short-
circuits the drill to a blocker verdict.

### 5.5 SIGNOFF — Mock Henrik-Audit-Sign-Off JSON (4 tests)

25. `test_signoff_record_has_henrik_audit_compliance_marker`
26. `test_signoff_record_includes_six_persona_cross_review_consent`
27. `test_signoff_record_includes_welle_focus_and_env_var`
28. `test_signoff_record_is_json_serialisable_for_audit_trail`

SIGNOFF pins the sign-off record shape: Henrik-Audit-Compliance
marker present, 6-persona AC-4 consensus, welle_focus + welle_env_var
match the slot's modul + env-var, JCS-canonical JSON round-trip.

### 5.6 MARATHON — Phase-3-Marathon-Schluss-Acceptance (3 tests)

29. `test_marathon_all_seven_signoffs_plus_henrik_plus_ar_sets_complete_marker`
30. `test_marathon_six_of_seven_signoffs_does_not_set_complete_marker`
31. `test_marathon_complete_marker_payload_carries_full_evidence`

MARATHON pins the Phase-3-COMPLETE marker contract: 7/7 sign-offs +
Henrik-Ratifikation + AR-stamp fire the marker; 6/7 does not; the
marker payload carries the full per-Welle evidence aggregate.

### 5.7 NEGATIVE — Cascade-block + drift-block + partial-sign-off (4 tests)

32. `test_negative_welle_3_rollback_blocks_welle_4_through_7`
33. `test_negative_welle_4_a7_drift_above_zero_blocks_welle_4_and_5`
34. `test_negative_six_of_seven_sign_off_does_not_set_complete_marker`
35. `test_negative_henrik_ratification_missing_blocks_complete_marker`

NEGATIVE pins the failure-modes: Welle-3 rollback cascades to
Welle-4..7; Welle-4 A7-drift above zero produces caution/blocker;
omitting any welle blocks the marker; missing Henrik compliance
blocks the marker.

### 5.8 MOCK-TIME — Time-Forward simulator invariants (2 tests)

36. `test_mock_time_advances_monotonically_through_seven_step_sequence`
37. `test_mock_time_compression_factor_preserves_event_ordering`

MOCK-TIME pins the mock-clock invariants: step-record timestamps are
monotonically non-decreasing, the compression factor preserves event
ordering between the seven steps.

### 5.9 AUDIT-MOCK — Henrik-Audit-Sign-Off JSON shape (2 tests)

38. `test_audit_mock_signoff_json_has_required_fields_for_zone_n_review`
39. `test_audit_mock_signoff_json_is_canonical_per_jcs_ordering`

AUDIT-MOCK pins the JCS-canonical sign-off-shape: every required
field for Zone-N review is present, keys are lexicographically
sorted, two independent builds of the same slot produce identical
bytes.

## 6. Hermeticity

stdlib-only. No podman, no live NATS, no live Bridge-Audit-Writer
I/O, no OTS-calendar contact, **no real wall-clock**. The drill uses
a `MockTimeProvider` that produces deterministic ISO timestamps so
the soak-window invariants are reproducible across CI runs. The
seven welle smoke-modules are loaded via `importlib` from their
hyphenated `scripts/phase-3c/` paths — same loader pattern as the
Tag-40 regression-suite — and each drill-run uses per-welle stub-
resolvers built from each smoke's own `ENGINE_BOOT_COMPONENTS`
inventory.

The drill simulator is the **QA-side oracle** the operator's live
drill (`scripts/phase-3c/live-vm-cutover-drill.sh`, ADR-0060 +
ADR-0058 §Nachtrag) compares against. The live-VM-lane remains
Operator-Hand responsibility; this file does not substitute for it.

## 7. Zone-N coordination (Henrik Internal Audit)

Henrik Zone-N-Quarterly-Review (Aisha-moderiert) consumes the
SIGNOFF + AUDIT-MOCK + ROLLBACK axes as complementary inputs to his
Cutover-Day-Audit-Spec sample. Per Amara/Henrik Zone-N-Boundary-
Discipline (ADR-0044 §Zone-N): QA-evidence here is **complementary**
to Henrik's audit-sample, **not substitutive**. The per-day sign-off-
records themselves are signed by the live audit process; this suite
verifies the *shape* the live process must produce.

## 8. CI surface

The test-file is auto-collected by pytest (`testpaths=["tests"]` in
`pyproject.toml`). It runs as part of the standard pytest job +
contributes to the Phase-3-final-regression-acceptance check-set.

No new workflow is added; existing pytest CI lane carries the suite.

## 9. Cross-spawn dependencies (Tag-41)

| Spawn | Dependency | Status |
|-------|------------|--------|
| Reza Tag-41 Phase-3a-final + cross-Welle-protocol-anchor | BackendDecision-Stream parse shape | wired through `parse_backend_decision_stream()` |
| Selin Tag-41 Welle-Schluss-Smoke + lifecycle-final | per-welle smoke substrate | consumed via importlib loader |
| Kai Tag-41 Cutover-Day Pre-Conditions Runbook §1 | Pre-Conditions checklist | mocked in step-1 evidence (Kai-runbook-§1-consumed flag) |
| Tomás Tag-41 Phase-3-Aggregator-Workflow | sign-off-record consumer | mock shape mirrors workflow expectations |
| Noa Tag-41 Soak-Window Monitoring Dashboards | alert-quiet-window oracle | mocked in step-4 evidence |
| Henrik Tag-41 Cutover-Day-Audit-Spec | Zone-N audit-sample-spec | shape mirrored in `HenrikAuditSignOffRecord` |

## 10. Acceptance criteria for this Quality-Gate

This Quality-Gate is GREEN when:

* All 51 tests in `tests/phase_3c/test_cutover_day_e2e_drill.py` pass
  hermetically (no podman, no network, no real clock).
* The drill simulator produces a Phase-3-COMPLETE marker payload that
  matches the shape declared in §3 of this document.
* The Henrik-Audit-Sign-Off JSON produced for each welle matches the
  shape declared in §4 of this document.
* The cross-KW quiet-window invariants in §2 hold.
* The Tag-40 Phase-3-final-regression-suite continues to pass (no
  regression introduced).

This Quality-Gate is BLOCKER when:

* Any of the 51 tests fail in CI.
* The Phase-3-COMPLETE marker payload schema drifts from §3.
* The Henrik-Audit-Sign-Off JSON shape drifts from §4.
* The Tag-40 final-regression-suite regresses.

— Amara
