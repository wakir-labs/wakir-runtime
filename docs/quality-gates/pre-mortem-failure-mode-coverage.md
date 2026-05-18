# Quality-Gate — Phase-3-Marathon Pre-Mortem Failure-Mode Test-Coverage Matrix

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Tag-46 sweep — pending Phase-3c-Welle-Marathon execution (ADR-0066 four-Wochen-Cadence KW-24 -> KW-27) |
| Phase | 3 (closing): Pre-Mortem failure-mode test-coverage audit + Tag-46 sweep |
| Source | Tag-45 Amara Auftrag (Continuous-Mode, 2026-05-18); Tag-46 Amara Coverage-Sweep (Continuous-Mode, 2026-05-18); Henrik Tag-44 Pre-Mortem-Skizze (`reports/audit/phase-3-marathon-pre-mortem-2026-05-18.md`); ADR-0066 §Beschluss + §Wochen-Plan; ADR-0065 §Verifikations-Plan |
| Date | 2026-05-18 (creation Tag-45; sweep update Tag-46) |
| Test-File (Tag-45 baseline) | `tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py` |
| Test-File (Tag-46 sweep) | `tests/phase_3c/test_pre_mortem_coverage_sweep_tag_46.py` |
| Companion (positive marathon-sequence) | `tests/phase_3c/test_marathon_schluss_acceptance_drill.py` (Tag-43) |
| Companion (anti-pattern control surface) | `tests/phase_3c/test_marathon_anti_patterns.py` (Tag-44) |
| Companion (per-day walkthrough) | `tests/phase_3c/test_cutover_day_e2e_drill.py` (Tag-41) |
| Companion (marker state-machine) | `tests/phase_3c/test_phase_3_final_regression.py` (Tag-40) |
| Companion (audit pre-mortem) | `reports/audit/phase-3-marathon-pre-mortem-2026-05-18.md` (Henrik Tag-44) |

## 0. Contract scope

This document is the **failure-mode test-coverage audit** for the
Phase-3c-Welle-Marathon. It maps each of Henrik's 23 hypothetical
failure-modes (Tag-44 Pre-Mortem-Skizze, Klassen A/B/C/D) to the
existing Phase-3 test stack and classifies the coverage state as
**COVERED**, **PARTIAL**, **GAP-ACCEPTED**, or **GAP-OPEN**.

The Tag-45 coverage-audit is **not** a re-implementation of the
positive marathon-sequence (Tag-43), the control-plane anti-pattern
suite (Tag-44), the per-day walkthrough (Tag-41), or the marker
state-machine (Tag-40). It is a **meta-audit** that asserts the
union of those four suites either covers each failure-mode or
explicitly records the gap as `GAP-ACCEPTED` (out-of-scope for the
QA test surface, e.g. external dependencies / governance layer) or
`GAP-OPEN` (Tag-46+ follow-up item).

The Phase-3-Acceptance pyramid grows to five layers with this file:

| Layer | Suite | Owner | Contract |
|---|---|---|---|
| 1 — State-Machine | `test_phase_3_final_regression.py` (Tag-40) | Amara | Given seven sign-off-records, does the Phase-3-COMPLETE-marker fire? |
| 2 — Per-Day | `test_cutover_day_e2e_drill.py` (Tag-41) | Amara | Does one Cutover-Mittwoch produce a correctly-shaped sign-off-record? |
| 3 — Marathon | `test_marathon_schluss_acceptance_drill.py` (Tag-43) | Amara | Does the four-Wochen-Sequence thread the per-day records into the AC-1..AC-5 conjunction, fire the marker, fire the Bilanz-Trigger? |
| 4 — Anti-Pattern | `test_marathon_anti_patterns.py` (Tag-44) | Amara | Does the control-surface REJECT ten dedicated control-plane anti-patterns by construction? |
| 5 — Pre-Mortem Coverage | `test_pre_mortem_failure_mode_coverage_audit.py` (Tag-45, this doc) | Amara | Does the union of Layer-1..4 cover the 23 Pre-Mortem failure-modes, or is each gap explicitly classified? |

## 1. Classification taxonomy

Each of the 23 failure-modes (A1..A8, B1..B6, C1..C5, D1..D5) is
classified into one of four coverage-states:

