# Quality-Gate — Phase-3c Doppel-Welle-6+7 Cutover-Path Definition of Done

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Draft — gates the ADR-0066 KW-27 Doppel-Welle decision + Phase-3-Marathon-Schluss-Acceptance |
| Phase | 3c, Doppel-Welle KW 27 (`subscribe_loop` + `recovery_workflow` / `recovery`) |
| Source | ADR-0066 §Beschluss Doppel-Welle-Cadence, ADR-0065 §Welle-Ende-Acceptance §WE-1..WE-4, Selin Welle-6+7-Smokes (Tag-39 paralleler spawn), Kai Welle-6+7-Runbooks (Tag-39 paralleler spawn) |
| Date | 2026-05-18 (Tag-39 Amara Auftrag, Continuous-Mode) |

## 0. Scope

This document is the cutover-path-specific Definition of Done for the
Doppel-Welle-6+7 cutover-Mittwoch (KW 27). It supplements
`docs/quality-gates/phase-3c-acceptance-criteria.md` (the welle-für-
welle umbrella) and `docs/quality-gates/phase-3c-doppel-welle-4-5.md`
(the KW-26 Doppel-Welle path-decision) with the **terminal-closure**
axis: under what preconditions does the Doppel-Welle-6+7 go parallel
vs. sequential, and what is the Phase-3-Marathon-Schluss-Acceptance
gate that fires when Welle-7 signs off.

Two paths exist for the Welle-6+7 cutover:

1. **Parallel-Path (PAR)** — both moduln flip `WAKIR_SUBSCRIBE_LOOP_
   BACKEND=rust` + `WAKIR_RECOVERY_BACKEND=rust` in one
   ENV-Flag-Switch + single `systemctl restart wakir-persona-engine`
   cycle. ADR-0066 §Beschluss target shape for KW 27.
2. **Sequential-Path (SEQ)** — `WAKIR_SUBSCRIBE_LOOP_BACKEND` flips
   on cutover-Mittwoch KW 27 part A; `WAKIR_RECOVERY_BACKEND` flips
   on cutover-Mittwoch KW 27 part B only after the intermediate-state
   holds for at least one stability-window. ADR-0066 §Rollback-
   Strategie back-out path if Cross-Modul-Stress-Test fails the pre-
   cutover gate.

KW 27 is the **terminal** cutover-week of Phase-3c — Welle-7 sign-off
closes Phase-3c per ADR-0065 §Welle-Ende-Acceptance and triggers the
Phase-3-Marathon-Schluss-Acceptance. The closure-axis of this DoD is
distinct from the Welle-4+5 path-decision axis: Welle-6+7 must satisfy
both the path-decision gates *and* the marathon-closure gates.

## 1. Decision Matrix — when each path applies

| Condition | Trigger | Path |
|---|---|---|
| Cross-Modul-Stress-Test green for ≥7 days, zero p99-excursions | Doppel-Welle-pre-gate fully green | PAR |
| Cross-Modul-Stress-Test caution (single p99 excursion, no schema drift) | AR consultation required | SEQ |
| Cross-Modul-Stress-Test red (any schema drift) | Hard block on cutover | abort, drift-investigation |
| Welle-4+5 KW-26-terminal audit-trail integrity broken | Prior Doppel-Welle instability invalidates the cross-modul stress-baseline | SEQ |
| R1-capability-token rotation-race detected in pre-cutover drill | Token-cache substrate not ready for two-modul flip | SEQ + token-cache pre-warm |
| NATS-subject-drift detected in pre-cutover smoke | Subject-prefix substrate not ready for parallel cutover | abort |
| Operator-Hand atomic-flip-runbook failed previous drill | Runbook substrate not ready for two-modul flip | SEQ |
| All Doppel-Welle preconditions green, AR-approval present | Default per ADR-0066 §Beschluss | PAR |

Reference: Kai's Welle-6+7-Operator-Cutover-Runbook (Tag-39 paralleler
spawn) tabulates the operational Operator-Hand decision steps; this
Quality-Gate table is the **CI-side** gate the runbook consumes.

## 2. Definition of Done — Parallel-Path (PAR)

The Doppel-Welle PAR cutover is *Done* when **all** of the following
gates are green on the cutover-Mittwoch KW 27 cutover-Tag:

### 2.1 Pre-cutover gates (from
`tests/acceptance/phase_3c/test_doppel_welle_6_7_e2e.py`)

| Gate | Test | Substrate |
|---|---|---|
| DW-AC-1 | `test_doppel_welle_6_7_dw_ac_1_both_moduln_boot_rust` | engine-boot mock |
| DW-AC-2 | `test_doppel_welle_6_7_dw_ac_2_subscribe_to_recovery_byte_parity` | cross-modul-schema mock |
| DW-AC-3 | `test_doppel_welle_6_7_dw_ac_3_rollback_subscribe_loop_partner_stays_rust` | single-komponente-rollback mock |
| DW-AC-4 | `test_doppel_welle_6_7_dw_ac_4_cross_modul_stress_test_green` | cross-modul-stress-test mock |
| DW-AC-5 | `test_doppel_welle_6_7_dw_ac_5_backend_decision_audit_two_records` | backend-decision-audit mock |
| CMD-AC-1 | `test_doppel_welle_6_7_cmd_ac_1_ack_consume_round_trip_parity` | ack-consume-round-trip mock |
| CMD-AC-2 | `test_doppel_welle_6_7_cmd_ac_2_resubscribe_trigger_wire_form` | resubscribe-trigger-wire-form mock |
| CMD-AC-3 | `test_doppel_welle_6_7_cmd_ac_3_per_komponente_consistency_green` | per-komponente-consistency mock |
| CMD-AC-4 | `test_doppel_welle_6_7_cmd_ac_4_atomic_flip_high_drift_subscribe_loop` | atomic-flip-rollback mock |

### 2.2 Path-specific gates (from
`tests/phase_3c/test_doppel_welle_6_7_acceptance.py`, this Auftrag)

| Gate | Test | Substantive question |
|---|---|---|
| DW-AC-6-7-PAR-1 | `test_dw_ac_6_7_par_both_moduln_rust_in_single_engine_boot` | Does a single engine-boot resolve both moduln to rust, with KW-26-terminal rust state preserved? |
| DW-AC-6-7-PAR-2 | `test_dw_ac_6_7_par_nats_subject_drift_between_subscribe_loop_and_recovery_blocks` | Is the NATS-subject-drift bug pattern (recovery resolver confuses pair env-vars) detectable? |
| DW-AC-6-7-SEQ | `test_dw_ac_6_7_seq_welle_6_first_then_welle_7_terminal_equivalence` | Does sequential-W7-terminal == parallel-PAR-terminal on the BackendDecision contract? |
| DW-AC-6-7-SLDC | `test_dw_ac_6_7_sldc_subscription_cursor_continuous_over_cutover` | Are pre-cutover subscription-cursors byte-identical on post-cutover read-back + monotonic-advance? |
| DW-AC-6-7-RDC | `test_dw_ac_6_7_rdc_recovery_restart_point_holds_over_subscribe_loop_flip` | Is the recovery restart-point-set preserved across the subscribe_loop cutover? |
| DW-AC-6-7-RC | `test_dw_ac_6_7_rc_r1_capability_token_rotation_race_blocks` | Is the R1-capability-token rotation-race bug pattern detectable + order-independent? |
| DW-AC-6-7-P3M-1 | `test_dw_ac_6_7_p3m_all_seven_moduln_rust_after_doppel_welle_6_7` | After Doppel-Welle-6+7, is every engine-inventory modul on rust (Phase-3-COMPLETE closure)? |
| DW-AC-6-7-P3M-2 | `test_dw_ac_6_7_p3m_welle_7_sign_off_triggers_phase_3_complete_marker` | Does Welle-7-Sign-Off fire the Phase-3-COMPLETE marker exactly once on both PAR and SEQ-W7-terminal paths, and never on PRE / SEQ-W6 / ROLLBACK? |

### 2.3 Pre-cutover operational gates (Operator-Hand, not CI)

* Schema-Migrations-Rollback-Plan drill executed within previous
  7 days, ≤2h SLA met.
* Cross-Modul-Stress-Test green window ≥7 days, zero schema-drift,
  zero p99-excursions.
* Operator-Hand atomic-flip-runbook for *two-modul-flip* sequence
  (subscribe_loop + recovery) drilled at least once on Pilot-VM
  with green outcome.
