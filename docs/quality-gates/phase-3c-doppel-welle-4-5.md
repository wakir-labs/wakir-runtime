# Quality-Gate — Phase-3c Doppel-Welle-4+5 Cutover-Path Definition of Done

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Draft — gates the ADR-0066 KW-26 Doppel-Welle decision |
| Phase | 3c, Doppel-Welle KW 26 (`state_backing` + `lifecycle_state_machine`/`fsm`) |
| Source | ADR-0066 §Beschluss Doppel-Welle-Cadence, ADR-0065 §Verifikations-Plan, Selin Welle-3-Smoke (PR #240, A6+A7 Self-Reference-Trap-Mitigation) |
| Date | 2026-05-18 (Tag-38 Amara Auftrag, Continuous-Mode) |

## 0. Scope

This document is the cutover-path-specific Definition of Done for
the Doppel-Welle-4+5 cutover-Mittwoch (KW 26). It supplements
`docs/quality-gates/phase-3c-acceptance-criteria.md` (the welle-für-
welle umbrella) with the **path-decision** axis: under what
preconditions does the Doppel-Welle go parallel vs. sequential, and
what is the post-cutover verification gate for the Welle-3 KW-25
solo wave that immediately precedes it.

Two paths exist for the Welle-4+5 cutover:

1. **Parallel-Path (PAR)** — both moduln flip `WAKIR_STATE_BACKING_
   BACKEND=rust_inmemory` + `WAKIR_FSM_BACKEND=rust` in one
   ENV-Flag-Switch + single `systemctl restart wakir-persona-engine`
   cycle. ADR-0066 §Beschluss target shape.
2. **Sequential-Path (SEQ)** — `WAKIR_STATE_BACKING_BACKEND` flips
   on cutover-Mittwoch KW 26; `WAKIR_FSM_BACKEND` flips on cutover-
   Mittwoch KW 27 only after the intermediate-state holds for at
   least one stability-window. ADR-0066 §Rollback-Strategie back-out
   path if Cross-Modul-Stress-Test fails the pre-cutover gate.

## 1. Decision Matrix — when each path applies

| Condition | Trigger | Path |
|---|---|---|
| Cross-Modul-Stress-Test green for ≥7 days, zero p99-excursions | Doppel-Welle-pre-gate fully green | PAR |
| Cross-Modul-Stress-Test caution (single p99 excursion, no schema drift) | AR consultation required | SEQ |
| Cross-Modul-Stress-Test red (any schema drift) | Hard block on cutover | abort, drift-investigation |
| Welle-3 Post-Cutover audit-trail integrity broken (W3-POST-* failing) | Welle-3 instability invalidates the cross-modul stress-baseline | SEQ |
| Operator-Hand atomic-flip-runbook failed previous drill | Runbook substrate not ready for two-modul flip | SEQ |
| All Doppel-Welle preconditions green, AR-approval present | Default per ADR-0066 §Beschluss | PAR |

Reference: Kai's Welle-5-Operator-Cutover-Runbook (PR #247) tabulates
the operational Operator-Hand decision steps; this Quality-Gate
table is the **CI-side** gate the runbook consumes.

## 2. Definition of Done — Parallel-Path (PAR)

The Doppel-Welle PAR cutover is *Done* when **all** of the following
gates are green on the cutover-Mittwoch KW 26 cutover-Tag:

### 2.1 Pre-cutover gates (from
`tests/acceptance/phase_3c/test_doppel_welle_4_5_e2e.py`)