| State | Meaning |
|---|---|
| **COVERED** | At least one test in Layer-1..4 directly asserts the invariant that the failure-mode would violate. The test is named and pinned in §2 below. |
| **PARTIAL** | The failure-mode is covered indirectly by at least one test, but the coverage is incomplete (e.g. only one of two structural arms is tested, or the test asserts a related but weaker invariant). A Tag-46+ follow-up is named. |
| **GAP-ACCEPTED** | The failure-mode is **structurally out-of-scope** for the QA test surface. Three sub-categories: (a) **external** failure-modes (D-class: GitHub-API, sigstore, cloud-provider, OTS-calendar) where the mitigation-anchor is operator-hand or fail-fast configuration, not a hermetic test; (b) **governance-layer** failure-modes (B5 spawn-collision, B6 persona-sleep-watch, C4 ADR-substanz) where the mitigation-anchor is a Memo / ADR / Mira-Hand process, not a test surface; (c) **operator-hand** failure-modes where the mitigation lives in the live-VM-acceptance-lane (ADR-0058 §Nachtrag), not in the hermetic test surface. |
| **GAP-OPEN** | The failure-mode is in-scope for the QA test surface but has **no** existing test that asserts its invariant. A Tag-46+ follow-up item is REQUIRED and named. |

## 2. The 23 failure-modes — coverage classification

### Class-A — Technisch (8 modes)

#### A1 — Cross-Modul-Drift Welle-N -> Welle-N+1 (Schema/State/API)

- **Coverage state.** COVERED.
- **Pinning tests.**
  - `test_cw_welle_m_state_does_not_corrupt_welle_n_for_all_m_lt_n`
    (Tag-40, `test_phase_3_final_regression.py`)
  - `test_cw_welle_isolation_holds_under_intermediate_sequential_states`
    (Tag-40, `test_phase_3_final_regression.py`)
  - `test_neg_cross_modul_drift_welle_4_5_blocker_marker_not_set`
    (Tag-43, `test_marathon_schluss_acceptance_drill.py`)
  - AP-4 (Tag-44, `test_marathon_anti_patterns.py`) — Cross-Welle
    FSM-state-leak via state-backing namespace prefix discipline.
- **Notes.** Tag-40 pins the isolation invariant cross-Welle as a
  pairwise property. Tag-43 pins the marathon-aggregate-level
  blocker-rejection. Tag-44 AP-4 pins the namespace-prefix discipline
  as the bidirectional invariant. Three suites together provide
  defence-in-depth.

#### A2 — FSM-Phantom-Transitions (illegal state-transitions post-cutover)

- **Coverage state.** PARTIAL.
- **Pinning tests.**
  - AP-4 (Tag-44) — partial coverage of FSM-state-leak via
    namespace-prefix discipline, but does NOT exercise transition-
    legality oracle directly.
  - Tag-37 Rust FSM-Replay-Engine — out-of-scope for this Python
    suite; covered in `bridge-audit/` Rust crate tests (operator-
    hand acceptance).
- **Follow-up (Tag-46+).** Add Python-side FSM-transition-legality
  oracle: given a Welle-N FSM-snapshot, the set of legal next-states
  MUST be a strict subset of the Welle-N+1 FSM-snapshot's legal
  predecessors. Place in `tests/phase_3c/` as
  `test_fsm_transition_legality_marathon.py`.

#### A3 — State-Migration-Failure (Welle-4 backing-Layer; Welle-7 Recovery-Pfad)

- **Coverage state.** COVERED.
- **Pinning tests.**
  - `test_welle_4_*` (Tag-40 lineage, `test_welle_4_cutover_smoke.py`)
  - `test_welle_7_*` (Tag-40 lineage, `test_welle_7_cutover_smoke.py`)
  - `test_pcd_drill_runs_full_seven_step_sequence_for_welle_4`
    (Tag-41, `test_cutover_day_e2e_drill.py`)
  - `test_pcd_drill_runs_full_seven_step_sequence_for_welle_7`
    (Tag-41, `test_cutover_day_e2e_drill.py`)
- **Notes.** Per-Welle cutover smokes + per-day drill walkthroughs
  cover the state-migration invariant. Live-VM lane (ADR-0058
  §Nachtrag) carries the substantive state-backing-snapshot test.

#### A4 — NATS-Mode-Mismatch (Tag-41 Bug-42-Klasse)

- **Coverage state.** COVERED.
- **Pinning tests.**
  - `test_dw_ac_6_7_par_nats_subject_drift_between_subscribe_loop_and_recovery_blocks`
    (Tag-39, `test_doppel_welle_6_7_acceptance.py`)
  - `test_dw_ac_6_7_rc_*` race-condition battery (Tag-39,
    `test_doppel_welle_6_7_acceptance.py`)
- **Notes.** NATS-subject-drift and Publisher/Subscriber-mode-drift
  are pinned at the Welle-6+7 acceptance layer. The Tag-41 Bug-42-Fix-
  PR's live-VM assertion lives in `tests/live_vm/` (acceptance lane).

#### A5 — Self-Reference-Trap-Fire (Welle-3 bridge-audit-writer)