* R1-capability-token pre-warm executed in previous 24h
  (rotation-race substrate ready).
* Henrik (Internal Audit) Zone-N pre-cutover sign-off on the audit-
  trail-readiness gate + Phase-3-Marathon-Schluss-Acceptance
  readiness gate.

### 2.4 Post-cutover gates (cutover-Tag + 5 day window)

* Bridge-Audit-Writer-Konsistenz-Report 5/5 days green for the
  stream-hashes produced by the Rust subscribe_loop + Rust recovery
  combination.
* No S0/S1 issues recorded by Noa (SRE) during the 5-day window.
* Cross-Review-Session (Aisha-moderated) consensus for both Welle-6
  and Welle-7 within the cutover-Freitag.
* Welle-Ende-Acceptance WE-1..WE-4 fully green (telescoped into the
  same cutover-week per ADR-0065 §Welle-Ende-Acceptance).
* Phase-3-COMPLETE marker recorded in audit-trail with timestamp
  matching the cutover-Tag boot envelope.

## 3. Definition of Done — Sequential-Path (SEQ)

The Doppel-Welle SEQ cutover is *Done* when **all** of the following
gates are green:

### 3.1 Pre-cutover gates (Stage 1 — Welle-6 only)

Same as §2.1, plus the SEQ-specific path-gate
`test_dw_ac_6_7_seq_welle_6_first_then_welle_7_terminal_equivalence`
which verifies the intermediate-state (subscribe_loop=rust ×
recovery=python) holds cross-modul isolation.

### 3.2 Stability-window gates (Stage 1 → Stage 2 transition)

* ≥48 hours of green Bridge-Audit-Writer-Konsistenz-Reports under the
  intermediate-state (subscribe_loop=rust, recovery=python).
* Zero S0/S1 issues during the stability-window.
* No drift in recovery's restart-point-set vs. the KW-26-terminal
  baseline (DW-AC-6-7-RDC pinned).

### 3.3 Stage 2 — Welle-7 flip + closure

Same as §2.2 DW-AC-6-7-SEQ + §2.4 post-cutover gates. The terminal-
equivalence assertion verifies SEQ-W7-terminal == PAR-terminal on the
BackendDecision contract — so §2.4 closure gates apply uniformly.

## 4. Phase-3-Marathon-Schluss-Acceptance

This is the **terminal** gate of Phase-3c. It is satisfied when:

1. **All 11 engine-inventory moduln report rust** at the KW-27 cutover-
   Tag boot. The set: `v907_verify`, `svid_workload_identity`,
   `bridge_diff`, `anchor_emitter`, `state_backing` (`rust_inmemory`),
   `fsm`, `subscribe_loop`, `recovery`, `federation_resolver`,
   `bridge_audit_writer`, `bridge_audit_diff_engine`.
2. **The Phase-3-COMPLETE marker is emitted** exactly once on the
   cutover-Tag boot. The marker identifier:
   `PHASE_3_COMPLETE_VIA_DOPPEL_WELLE_6_7`.
3. **The marker is recorded in the audit-trail** for Henrik (Internal
   Audit) Zone-N quarterly review with a verifiable timestamp.
4. **No regression on KW-26-terminal moduln** — the prior 9 cutover-
   wave moduln retain their KW-26-terminal rust state through the
   cutover-Tag boot.
5. **Welle-Ende-Acceptance WE-1..WE-4 fully green** (telescoped per
   ADR-0065 §Welle-Ende-Acceptance).

### 4.1 Marathon-Schluss CI Gate

The test `test_dw_ac_6_7_p3m_all_seven_moduln_rust_after_doppel_welle_
6_7` is the CI-side closure-gate. The test
`test_dw_ac_6_7_p3m_welle_7_sign_off_triggers_phase_3_complete_marker`
verifies the marker semantics on **every** path:

* PAR boot → marker fires once.
* SEQ-W7-terminal boot → marker fires once (path-agnostic closure).
* SEQ-W6-intermediate boot → marker does **not** fire (recovery still
  python).
* PRE / ROLLBACK boot → marker does **not** fire.

### 4.2 Marathon-Schluss Audit-Trail Anchor