| Gate | Test | Substrate |
|---|---|---|
| DW-AC-1 | `test_doppel_welle_4_5_dw_ac_1_both_moduln_boot_rust` | engine-boot mock |
| DW-AC-2 | `test_doppel_welle_4_5_dw_ac_2_state_record_to_lifecycle_byte_parity` | cross-modul-schema mock |
| DW-AC-3 | `test_doppel_welle_4_5_dw_ac_3_rollback_state_backing_partner_stays_rust` | single-komponente-rollback mock |
| DW-AC-4 | `test_doppel_welle_4_5_dw_ac_4_cross_modul_stress_test_green` | cross-modul-stress-test mock |
| DW-AC-5 | `test_doppel_welle_4_5_dw_ac_5_backend_decision_audit_two_records` | backend-decision-audit mock |
| CMD-AC-1 | `test_doppel_welle_4_5_cmd_ac_1_deserialization_round_trip_parity` | drift-deserialization mock |
| CMD-AC-2 | `test_doppel_welle_4_5_cmd_ac_2_write_back_wire_form_parity_all_oracles` | drift-write-back mock |
| CMD-AC-3 | `test_doppel_welle_4_5_cmd_ac_3_per_komponente_consistency_green` | per-komponente-consistency mock |
| CMD-AC-4 | `test_doppel_welle_4_5_cmd_ac_4_atomic_flip_high_drift_state_backing` | atomic-flip-rollback mock |

### 2.2 Path-specific gates (from
`tests/phase_3c/test_doppel_welle_acceptance.py`, this Auftrag)

| Gate | Test | Substantive question |
|---|---|---|
| DW-AC-4-5-PAR-1 | `test_dw_ac_4_5_par_both_moduln_rust_in_single_engine_boot` | Does a single engine-boot resolve both moduln to rust? |
| DW-AC-4-5-PAR-2 | `test_dw_ac_4_5_par_env_clobber_between_state_backing_and_fsm_blocks` | Is the env-clobber bug pattern detectable? |
| DW-AC-4-5-SPC | `test_dw_ac_4_5_spc_state_written_pre_readable_post_cutover` | Are pre-cutover state-records byte-identical on post-cutover read-back? |
| DW-AC-4-5-FTI | `test_dw_ac_4_5_fti_fsm_transitions_preserved_over_state_backing_flip` | Is the fsm transition-set preserved across the cutover? |
| DW-AC-4-5-RC-1 | `test_dw_ac_4_5_rc_boot_order_coupling_state_backing_before_fsm` | Does state_backing resolve before fsm in canonical-order? |
| DW-AC-4-5-RC-2 | `test_dw_ac_4_5_rc_shared_cache_leak_blocks` | Is the shared-cache leak pattern detectable? |
| DW-AC-4-5-RC-3 | `test_dw_ac_4_5_rc_fsm_first_boot_order_blocks_under_parallel` | Is an inverted boot-order detectable? |

### 2.3 Pre-cutover operational gates (Operator-Hand, not CI)

* Schema-Migrations-Rollback-Plan drill executed within previous
  7 days, ≤2h SLA met (Welle-4 prerequisite, retained under Doppel-
  Welle per ADR-0066 §Beschluss).
* Cross-Modul-Stress-Test green window ≥7 days, zero schema-drift,
  zero p99-excursions.
* Operator-Hand atomic-flip-runbook for *two-modul-flip* sequence
  drilled at least once on Pilot-VM with green outcome.
* Henrik (Internal Audit) Zone-N pre-cutover sign-off on the audit-
  trail-readiness gate.

### 2.4 Post-cutover gates (cutover-Tag + 5 day window)

* Bridge-Audit-Writer-Konsistenz-Report 5/5 days green for the
  stream-hashes produced by the Rust state_backing + Rust fsm
  combination.
* No S0/S1 issues recorded by Noa (SRE) during the 5-day window.
* Cross-Review-Session (Aisha-moderated) consensus for both Welle-4
  and Welle-5 within the cutover-Freitag.
* V-907 Pin-Validation 100% pass for all persona-definitions across
  the 5-day window.

## 3. Definition of Done — Sequential-Path (SEQ)

The SEQ path is *Done* when both legs complete independently:

### 3.1 Leg 1 — Welle-4 cutover (cutover-Mittwoch KW 26)

* All Welle-4 solo-welle AC-1...AC-5 gates green (from
  `tests/acceptance/phase_3c/test_welle_4_state_backing_e2e.py`).
* Welle-4 Cross-Modul-Drift-to-Welle-5 isolation: fsm stays python.
  Smoke-test: `tests/phase_3c/test_welle_4_cutover_smoke.py::
  test_a7_cross_modul_drift_to_welle_5_fsm_blocks_on_fsm_leak`.