- **Coverage state.** COVERED.
- **Pinning tests.**
  - AP-3 (Tag-44, `test_marathon_anti_patterns.py`) — `bridge_audit_
    writer` cutover-window pinned: legacy / new writer ownership of
    every record, no corruption-window.
  - `test_mar_kw_25_solo_welle_3_carries_henrik_caution_pre_audit_path_marker`
    (Tag-43, `test_marathon_schluss_acceptance_drill.py`) — Henrik-
    Caution Pre-Audit-Path marker on Welle-3 sign-off.
- **Notes.** AP-3 is the synthetic-ledger pin; the live audit-trail
  test lives in the AR-designated external Pre-Auditor's Welle-3
  audit-scope (operator-hand, not hermetic).

#### A6 — Cosign-Verification-Drift (Image-Re-Bake mid-Marathon)

- **Coverage state.** COVERED (Tag-46 substrate-layer closeout;
  pre-Tag-46 state was PARTIAL).
- **Pinning tests.**
  - `test_cosign_login_step_present` (`tests/ci/test_build_wakir_
    provisioner_workflow.py`) — Layer-1 CI-workflow shape.
  - `test_cosign_login_runs_before_sign`
    (`tests/ci/test_build_wakir_provisioner_workflow.py`) — Layer-1
    CI-workflow shape.
  - `tests/infra/test_cosign_drift_coverage_a6.py` (Tag-46, Kai) —
    Layer-3 substrate, 17 hermetic invariants:
    - `test_a6_per_binary_cosign_drift_invariant` (parametrised
      across 15 binaries, TV-A6-01..15).
    - `test_a6_image_digest_mismatch_recovery_posture` (TV-A6-16).
    - `test_a6_cosign_installer_semver_pin` (TV-A6-17).
    - `test_a6_keyless_oidc_identity_drift_detection` (TV-A6-18).
    - `test_a6_sigstore_trust_root_posture` (TV-A6-19).
    - `test_a6_coverage_classification_covered`
      + `test_a6_coverage_matrix_doc_exists_and_named` (TV-A6-20).
- **Notes.** Three-layered coverage: Layer-1 (CI-workflow shape) +
  Layer-3 (substrate per-binary cosign-drift detection + recovery
  posture + installer / OIDC / trust-root discipline). The Tag-46+
  Layer-5 marathon-level pin
  (`test_cosign_chain_marathon_image_hash_stability.py` — Amara owner)
  remains an additional defence-in-depth follow-up extending COVERED
  across the cutover sequence.

#### A7 — Persona-Engine-Sprach-Drift (Python-Rest in Hot-Path)

- **Coverage state.** COVERED.
- **Pinning tests.**
  - `test_coord_kw_26_dw_4_5_runs_in_parallel_with_symmetric_a7_drift`
    (Tag-41, `test_cutover_day_e2e_drill.py`)
  - `test_rollback_trigger_fires_when_a7_drift_exceeds_threshold`
    (Tag-41, `test_cutover_day_e2e_drill.py`)
- **Notes.** A7-Drift is named in two Tag-41 tests and rolled up
  into Tag-43 KW-26 Doppel-Welle bundle. Live-Latency P95/P99 watch
  is operator-hand on Cutover-Tag.

#### A8 — NATS-JetStream-Stream-Persistence-Loss (Welle-4-Cutover)

- **Coverage state.** PARTIAL.
- **Pinning tests.**
  - `test_welle_4_cutover_smoke.py` — per-Welle smoke covers
    state-backing layer-switch shape, but not the persistence-loss
    failure-mode directly.
- **Follow-up (Tag-46+).** Add hermetic state-backing-persistence-
  loss probe: given an in-test state-backing snapshot, simulate a
  cutover-window crash, assert the snapshot-restore invariant. Place
  in `tests/phase_3c/test_welle_4_state_backing_persistence_loss.py`.

### Class-B — Operativ (6 modes)

#### B1 — AR-Hand-Stop-Marker-Missing-Trigger

- **Coverage state.** PARTIAL.
- **Pinning tests.**
  - `test_cutover_cheat_sheet_structure.py` — §I AR-Hand-Stop-Marker
    section structure pinned (>=5 triggers).