Henrik (Internal Audit) Zone-N quarterly review consumes the
Phase-3-COMPLETE marker as the **definitive** Phase-3c-closure-
timestamp anchor. The marker is the substrate-level proof that
Welle-7 signed off and the entire Persona-Engine is on rust-default.

The audit-trail Anchor includes:

* Boot envelope UUID at cutover-Tag boot.
* The 11 BackendDecision records (every modul = rust).
* The Phase-3-COMPLETE marker identifier + timestamp.
* The cutover-path (PAR or SEQ-W7-terminal) — distinguishable via
  the boot history but not via the marker itself (path-agnostic).

This Anchor is the **Phase-3c-Ende** that ADR-0066 §Beschluss
specifies as ~2026-06-21 (KW 27 Freitag).

## 5. Rollback-Strategie

Rollback for KW-27 has stronger constraints than KW-26 because it is
the terminal cutover-week. Two distinct rollback variants:

### 5.1 Partial-Rollback — single-modul under PAR

A single-modul rollback (subscribe_loop OR recovery alone reverts to
python) is supported via the DW-AC-3 asymmetric-rollback gate. The
partner modul stays on rust. The Phase-3-COMPLETE marker is **NOT**
emitted on the partial-rollback boot (one modul is python again).

### 5.2 Full-Rollback — both moduln revert under PAR

Full-Rollback flips both env-vars back to absent/python. The engine
reads python-default for the pair. This is the
`PHASE_DW_ROLLBACK` test phase — the Phase-3-COMPLETE marker is
explicitly **NOT** emitted under this phase (per test `test_dw_ac_6_
7_p3m_welle_7_sign_off_triggers_phase_3_complete_marker`).

### 5.3 Roll-forward after partial-rollback

If a partial-rollback fires post-cutover (e.g. subscribe_loop reverts
to python, recovery stays on rust), the cutover-runbook may roll-
forward the rolled-back modul on a subsequent boot once the
underlying issue is resolved. The Phase-3-COMPLETE marker fires on
the roll-forward boot — the marker is **path-and-time-agnostic**, it
fires whenever both moduln are observed on rust on the same boot.

## 6. Zone-N Boundary — QA × Audit

Henrik (Internal Audit) cross-checks **per the regular Zone-N
quarterly review**:

* Phase-3-COMPLETE marker recorded in audit-trail with a verifiable
  timestamp ≥ cutover-Mittwoch KW 27.
* No drift between QA-CI-result and Audit-Trail-Read on the BackendDecision
  inventory at cutover-Tag boot.
* The Welle-Ende-Acceptance WE-1..WE-4 telescoped closure-evidence is
  internally consistent (Welle-7 sign-off and Phase-3-COMPLETE marker
  reference the same boot envelope UUID).
* The cutover-path attribution (PAR or SEQ-W7-terminal) is recorded
  in the audit-trail for ADR-0066 §Beschluss compliance verification.

Henrik does **not** re-run the CI tests. The tests are QA's substrate
authority; Henrik's substrate is the audit-trail itself.

## 7. Cross-Spawn-Konsistenz

* **Selin (Persona-Engine, Tag-39):** Welle-6+7-Smokes per-modul. The
  per-modul cross-modul-drift contract (Welle-6-side asserts
  recovery stays python during Welle-6-solo PHASE_POST; Welle-7-side
  asserts subscribe_loop stays rust during Welle-7-solo PHASE_POST)
  mirrors the A7 symmetric-pattern from Selin Tag-38 Welle-5-Smoke.
* **Kai (SRE, Tag-39):** Welle-6+7-Operator-Cutover-Runbooks. The
  decision-matrix in §1 is the runbook's CI-side reference; the
  runbook's operator-hand reference is the inverse (decision steps
  for operator vs. decision matrix for CI).
* **Tomás (Engineering-Lead, Tag-39):** Welle-6+7-Validation-Workflows
  add a `ci-aggregator-welle-6-7` job that consumes the §2.2 test
  results plus the §3.1 / §3.3 sequential variants. The aggregator
  emits a single doppel-welle-6-7 status to the branch-protection
  required-status-checks.
* **Reza (Wirelang, Tag-39):** ADR-0068 migration substrate provides
  the schema-drift detector that the CMD-AC tests consume; the
  Phase-3-COMPLETE marker references the schema-version-anchor in
  the audit-trail.