* Intermediate-state stability ≥7 days post Welle-4 cutover with
  zero S0/S1 issues, zero schema-drift, zero p99-excursions
  attributable to the state_backing-rust × fsm-python contract.

### 3.2 Leg 2 — Welle-5 cutover (cutover-Mittwoch KW 27)

* All Welle-5 solo-welle AC-1...AC-5 gates green (from
  `tests/acceptance/phase_3c/test_welle_5_lifecycle_state_machine_
  e2e.py`).
* Welle-5 Cross-Modul-Drift-from-Welle-4 isolation: Welle-5-smoke
  A7 verifies state_backing-rust × fsm-rust contract under solo
  Welle-5 PHASE_POST (Selin's Tag-38 parallel spawn).
* **Terminal-equivalence:** SEQ-terminal state must be byte-
  identical to PAR-terminal state on the BackendDecision contract.
  Gate: `tests/phase_3c/test_doppel_welle_acceptance.py::
  test_dw_ac_4_5_seq_welle_4_first_then_welle_5_intermediate_state
  _holds` covers this property.

## 4. Welle-3 Post-Cutover Verification — prerequisite for either path

ADR-0066 places Welle-3 (`bridge_audit_writer`, KW 25) as the solo
wave immediately preceding the Doppel-Welle-4+5 KW 26. Welle-3 is
the consistency-oracle substrate for **every other welle**, so
Welle-3 cutover instability invalidates the Doppel-Welle-4+5 pre-
cutover Cross-Modul-Stress-Test baseline.

The Welle-3 post-cutover verification gate (from
`tests/phase_3c/test_welle_3_post_cutover_verification.py`,
this Auftrag) must be green before the Doppel-Welle-4+5 cutover-
Mittwoch:

| Gate | Test | Substantive question |
|---|---|---|
| W3-POST-1 (happy) | `test_welle_3_post_1_audit_stream_continuity_post_cutover` | Does the bridge-audit-stream-hash stay byte-stable post-cutover? |
| W3-POST-1 (drift) | `test_welle_3_post_1_stream_drift_blocks` | Is post-cutover stream-drift detectable? |
| W3-POST-2 | `test_welle_3_post_2_self_reference_trap_mitigation_fired` | Did A6+A7 (Selin Tag-36 PR #240) actually fire in the cutover envelope? |
| W3-POST-3 (anchor) | `test_welle_3_post_3_cross_modul_drift_anchor_emitter` | Is anchor_emitter cleanly isolated from bridge_audit_writer's rust flip? |
| W3-POST-3 (diff) | `test_welle_3_post_3_cross_modul_drift_bridge_diff` | Is bridge_diff cleanly isolated from bridge_audit_writer's rust flip? |
| W3-POST-4 | `test_welle_3_post_4_rollback_hairpin_window_audit_trail_intact` | Is the audit-trail readable post-rollback if the cutover is reverted? |

**Hard block on Welle-3 post-cutover failure:** if any W3-POST-*
gate fails in the post-cutover stability window, the Doppel-Welle-
4+5 KW 26 cutover **must back out to sequential path** with an
additional 7-day stability window between Welle-3 stabilisation
and Welle-4 cutover.

## 5. Rollback paths

### 5.1 Single-Komponente rollback (asymmetric)

Per ADR-0066 §Rollback-Strategie + CMD-AC-4: if drift > 0.5pp is
attributable to exactly one of state_backing or fsm, the
Operator-Hand atomic-flip-runbook fires a single-modul rollback
to python; the partner stays on rust.

SLA: ≤600s for the ENV-Flag-Switch portion (DW-AC-3 / CMD-AC-4
threshold).

### 5.2 Both-Komponente rollback (symmetric)

If the drift is in the *contract* between the two moduln (rather
than localised to one), both moduln roll back together. ADR-0066
§Rollback-Strategie default.

SLA: ≤600s for the ENV-Flag-Switch portion + ≤2h for any schema-
migration follow-up (Welle-4 Schema-Migrations-Rollback-Plan).

### 5.3 Hairpin-window audit-trail readability

The Welle-3 W3-POST-4 hairpin-window gate ensures the audit-trail
emitted during a rollback hairpin window remains readable. This
property carries over to the Doppel-Welle cutover-window: any
rollback fired during the Doppel-Welle cutover-day must preserve
the audit-trail emitted during the cutover-window itself.

## 6. CI-side ordering

The Quality-Gate-Aggregator (ADR-0068 ci-aggregator workflow, PR
#244 / Tomás Tag-37) consumes:

1. `tests/phase_3c/test_welle_3_post_cutover_verification.py` —
   prerequisite for Doppel-Welle-4+5 cutover.
2. `tests/phase_3c/test_doppel_welle_acceptance.py` — cutover-path
   gates (this Auftrag).
3. `tests/acceptance/phase_3c/test_doppel_welle_4_5_e2e.py` —
   solo-cutover-DW-AC + CMD-AC gates (PR #199 + PR #221 substrate).

All three must be green on the cutover-Mittwoch CI run; Tomás's
Welle-5-Validation-Workflow (paralleler Tag-38 spawn) wires this
into the ci-aggregator's `phase-3c-doppel-welle-4-5-aggregate` job.

## 7. Zone-N (Henrik Audit) boundary

Henrik (Internal Audit) cross-checks the following via Zone-N
quarterly review:

| Aspect | Amara (QA) Evidence | Henrik (Audit) Cross-check |
|---|---|---|
| Test-pass status of all gates above | Test-Pass-Reports + CI-Aggregator-Envelope | Sample-based review of the envelope contents |
| ADR-0066 compliance | Tests anchored to ADR-0066 §-Beschluss line-items | Confirms gate set matches §Beschluss + §Rollback-Strategie |
| W3-POST-4 audit-trail readability | Hermetic-test substrate proves byte-stable readback | Sample-based read-back of real audit-trail entries on Pilot-VM |
| Doppel-Welle = Sequential terminal-equivalence | SEQ-test asserts BackendDecision-contract equivalence | Confirms ADR-0066 §Beschluss equivalence-claim holds |

Zone-N protocol: Amara + Henrik halten quartalsweisen Boundary-Review
(Aisha-moderiert). For the Doppel-Welle-4+5 cutover specifically, an
ad-hoc Zone-N sign-off is requested ≤24h before the cutover-Mittwoch.

## 8. Cross-spawn coordination

This Quality-Gate doc was authored in parallel with the following
Tag-38 spawns:

* **Selin** — Welle-5-Smoke A7 symmetric-pattern (per-modul anchor
  for the FSM side of the Doppel-Welle contract).
* **Kai** — Welle-5-Operator-Cutover-Runbook PR #247 (Operator-Hand
  decision matrix referenced in §1).
* **Tomás** — Welle-5-Validation-Workflow + ci-aggregator wiring
  (CI gate referenced in §6).
* **Reza** — Bridge-Audit-Diff-Engine Tag-36/37 substrate (the
  rust-side substrate that the bridge_audit_writer + state_backing
  cutover-Mittwochs activate).

Coordinated via Tomás (Engineering-Lead) Zone-M weekly review;
Aisha protokolliert Konsens-Zeitpunkt.

## 9. Vermutungs-Kennzeichnung (P2)

* The decision matrix in §1 is sourced from ADR-0066 §Beschluss +
  §Rollback-Strategie; threshold values (≥7 days, ≤0.5pp) are
  taken from CMD-AC-4 + HC-AC-2 / HC-AC-3 ADR-anchored constants.
* The hard-block rule in §4 ("Welle-3 instability invalidates
  Doppel-Welle baseline") is Amara's interpretation of the ADR-0066
  §Beschluss Cross-Modul-Stress-Test dependency; the AR has not
  explicitly ruled on this dependency-direction. Pending AR
  ratification of this rule via ADR-Folge-Item if the cutover-
  Mittwoch hits the edge case.
* Terminal-equivalence (§3.2) is the substantive claim under-pinning
  the ADR-0066 §Beschluss "Doppel-Welle = Sequential" equivalence;
  if a post-cutover Operator-Hand drill surfaces a difference
  (e.g. timing-window-dependent state-record divergence), the
  equivalence-claim must be reopened with the AR.

— Amara