- **Follow-up (Tag-46+).** No Marathon-level test asserts the
  trigger-firing invariant ("given a drift event >= threshold, an
  `activity-log.md` entry MUST be appended within T minutes"). Add
  `test_ar_hand_stop_marker_trigger_invariant.py`. Note: the
  substantive marker-emission is operator-hand (Mira-Hand or AR-
  Hand), not automation; the QA test pins the structural invariant.

#### B2 — Sign-Off-Sequenz-Bruch (Welle-N+1 startet vor Welle-N-Sign-Off)

- **Coverage state.** COVERED.
- **Pinning tests.**
  - `test_neg_welle_3_rollback_blocks_welle_4_to_7_and_marker_not_set`
    (Tag-43, `test_marathon_schluss_acceptance_drill.py`)
  - `test_cascade_welle_3_rollback_blocks_welle_4_through_7_start`
    (Tag-40, `test_phase_3_final_regression.py`)
  - `test_cascade_welle_5_rollback_blocks_welle_6_through_7_but_not_4`
    (Tag-40, `test_phase_3_final_regression.py`)
  - AP-9 (Tag-44, `test_marathon_anti_patterns.py`) — Rollback
    cascade-rejection.
- **Notes.** Four-fold coverage: aggregate-marker rejection (Tag-43),
  per-cascade-step rejection (Tag-40, twice), control-plane cascade-
  rejection (Tag-44 AP-9).

#### B3 — Pre-Auditor-Konflikt IIA-1130 Welle-3

- **Coverage state.** PARTIAL.
- **Pinning tests.**
  - `test_mar_kw_25_solo_welle_3_carries_henrik_caution_pre_audit_path_marker`
    (Tag-43) — Henrik-Caution marker pinned.
- **Follow-up (Tag-46+).** No test asserts the AR-Hand-designation-
  precondition (AR designates an external Pre-Auditor for Welle-3
  BEFORE Welle-3 cutover-day). Add structural test
  `test_welle_3_pre_auditor_designation_precondition.py` that parses
  the audit-spec markdown and asserts the AR-Hand-stamp file exists
  prior to KW-25 cutover-ISO.

#### B4 — Pre-Auditor-Konflikt IIA-1130 Welle-7

- **Coverage state.** COVERED.
- **Pinning tests.**
  - AP-7 (Tag-44, `test_marathon_anti_patterns.py`) — IIA-1130
    Welle-7 self-audit trap: Henrik-signoff rejection + AR-Hand-only
    admissibility.
  - `test_neg_welle_7_pre_auditor_decision_missing_marker_not_set`
    (Tag-43, `test_marathon_schluss_acceptance_drill.py`)
  - `test_ac15_ac_5_iia_1130_ar_hand_quote_empty_blocks_marker`
    (Tag-43, `test_marathon_schluss_acceptance_drill.py`)
  - `test_cross_marathon_kw_27_pre_auditor_decision_blocks_ac_5_quote`
    (Tag-43, `test_marathon_schluss_acceptance_drill.py`)
- **Notes.** Four-fold coverage including the substantive AR-Hand-
  quote-non-emptiness invariant.

#### B5 — Spawn-Collision bei >30 Spawns/Tag

- **Coverage state.** GAP-ACCEPTED (governance-layer).
- **Mitigation-anchor.** High-Tempo-Spawn-Collision-Memo 2026-05-17;
  Baseline-Commit-Pinning + idempotency-check in spawn-Auftrag.
  Memory: `feedback_high_tempo_spawn_collision.md`.
- **Rationale.** Spawn-orchestration lives in the Mira-Hand /
  spawn-Auftrag template layer, not in the runtime test surface.
  The mitigation is a process-discipline memo, not a hermetic test.

#### B6 — Persona-Sleep-Watch-Bruch

- **Coverage state.** GAP-ACCEPTED (governance-layer).
- **Mitigation-anchor.** `agents-workspaces/mira/persona-health-
  sleep-watch-2026-05-17.md`; Mira-Hourly-Telemetry; Tomás-Tag-43-
  Bilanz.
- **Rationale.** Persona-Sleep-Watch lives in the Mira-Hourly-
  Telemetry process surface, not in the runtime test surface.
  Mira-Hourly-Watchdog (`tests/test_mira_hourly_watchdog.py`)
  partially exercises the watchdog shape, not the sleep-discipline
  invariant.

### Class-C — Prozedural (5 modes)

#### C1 — COMPLETE-Marker-False-Positive

- **Coverage state.** COVERED.
- **Pinning tests.**
  - `test_p3m_marker_sets_only_when_all_seven_wellen_sign_off`
    (Tag-40, `test_phase_3_final_regression.py`)
  - `test_p3m_marker_blocked_when_six_of_seven_wellen_sign_off`
    (Tag-40, `test_phase_3_final_regression.py`)
  - `test_p3m_marker_blocked_when_ac_4_cross_review_consensus_missing`
    (Tag-40, `test_phase_3_final_regression.py`)
  - `test_p3m_marker_blocked_when_we_1_to_we_4_welle_ende_incomplete`
    (Tag-40, `test_phase_3_final_regression.py`)
  - `test_false_pos_marker_not_set_on_six_of_seven_signoff`
    (Tag-40, `test_phase_3_final_regression.py`)
  - `test_ac15_*` family (Tag-43, `test_marathon_schluss_acceptance_drill.py`)
  - AP-10 (Tag-44, `test_marathon_anti_patterns.py`) — empty-state-
    file false-positive rejection.
- **Notes.** Heaviest-covered failure-mode in the matrix (7+ tests).

#### C2 — AR-Ratifikation-Race (Phase-4 startet vor AR-Hand-Stempel)

- **Coverage state.** COVERED.
- **Pinning tests.**
  - AP-6 (Tag-44, `test_marathon_anti_patterns.py`) — AR-Hand
    ratification bypass rejection (8 bypass variants).
  - `test_ac15_ac_5_ar_hand_stamp_missing_blocks_marker`
    (Tag-43, `test_marathon_schluss_acceptance_drill.py`)
  - `test_ac15_ac_5_iia_1130_ar_hand_quote_empty_blocks_marker`
    (Tag-43, `test_marathon_schluss_acceptance_drill.py`)
- **Notes.** AC-5 stamp-shape + non-empty-quote + boolean-True
  pinned at both the marathon and the control-plane layer.

#### C3 — Public-Communication-Premature (Júlia publiziert vor Sign-Off)

- **Coverage state.** GAP-ACCEPTED (operator-hand / site-repo).
- **Mitigation-anchor.** Site-Publication-Items deferred memo
  (`agents-workspaces/mira/memory/project_site_pilot_publication_
  deferred.md`); Comms-Outbox-Pre-AR-Sichtung.
- **Rationale.** Comms-publication lives in the `wakir-site` repo
  (Quartz-render-pipeline), not in `wakir-runtime`. The mitigation
  is AR-Pre-Sichtung process-discipline.

#### C4 — ADR-Substanz-False-Premise

- **Coverage state.** GAP-ACCEPTED (governance-layer).
- **Mitigation-anchor.** `agents-workspaces/mira/memory/feedback_
  adr_substanz_pruefung_pflicht.md`; main-tip + PR-Stack pre-check
  before ADR-Vorlage.
- **Rationale.** ADR-Vorlage substanz-check lives in the Mira-Hand
  pre-vorlage process, not in the runtime test surface.

#### C5 — YAML-Frontmatter-Disziplin-Bruch (Quartz kippt)

- **Coverage state.** GAP-ACCEPTED (site-repo / operator-hand).
- **Mitigation-anchor.** `agents-workspaces/mira/memory/feedback_
  yaml_frontmatter_disziplin.md`; Pre-Commit-Lint im `wakir-site`.
- **Rationale.** Quartz-frontmatter-lint lives in the `wakir-site`
  repo's CI surface, not in `wakir-runtime`. Cross-repo enforcement
  is operator-hand.

### Class-D — Externe (5 modes)

All five Class-D failure-modes are **external dependencies** with
operator-hand or fail-fast configuration as the mitigation-anchor.
They are uniformly classified **GAP-ACCEPTED (external)** per the
Tag-45 contract scope (§0).

#### D1 — GitHub-API-Outage während Cutover-Tag

- **Coverage state.** GAP-ACCEPTED (external).
- **Mitigation-anchor.** Aggregator-Workflow ADR-0068 lokal-fail-fast;
  manueller Override-Pfad; github.status.com Watch.

#### D2 — NATS-Service-Failure auf Pilot-VM

- **Coverage state.** GAP-ACCEPTED (external / live-VM).
- **Mitigation-anchor.** ADR-0060 Live-FCOS-VM-CI-Gate; NATS-Cluster-
  Replikation. The live-VM-acceptance-lane (`tests/live_vm/`) is the
  operator-hand surface; the hermetic surface deliberately does not
  exercise live NATS (see `tests/phase_3c/test_doppel_welle_acceptance.
  py` header: "no live NATS").

#### D3 — Cosign-Verification-Drift (sigstore/Fulcio external)

- **Coverage state.** GAP-ACCEPTED (external).
- **Mitigation-anchor.** Pinned-Cosign-Version; lokales Key-Material-
  Backup. The internal cosign-chain shape is pinned by the Tag-44
  AP-6 sibling layer + the `tests/ci/test_build_wakir_provisioner_
  workflow.py` cosign-step tests.

#### D4 — Cloud-Provider-Throttling (Registry-Pull-Limits)

- **Coverage state.** GAP-ACCEPTED (external).
- **Mitigation-anchor.** Registry-Mirror; Pre-Cutover-Image-Cache-
  Warmup; Pull-Latency-Watch.

#### D5 — OpenTimestamps-Calendar-Outage

- **Coverage state.** GAP-ACCEPTED (external).
- **Mitigation-anchor.** Multiple-Calendar-Server; deferred-
  Verification-Pfad; OTS-Verify-Job.

## 3. Coverage summary

| Class | Total | COVERED | PARTIAL | GAP-ACCEPTED | GAP-OPEN |
|---|---|---|---|---|---|
| A (Technisch) | 8 | 6 (A1, A3, A4, A5, A6, A7) | 2 (A2, A8) | 0 | 0 |
| B (Operativ) | 6 | 2 (B2, B4) | 2 (B1, B3) | 2 (B5, B6) | 0 |
| C (Prozedural) | 5 | 2 (C1, C2) | 0 | 3 (C3, C4, C5) | 0 |
| D (Externe) | 5 | 0 | 0 | 5 (D1-D5) | 0 |
| **Total** | **24*** | **10** | **4** | **10** | **0** |

\* Henrik's Pre-Mortem-Skizze §6 names "23 hypothetische Failure-
Modes" but the table-row count is A8 + B6 + C5 + D5 = 24. The
discrepancy is harmless (Henrik notes "einzelne ID-Lücken durch
Klassifikations-Defaultpfad" in §6). The coverage matrix uses the
table-row count (24) as the canonical denominator.

**Coverage interpretation.**

- **10 of 24 failure-modes (41.7%) are directly COVERED** by at
  least one test in Layer-1..4 of the Phase-3-Acceptance pyramid
  (Tag-46 substrate-layer closeout flipped A6 PARTIAL -> COVERED).
- **4 of 24 failure-modes (16.7%) are PARTIAL** with an explicit
  Tag-46+ follow-up item named for each.
- **10 of 24 failure-modes (41.7%) are GAP-ACCEPTED** as structurally
  out-of-scope for the QA test surface (5 external D-class, 4
  governance-layer B5/B6/C3/C4/C5, 1 site-repo C5).
- **0 of 24 failure-modes (0%) are GAP-OPEN** with no path forward.

**Strukturelle Beobachtung (Vermutungs-Kennzeichnung P2).** The
PARTIAL bucket clusters around three structural seams:

1. **Audit-Substrate-Self-Reference seam** (A5/B3): Welle-3
   `bridge-audit-writer` as audit-oracle for downstream Wellen. The
   AP-3 synthetic-ledger pin + the Henrik-Caution-marker pin cover
   the structural invariant; the substantive cross-audit lives in
   the operator-hand AR-designated external Pre-Auditor process.
2. **State-Persistence seam** (A2/A8): FSM-transition-legality and
   state-backing-persistence-loss. The Tag-37 Rust FSM-Replay-Engine
   covers transition-legality at the Rust-crate-test layer; the
   Python-side smoke covers shape but not failure-mode. Tag-46+
   adds two Python-side tests to close the seam.
3. **Image-Chain seam** (A6): cosign-verification-chain across
   Welle-N -> Welle-N+1 image-hashes. **Closed at substrate-layer
   in Tag-46** by `tests/infra/test_cosign_drift_coverage_a6.py`
   (17 hermetic invariants — per-binary drift-anchor slots + recovery
   posture + installer / OIDC / trust-root discipline). The
   marathon-level image-hash-stability invariant (Welle-N == Welle-N+1
   image-hash) remains an additional defence-in-depth Tag-46+ pin
   owned by Amara.

## 4. Tag-46+ follow-up items (named, not yet spawned)

The five PARTIAL classifications each name a specific follow-up
test that closes the partial coverage. The Tag-45 coverage-audit
**does not spawn** these follow-ups; it only names them so the
Tag-46+ planning surface has explicit anchors.

| # | Failure-Mode | Follow-up test | Layer | Owner | Status |
|---|---|---|---|---|---|
| 1 | A2 FSM-Phantom-Transitions | `test_fsm_transition_legality_marathon.py` | 5 (Marathon) | Amara | pending |
| 2a | A6 Cosign-Verification-Drift (substrate) | `tests/infra/test_cosign_drift_coverage_a6.py` | 3 (substrate) | Kai (Zone-C cross-review) | **DONE (Tag-46, this audit; flipped A6 -> COVERED)** |
| 2b | A6 Cosign-Verification-Drift (marathon defence-in-depth) | `test_cosign_chain_marathon_image_hash_stability.py` | 5 (Marathon) | Amara, with Kai cross-review | pending (additional defence) |
| 3 | A8 NATS-JetStream-Persistence-Loss | `test_welle_4_state_backing_persistence_loss.py` | 5 (Marathon) | Amara, with Reza cross-review | pending |
| 4 | B1 AR-Hand-Stop-Marker-Trigger | `test_ar_hand_stop_marker_trigger_invariant.py` | 5 (Marathon) | Amara | pending |
| 5 | B3 Welle-3-IIA-1130-Pre-Auditor-Designation | `test_welle_3_pre_auditor_designation_precondition.py` | 5 (Marathon) | Amara, with Henrik cross-review (Zone N) | pending |

**Sequencing observation (Vermutungs-Kennzeichnung P2).** Items 1
and 3 (state-related) should be spawned before Marathon-Start (KW-24,
2026-06-08) since they cover Welle-4 / Welle-5 cutover invariants.
Item 2a (image-chain substrate) **landed Tag-46** (this audit) and
closed A6 at substrate-layer. Item 2b (image-chain marathon
defence-in-depth) and Item 4 (AR-Hand-Stop) can be spawned in parallel
with Marathon-Start. Item 5 (Welle-3-Pre-Auditor designation) MUST
be spawned before KW-25 (2026-06-16) since it is a Welle-3 cutover
pre-condition.

## 4a. Tag-46 sweep — promotion-detection state

The Tag-46 Coverage-Sweep
(`tests/phase_3c/test_pre_mortem_coverage_sweep_tag_46.py`) is the
follow-on to the Tag-45 baseline. It detects whether the four
spawn-streams targeting the PARTIAL-classified items (A2 / A6 /
A8 / B1) have landed their named follow-up test files, and
re-classifies COVERED-iff-present-else-PARTIAL. The fifth PARTIAL
item (B3 Welle-3-Pre-Auditor-Designation) is the **hard-deferred
KW-25 blocker** and is excluded from the Tag-46 promotion-set.

### Tag-46 spawn-stream map

| # | PARTIAL-Item        | Tag-46 Spawn-Owner | Cross-Review | Canonical Follow-up artefact (or accepted alias)                | Status (2026-05-18 Tag-46 sweep-time)         |
|---|---------------------|--------------------|--------------|-----------------------------------------------------------------|-----------------------------------------------|
| 1 | A2 FSM-Phantom      | Reza               | Amara        | `test_fsm_transition_legality_marathon.py` (alias accepted: `test_fsm_phantom_transition_coverage_a2.py` at `wirelang/tests/persona_engine/`) | **COVERED via PR #295 (commit `dd691c7`)**     |
| 2 | A6 Cosign-Drift     | Kai                | Amara        | `test_cosign_chain_marathon_image_hash_stability.py` (alias accepted: `test_cosign_chain_image_hash_stability_a6.py`) | PARTIAL — Tag-46 Kai spawn in flight          |
| 3 | A8 NATS-JetStream   | Selin              | Reza         | `test_welle_4_state_backing_persistence_loss.py` (alias accepted: `test_welle_4_jetstream_persistence_loss_a8.py`) | PARTIAL — Tag-46 Selin spawn in flight        |
| 4 | B1 AR-Hand-Stop     | Tomás              | Amara        | `test_ar_hand_stop_marker_trigger_invariant.py` (alias accepted: `test_ar_hand_stop_marker_trigger_b1.py`) | PARTIAL — Tag-46 Tomás spawn in flight        |
| 5 | B3 Welle-3 Pre-Aud  | (Tag-47+ deferred) | Henrik       | `test_welle_3_pre_auditor_designation_precondition.py` (alias accepted: `test_welle_3_pre_auditor_designation_b3.py`)         | **DEFERRED — KW-25 hard blocker (2026-06-15)**|

**Layout-tolerance.** The sweep accepts follow-up files at any of:
`tests/phase_3c/`, `wirelang/tests/persona_engine/`,
`tests/persona_engine/`, or `tests/ci/`. The canonical Tag-45 §4
placement is `tests/phase_3c/`; the persona-engine + CI placements
are accepted aliases when the failure-mode-substance is more
naturally pinned at the persona-engine module-level or the CI
workflow-shape level.

### Projected post-Tag-46 §3 summary (sweep recomputation)

If all four Tag-46 items land, the §3 summary shifts to:

| Class | Total | COVERED | PARTIAL | GAP-ACCEPTED | GAP-OPEN |
|---|---|---|---|---|---|
| A (Technisch) | 8 | 8 (A1-A8) | 0 | 0 | 0 |
| B (Operativ) | 6 | 3 (B1, B2, B4) | 1 (B3) | 2 (B5, B6) | 0 |
| C (Prozedural) | 5 | 2 (C1, C2) | 0 | 3 (C3, C4, C5) | 0 |
| D (Externe) | 5 | 0 | 0 | 5 (D1-D5) | 0 |
| **Total (post-Tag-46 if all four land)** | **24** | **13** | **1 (B3)** | **10** | **0** |

If zero Tag-46 items land, the summary stays at the Tag-45 baseline
(9 / 5 / 10 / 0). Partial-land states are linearly interpolated.

### Tag-46 A6 + B1 cross-validation (Amara self-authored)

For A6 and B1 — the two items where Amara is the cross-review
partner — the Tag-46 sweep additionally self-authors **structural
cross-validation tests** that pin the QA-perspective anchors
already-existing in the repo. These do not replace the spawn-
owner's follow-up file; they make the cross-review substrate
explicit and detect regressive removal of the anchors.

**A6 anchors (`test_t46_a6xv_*` family, 4 tests):**

1. `build-wakir-provisioner.yml` cosign signing-chain present.
2. `test_build_wakir_provisioner_workflow.py` cosign-step tests
   (named `test_cosign_login_step_present`, `test_cosign_login_
   runs_before_sign`) still pin the workflow shape.
3. Cutover-Operator-Cheat-Sheet §I trigger-9 names Quadlet-
   Restart-Failure + Container-Identity-Drift (image-identity-
   drift operator surface).
4. Tag-45 Kai PR #294 substrate doc (`quadlet-cosign-15-binary-
   installer.md`) present.

**B1 anchors (`test_t46_b1xv_*` family, 4 tests):**

1. Tag-45 Noa alert rule `WakirPhase3FailureModeB1ArHandStop
   MissingTrigger` present in `dashboards/phase-3-marathon-
   alerts.yaml`.
2. Tag-45 alert-shape test `test_b1_ar_hand_stop_missing_is_
   conjunction` present in `tests/ci/test_phase_3_marathon_
   failure_mode_alerts.py`.
3. Cutover-Operator-Cheat-Sheet §I lists >= 10 numbered operator-
   trigger conditions.
4. `test_cutover_cheat_sheet_structure.py` pins the §I shape
   (Tag-43 baseline anchor).

### Tag-47+ open items (Vermutungs-Kennzeichnung P2)

- **B3 Welle-3-Pre-Auditor-Designation is the hard-deferred
  blocker** for KW-25 cutover (2026-06-15). The AR-Hand
  designation of an external Pre-Auditor MUST be in place BEFORE
  Welle-3 cutover-day. The follow-up filename is named
  (`test_welle_3_pre_auditor_designation_precondition.py`) but
  not spawned in Tag-46 — Henrik's
  `reports/audit/welle-3-iia-1130-pre-decision-spec-2026-05-18.md`
  is the AR-Hand decision-frame, and the test file is the QA-side
  precondition-pin once the AR-Hand stamp file is defined.
- New failure-modes discovered during pre-cutover-probes (KW-22
  onwards) are surfaced as candidate GAP-OPEN entries on the next
  coverage-doc update.



The Tag-45 coverage-audit document is the **test-side companion** to
Henrik's Tag-44 Pre-Mortem-Skizze. Zone-N boundary observations:

- The Tag-45 document classifies coverage of **QA-test-surface**
  failure-modes. It does not classify audit-coverage; Henrik's
  audit-sample remains the audit-side surface.
- Class-B3 / Class-B4 (Henrik as actor) are listed in this matrix
  but Henrik's IIA-1130 self-conflict considerations are **not**
  evaluated by this document. The relevant specs (`reports/audit/
  welle-3-iia-1130-pre-decision-spec-2026-05-18.md`, `reports/audit/
  welle-7-iia-1130-conflict-resolution-spec-2026-05-18.md`) are
  Henrik-side; this document only checks "is there a test that
  pins the structural invariant the IIA-1130 conflict would
  violate?".
- The GAP-ACCEPTED (governance-layer) classifications (B5, B6, C3,
  C4, C5) are explicitly NOT a recommendation to skip audit-coverage.
  Henrik's audit-sample is the appropriate evidence-surface for
  those failure-modes; QA-test-surface is not.

## 6. Test-file contract

The Tag-45 test file `tests/phase_3c/test_pre_mortem_failure_mode_
coverage_audit.py` enforces this matrix as **assertions on the
test-suite structure itself**. The 25 tests in that file are split:

- 24 tests, one per failure-mode (A1..A8, B1..B6, C1..C5, D1..D5):
  each asserts the coverage-state classification documented in §2
  is consistent with the actual presence/absence of the named
  pinning-tests in the companion suites.
- 1 test: the §3 coverage-summary table totals match the §2
  individual classifications (consistency-check).

The test file is hermetic: it imports the companion test modules
via `importlib`, collects their test-function names, and asserts
the named pinning-tests exist. It does NOT re-execute the
companion tests.

— Amara Osei (QA), Tag-45 Pre-Mortem Coverage-Audit, 2026-05-18
— Amara Osei (QA), Tag-46 Coverage-Sweep + A6/B1 Cross-Validation, 2026-05-18