* **Henrik (Internal Audit, Tag-39):** Zone-N quarterly review
  consumes the Phase-3-COMPLETE marker as the Phase-3c-closure-
  timestamp anchor (§4.2).
* **Noa (SRE, parallel):** Post-cutover 5-day window SLO-evaluation
  feeds §2.4 closure gates.

## 8. Acceptance-Failure-Escalation

| Gate-Failure | Severity | Action | Owner |
|---|---|---|---|
| DW-AC-6-7-PAR-1 red | S0 | Abort cutover, revert to KW-26-terminal | Operator-Hand |
| DW-AC-6-7-PAR-2 red (NATS-subject-drift detected) | S0 | Abort cutover, drift-investigation by Reza | Mira → Reza |
| DW-AC-6-7-SEQ terminal-equivalence red | S1 | Back-out to SEQ, cutover-Mittwoch postponed | Mira → AR |
| DW-AC-6-7-SLDC byte-drift | S0 | Abort cutover, subscription-cursor investigation | Mira → Selin (Persona-Engine) |
| DW-AC-6-7-RDC restart-point drift | S0 | Abort cutover, restart-point reconstruction investigation | Mira → Selin |
| DW-AC-6-7-RC R1-token-rotation-race detected | S1 | Pre-warm R1-token-cache, retry cutover after 24h | Operator-Hand + Tomás |
| DW-AC-6-7-P3M-1 non-rust modul | S0 | Abort closure, re-verify earlier cutover-wave | Operator-Hand + Henrik |
| DW-AC-6-7-P3M-2 marker misfires | S1 | Abort closure, audit-trail substrate investigation | Henrik |
| Cross-Review-Session no-consensus | S1 | Re-run review, AR-consultation if 2nd no-consensus | Aisha → Mira |

The S0/S1 classification follows Noa's SRE-incident classification
schema. S0 blocks cutover-Mittwoch; S1 may permit cutover with AR-
override + post-cutover-Friday close-out commitment.

## 9. Diff vs. Doppel-Welle-4+5 (KW 26)

| Aspect | Welle-4+5 (KW 26) | Welle-6+7 (KW 27) |
|---|---|---|
| Pair character | Hot-State persistence | Stateful-loop + cross-modul orchestrator |
| Substantive risk | Schema-drift between state_backing and fsm | NATS-subject-drift between subscribe_loop and recovery |
| Cross-Cutover anchor | Welle-3 KW-25 post-cutover verification | Welle-4+5 KW-26-terminal substrate |
| Authentication race-class | (none specific) | R1-capability-token rotation-race |
| Closure-gate | DW-AC-4-5-FTI (transition-set preserved) | DW-AC-6-7-P3M (Phase-3-COMPLETE marker fires) |
| Terminal-equivalence | parallel == sequential | parallel == sequential + path-agnostic marker |
| Phase-3-Marathon claim | (not yet) | **Yes** — Welle-7 sign-off closes Phase-3c |

## 10. Open Questions

* **AR-decision frame at KW-27 cutover-Tuesday:** Should the
  Phase-3-COMPLETE marker include an explicit AR-acknowledgement
  field, or is the boot-envelope-UUID + Welle-Ende-Acceptance
  cross-reference sufficient? Recommendation: marker self-contained,
  AR-acknowledgement recorded in ADR-0066 §Schluss-Acceptance-Log
  rather than in the substrate. ADR-bedarf if AR disagrees.
* **Quarterly Zone-N review frequency post-Phase-3c:** Phase-3c-Ende
  ~2026-06-21. The Q3-2026 Zone-N review is the first to consume the
  Phase-3-COMPLETE marker. Should the marker drive an out-of-band
  Henrik-review (within 7 days of cutover-Tag) or wait for the
  scheduled quarterly? Recommendation: 7-day out-of-band Zone-N
  review for the closure milestone, then resume quarterly cadence.
* **bridge_audit_diff_engine wire-in status at KW-27:** The Welle-4-
  smoke documents Reza's Tag-36 wire-in (PR #241) which the
  `DEFAULT_EXPECTED_COMPONENTS=10` baseline tracks. By KW-27 the
  wire-in must be production-live (`--expected-components 11`).
  Verification owner: Tomás Engineering-Lead.

---

— Amara (Tag-39, 2026-05-18)
