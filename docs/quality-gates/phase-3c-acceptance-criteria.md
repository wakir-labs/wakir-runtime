# Quality-Gate — Phase-3c Cutover Welle E2E Acceptance

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Draft skeleton — pending Phase-3c-Welle-Start trigger (ADR-0065 §Decision-Trigger) |
| Phase | 3c — Per-Welle Cutover from Python-Default to Rust-Default for 7 Engine-Komponenten |
| Source | ADR-0065 §Verifikations-Plan, ADR-0066 §Beschluss (Doppel-Welle-Beschleunigung), ADR-0063 §Phase-3c-Final-Cutover, ADR-0058 §Phase-3 |
| Date | 2026-05-17 (skeleton creation); 2026-05-17 Doppel-Welle-Extension (Tag-30 Mini-Welle, ADR-0066 §Folge-Item); 2026-05-17 Welle-3 Henrik-Caution-Extension (Tag-31 Mini-Welle, ADR-0066 §Beschluss Welle-3 carve-out) |

## 0. Phase contract

Phase-3c begins when **all** trigger-bedingungen from ADR-0065
§Decision-Trigger are met (7/7 Phase-3b-done, 2-Wochen-Stabilitäts-
Fenster, Live-VM-Acceptance-Lane green, Cosign-Policy verified,
Quadlet-Installer Rollback-tested, CFO-Cost-Telemetrie-Baseline,
ADR-0065 AR-approved).

Once Phase-3c starts, the 7 wellen run per the ADR-0066 §Beschluss
Doppel-Welle-Cadence (4 Wochen statt 7):

* **KW 24** Doppel-Welle-1+2 (`v907_verify` + `svid_workload_identity`)
* **KW 25** Solo-Welle-3 (`bridge_audit_writer`, Henrik-Caution)
* **KW 26** Doppel-Welle-4+5 (`state_backing` + `lifecycle_state_machine`)
* **KW 27** Doppel-Welle-6+7 (`subscribe_loop` + `recovery_workflow`)

Each welle's E2E acceptance-suite (this document) gates the welle's
Go/No-Go-Decision (Freitag, ADR-0065 §Verifikations-Plan Wochen-Plan,
retained under ADR-0066 §Mitigation 3). Doppel-Wellen carry an
additional five DW-AC-1...DW-AC-5 acceptance criteria (§9 below).

## 1. Welle-für-Welle Acceptance-Kriterien (AC-1 ... AC-5)

The five acceptance-criteria from ADR-0065 §"Acceptance-Kriterien
pro Komponente (Wochen-Ende)" apply identically to every welle.
Per-welle specialisation is encoded in the welle-test files and
captured in the welle-fokus column.

| Welle | Modul | Test-File | Risiko-Klasse | Welle-Fokus |
|---|---|---|---|---|
| 1 | `v907_verify` | `test_welle_1_v907_verify_e2e.py` | Niedrigste (read-only) | V-907-pin-attest payload parity |
| 2 | `svid_workload_identity` | `test_welle_2_svid_workload_identity_e2e.py` | Niedrig (deterministic lookup) | SPIRE-SVID-payload hash parity |
| 3 | `bridge_audit_writer` | `test_welle_3_bridge_audit_writer_e2e.py` | Mittel (write, idempotent) | WAT-anchor idempotency + hold-out python writer |
| 4 | `state_backing` | `test_welle_4_state_backing_e2e.py` | Erhöht (persistent state) | JCS-byte-parity + schema-migration-rollback |
| 5 | `lifecycle_state_machine` | `test_welle_5_lifecycle_state_machine_e2e.py` | Erhöht (cross-modul state) | Transition-table cross-lang parity + Welle-4 contract |
| 6 | `subscribe_loop` | `test_welle_6_subscribe_loop_e2e.py` | Hoch (NATS state) | Subscription-cursor parity + Bug-42-replay |
| 7 | `recovery_workflow` | `test_welle_7_recovery_workflow_e2e.py` | Höchste (cross-modul orchestration) | Recovery-decision parity + Welle-Ende WE-1...WE-4 |

## 2. AC-1 ... AC-5 contract surface

### AC-1 — Bridge-Audit-Writer-Konsistenz-Report (5/5 days green)

* **Gate:** Across the 5-day Beobachtungs-Fenster, the Bridge-Audit-
  Writer-Konsistenz-Report must show zero Python ⇆ Rust envelope-
  hash divergence on the welle-modul's call-set.
* **Test-Helper:** `assert_ac_1_bridge_audit_consistency` in
  `tests/acceptance/phase_3c/_ac_assertions.py`.
* **Owner-Substrate:** Selin (Bridge-Audit-Writer-Konsistenz-Report-
  Pipeline, ADR-0065 §Folgeartefakte 7) produces the daily report;
  Amara consumes it as the AC-1 oracle.

### AC-2 — Performance: P95-Latency ≤ Python-Baseline + 20%

* **Gate:** Rust-backend P95-Latency on the welle-modul stays within
  120% of the Python-baseline (Phase-3a benchmark).
* **Test-Helper:** `assert_ac_2_performance_headroom`.
* **Owner-Substrate:** Noa-Prometheus-Gauges deliver the P95-metric;
  Amara consumes the metric as the AC-2 oracle.
* **Vermutung-P2:** 20% headroom is an ADR-0065 placeholder pending
  Noa-design-review.

### AC-3 — Bug-Rate: 0 substanz-relevante (S0/S1) Issues

* **Gate:** Zero S0 or S1 issues filed against the welle-modul during
  the Beobachtungs-Woche.
* **Test-Helper:** `assert_ac_3_bug_rate`.
* **Owner-Substrate:** Issue-tracker query (Operator-Hand input pre-
  trigger-sprint, automated query post-trigger-sprint).

### AC-4 — Cross-Review-Session-Konsensus

* **Gate:** All Engineering-Personas (Tomás, Reza, Kai, Lena, Noa,
  Selin) consent in the Donnerstag Cross-Review-Session (Aisha-
  protokolliert).
* **Test-Helper:** `assert_ac_4_cross_review_consensus`.
* **Owner-Substrate:** Aisha-Cross-Review-Session-Protokoll
  (ADR-0065 §Folgeartefakte 8).

### AC-5 — V-907 Pin-Validation 100% pass-rate

* **Gate:** V-907-pin-attest validation on all live Persona-Defs
  pass post-welle-cutover (Cache-Konflikt-Free, ADR-0064 §Risiken).
* **Test-Helper:** `assert_ac_5_v907_pin_validation`.
* **Owner-Substrate:** V-907-validation-cli over the
  `agents/*.md` Persona-Def corpus.

## 3. Welle-Ende-Acceptance (WE-1 ... WE-4)

Welle-Ende-Acceptance fires only after Welle-7-AC-1...AC-5 are
green. The four WE-Kriterien (ADR-0065 §Welle-Ende-Acceptance)
mark the *end of Phase-3c* and the close of ADR-0035 §C-Drift.

| ID | Gate | Test-Location |
|---|---|---|
| WE-1 | Container-Image-Tag `0.7.0-rust` als Production-Default aktiv | `test_welle_7_we_1_container_tag_0_7_0_rust_record` |
| WE-2 | Quadlet-Default-ENV-Flags alle 7 auf `rust` | `test_welle_7_we_2_quadlet_all_seven_rust` |
| WE-3 | Henrik-Audit-Compliance-Check GREEN (ADR-0035 §C-Drift-Closure) | `test_welle_7_we_3_henrik_audit_compliance_green` (skip — pending) |
| WE-4 | `wirelang/persona_engine_py_legacy/` archived (4-Wochen-Reserve) | `test_welle_7_we_4_python_legacy_archived_not_deleted` (skip — pending) |

## 4. Skeleton scope and skip-by-default

This test-suite is a **skeleton**. The Phase-3c-trigger sprint
replaces the mock substrate (`mocked_bridge_audit_writer`,
`mocked_engine_boot`, `mocked_wat_anchor_sink`, `mocked_quadlet_env`,
`mocked_cross_review`) with the real engine + bridge + Quadlet
wiring.

Until then, the suite is **skip-by-default**:

* **Default CI:** All `phase_3c_acceptance`-marked tests skip via
  the `conftest.py` `pytest_collection_modifyitems` hook.
* **Opt-in for the trigger sprint:** Either `WAKIR_PHASE_3C_E2E=1`
  env-var or `pytest --phase-3c-acceptance` CLI flag enables the
  skeleton.

This mirrors `tests/infra/test_phase_3_acceptance_gates.py` (Phase-3-
Validation skeleton, PR #80) — *same skip-by-default pattern*, scoped
to per-welle granularity.

## 5. Sandbox boundary

Hermetic-only. No podman, no live NATS, no live Bridge-Audit-Writer
I/O, no OTS-calendar I/O, no SPIRE-agent RPC. The live-VM-acceptance
lane (ADR-0060) remains Operator-Hand. The fixtures in this suite are
the *test-time oracles* the live drills will compare against.

## 6. Zone-N coordination (Henrik / Internal Audit)

Welle-Ende WE-3 ("Henrik-Audit-Compliance-Check GREEN") is the
explicit Zone-N hand-off. Per the Amara/Henrik Zone-N-Quarterly-Review
(Aisha-moderiert), QA-evidence from this suite (AC-1...AC-5 pro
Welle + WE-1...WE-4 Welle-Ende) is *complementary* to Henrik's
audit-sample, **not substitutive**. Henrik runs his own ADR-0035 §C-
Drift-Closure compliance-check post-Welle-Ende.

## 7. Vermutungs-Kennzeichnung (P2)

The exact thresholds below are ADR-0065-sourced placeholders pending
real Phase-3a/3b benchmark replacement:

* AC-1: 5/5 days green (ADR-0065 fixed).
* AC-2: 20% headroom (ADR-0065 placeholder, pending Noa-design-review).
* AC-3: 0 S0/S1 (ADR-0065 fixed).
* AC-4: 6-persona consensus (Engineering-Matrix snapshot per
  `agents/*.md` 2026-05-17).
* AC-5: 100% pass-rate (ADR-0064 §Risiken non-negotiable).

The AC-2 placeholder Python-baseline-numbers (P95 in ms) inside the
welle-test files are *shape anchors*, not Aufsichtsrat-binding values.

## 8. Related artefacts

* `decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md`
  (proposed, this PR-suite implements §Verifikations-Plan).
* `decisions/0066-phase-3c-beschleunigung-option-a-plus.md` (Doppel-
  Welle-Beschleunigung KW 24/26/27, this PR-suite implements
  §Beschluss for the Doppel-Welle-Extension §9 below).
* `decisions/0063-persona-engine-sprach-revision-rust-rewrite.md`
  (approved 2026-05-16, §Phase-3c-Verweis).
* `docs/quality-gates/phase-3-production.md` (Amara, PR #80) — the
  parent Phase-3 acceptance-gate document this welle-suite extends.
* `tests/infra/test_phase_3_acceptance_gates.py` (Amara, PR #80) —
  the skip-by-default skeleton pattern this suite inherits.

## 9. Doppel-Welle-Extension (ADR-0066 §Beschluss)

ADR-0066 (approved 2026-05-17) collapses the seven-Wochen-Cadence
from ADR-0065 into a four-Wochen-Doppel-Welle-Cadence: three Doppel-
Wellen + one Solo-Welle (Welle-3, Henrik-Caution carve-out).

### 9.1 Doppel-Welle-Tabelle

| Doppel-Welle | KW | Modul-A | Modul-B | Charakter | Cross-Modul-Drift-Focus | Test-File |
|---|---|---|---|---|---|---|
| DW-1+2 | KW 24 | `v907_verify` | `svid_workload_identity` | Read-only-paar | Niedrig (kein gemeinsamer Schema-Touchpoint) | `test_doppel_welle_1_2_e2e.py` |
| DW-4+5 | KW 26 | `state_backing` | `lifecycle_state_machine` | Cross-modul-state-paar | **Hoch** (Producer/Consumer JCS-Schema-Contract, beidseitig Rust) | `test_doppel_welle_4_5_e2e.py` |
| DW-6+7 | KW 27 | `subscribe_loop` | `recovery_workflow` | Stateful-loop-paar | Mittel (Subscription-Cursor + Recovery-Readback) | `test_doppel_welle_6_7_e2e.py` |

### 9.2 DW-AC-1 ... DW-AC-5 Acceptance-Kriterien

Each Doppel-Welle test-file enforces five Doppel-Welle-specific
criteria *in addition to* the per-welle AC-1...AC-5 in the sister
per-welle test-files. The five DW-AC criteria are encoded in
`tests/acceptance/phase_3c/_ac_assertions.py`.

| ID | Gate | Test-Helper |
|---|---|---|
| **DW-AC-1** | Beide Komponenten boot mit rust-Backend im selben engine-boot-cycle; exakt das Pair-Tupel ist rust-flipped (keine Extras). | `assert_dw_ac_1_both_moduln_boot_rust` |
| **DW-AC-2** | Cross-Modul-Schema-Konsistenz byte-paritär über alle Producer→Consumer-Touchpoints des Pairs. | `assert_dw_ac_2_cross_modul_schema_byte_parity` |
| **DW-AC-3** | Asymmetric single-Komponente-Rollback: bei Bug in einer Komponente rollt nur diese auf python zurück, die andere bleibt rust. Elapsed ≤10min ENV-Flag-Switch-SLA. | `assert_dw_ac_3_asymmetric_rollback` |
| **DW-AC-4** | Cross-Modul-Stress-Test grün: zero failures, zero p99-latency-excursions, zero cross-modul-schema-drifts über die Stress-Window. Referenziert Phase-2-Acceptance-Gate-Erweiterung (Tomás Tag-29, ADR-0066 §Mitigation 1). | `assert_dw_ac_4_cross_modul_stress_test_green` |
| **DW-AC-5** | Backend-Decision-Audit emittiert exakt 2 Records gleichzeitig im selben cutover-cycle, beide target_backend = rust, beide Pair-Moduln genannt. | `assert_dw_ac_5_backend_decision_audit_two_records_consistent` |

### 9.3 Per-Doppel-Welle Gate-Schwerpunkt-Tabelle

Welle-Charakter steuert die DW-AC-Gewichtung. Alle fünf DW-AC sind
hart-gates; die Schwerpunkte zeigen, welche DW-AC bei welcher
Doppel-Welle den dominanten Drift-Detektions-Wert liefern:

| Doppel-Welle | Dominante DW-AC | Sekundäre DW-AC | Begründung |
|---|---|---|---|
| DW-1+2 (KW 24) | DW-AC-1, DW-AC-5 | DW-AC-2, DW-AC-3, DW-AC-4 | Read-only → Boot-Konsistenz + Audit-Trail-Vollständigkeit primär; Cross-Modul-Schema marginal |
| DW-4+5 (KW 26) | **DW-AC-2, DW-AC-4** | DW-AC-1, DW-AC-3, DW-AC-5 | Cross-Modul-Drift-Focus → Schema-Byte-Parity + Cross-Modul-Stress dominant |
| DW-6+7 (KW 27) | DW-AC-1, DW-AC-3, DW-AC-5 | DW-AC-2, DW-AC-4 | Phase-3c-Closing-Cutover → Boot-Success + Asymmetric-Rollback-Capability + Audit-Vollständigkeit für WE-1...WE-4-Handoff |

### 9.4 Doppel-Welle-Opt-In-Gate

The Doppel-Welle skeleton is **independently** skip-by-default from
the per-welle skeleton:

* **Per-welle opt-in:** `WAKIR_PHASE_3C_E2E=1` env-var or
  `pytest --phase-3c-acceptance` CLI flag.
* **Doppel-Welle opt-in:** `WAKIR_PHASE_3C_DOPPEL_E2E=1` env-var or
  `pytest --phase-3c-doppel-welle-acceptance` CLI flag.

The two lanes are independent so that the KW 25 Solo-Welle-3
trigger-sprint can run per-welle without invoking Doppel-Welle
oracles (which would not apply during a solo cutover).

### 9.5 Zone-N coordination — Doppel-Welle delta

Henrik (Internal Audit) Zone-N-Quarterly-Review (Aisha-moderiert)
covers the Doppel-Welle DW-AC-5 audit-record-pair specifically:
QA-evidence (DW-AC-5 happy-path + failure-modes) is *complementary*
to Henrik's audit-sample of the Backend-Decision-Audit-Trail under
parallel cutover. Henrik's audit-sample at the Doppel-Welle-trigger-
sprint focuses on (a) cutover-cycle-id integrity and (b) the
asymmetric-rollback audit-trail when DW-AC-3 fires in the field.

### 9.6 Vermutungs-Kennzeichnung (P2) — Doppel-Welle delta

* The Cross-Modul-Stress-Test stress-loads in the test-fixtures
  (`total=1000` for DW-1+2, `total=5000` for DW-4+5, `total=2000`
  for DW-6+7) are placeholder shape-anchors; the Doppel-Welle-
  trigger-sprint wires Tomás Tag-29 substrate's real load-targets.
* The Cross-Modul-Schema touchpoint-IDs are placeholders pending
  real producer/consumer wiring of state_backing↔lifecycle_state_
  machine, subscribe_loop↔recovery_workflow, etc.
* The Rollback-SLA (`ROLLBACK_SLA_SECONDS = 600`) is ADR-0065/-0066-
  fixed (10min ENV-Flag-Switch); the Welle-4-specific 2h Schema-
  Migrations-Rollback drill is covered by a `@pytest.mark.skip`
  placeholder in `test_doppel_welle_4_5_e2e.py`.

## 10. Welle-3 Henrik-Caution-Extension (ADR-0066 §Beschluss Solo-Welle)

ADR-0066 §Beschluss carves Welle-3 (`bridge_audit_writer`) out of the
Doppel-Welle-Cadence as the only Solo-Welle (KW 25). The carve-out is
explicit Henrik-Caution: the bridge-audit-writer **is** the
consistency-oracle substrate for the other six wellen, so flipping its
own write-path to Rust-default while it remains the audit-trail-
producer requires three additional acceptance criteria layered on top
of the per-welle AC-1...AC-5.

These criteria are **solo-welle-specific** — Doppel-Wellen do not
carry them. Per ADR-0066 §Beschluss, the bridge-audit-writer never
pairs with another modul precisely so the cross-modul-paritäts-
question does not compound the Henrik-Caution-question.

### 10.1 HC-AC-1 ... HC-AC-3 Acceptance-Kriterien

| ID | Gate | Test-Helper | Constant |
|---|---|---|---|
| **HC-AC-1** | Bridge-Audit-Writer-Output independently validated by a Phase-2-Cross-Modul-Stress-Test sample, using the hold-out Python-pinned writer-instance as the consistency-oracle. Self-referential validation (Rust-writer-under-cutover as its own oracle) is rejected. | `assert_henrik_caution_ac_1_independent_stress_validation` | — |
| **HC-AC-2** | Welle-3-Rollback bei >0.5% Divergenz: atomic ENV-Flag-switch ≤10min SLA, post-rollback-backend `python`. Sub-threshold divergence must not trigger spurious rollback. | `assert_henrik_caution_ac_2_divergence_rollback` | `HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD = 0.5` |
| **HC-AC-3** | Pre-Cutover-Konsistenz-Baseline aus 7-Tage-Observability-Window: alle 7 Tage ≥99.5% per-day-consistency-rate. Erst dann darf Welle-3 Cutover-Mittwoch feuern. | `assert_henrik_caution_ac_3_pre_cutover_baseline` | `HENRIK_CAUTION_PRE_CUTOVER_BASELINE_DAYS = 7`, `HENRIK_CAUTION_PRE_CUTOVER_BASELINE_GREEN_RATE = 0.995` |

### 10.2 Gate-Schwerpunkt — Henrik-Caution Justification

The three HC-AC are layered atop AC-1...AC-5 because the bridge-audit-
writer is structurally distinct from the other six wellen:

* **HC-AC-1 vs AC-1**: AC-1 (5/5 days green) measures the Rust-writer
  output against the hold-out Python-writer. HC-AC-1 closes a
  *meta*-loophole: AC-1 by itself cannot detect when the hold-out
  validation-oracle is accidentally configured to read the same
  Rust-writer-output it is meant to verify (self-referential
  validation). HC-AC-1 forces operator-runbook attestation of oracle-
  independence and a Phase-2-Cross-Modul-Stress-Test sample on top.
* **HC-AC-2 vs AC-3**: AC-3 (0 S0/S1 issues) is a binary count-floor.
  HC-AC-2 introduces a *quantitative* divergence-percent gate (0.5%
  per-day) with an automated atomic-rollback hook. The bridge-audit-
  writer is the meta-modul; a single drift here poisons downstream
  audit-trails for all other six wellen, so a tighter and automated
  rollback discipline is non-negotiable.
* **HC-AC-3 vs AC-1 window**: AC-1 covers the *post-cutover* 5-day
  window. HC-AC-3 covers the *pre-cutover* 7-day window. The asymmetry
  is intentional — Henrik-Caution requires that the existing Python-
  only baseline be demonstrably stable before introducing a Rust-
  writer at all. A failing pre-cutover-baseline almost certainly
  indicates an upstream substrate issue masquerading as a write-path
  issue; cutting over to Rust on top of that masking would compound
  the diagnosis-problem.

### 10.3 Zone-N coordination — Henrik-Caution delta

Henrik's Zone-N-Quarterly-Review (Aisha-moderiert) gets a Welle-3-
specific evidence-bundle at the Welle-3 Cutover-Mittwoch:

* HC-AC-1 stress-sample provenance + oracle-independence attestation
  (Operator-Hand-runbook).
* HC-AC-2 divergence-rollback decision record (if rollback fired) or
  divergence-observation log (if rollback did not fire).
* HC-AC-3 7-day pre-cutover-baseline per-day-consistency-rate matrix.

Per Zone-N-Boundary-Discipline (ADR-0044 §Zone-N): QA-evidence from
the HC-AC layer is *complementary* to Henrik's audit-sample, **not
substitutive**. Henrik retains independent sampling rights on the
Welle-3 Backend-Decision-Audit-Trail and the post-cutover anchor-
trail integrity.

### 10.4 Welle-3-Opt-In-Gate

Welle-3 HC-AC tests carry the `phase_3c_acceptance` marker (NOT
`phase_3c_doppel_welle_acceptance`) — they are per-welle solo-cadence
gates, opt-in via `WAKIR_PHASE_3C_E2E=1` env-var or
`pytest --phase-3c-acceptance` CLI flag. The KW 25 Solo-Welle-3
trigger-sprint runs the per-welle lane only; the Doppel-Welle lane
is irrelevant for Welle-3.

### 10.5 Vermutungs-Kennzeichnung (P2) — Welle-3 delta

* The HC-AC-1 stress-sample size (`stress_window_request_count=5000`
  in the fixture default) is a placeholder shape-anchor pending the
  Phase-3c-trigger-sprint wire-up against Tomás Tag-29 Cross-Modul-
  Stress-Test substrate's real load-target.
* The HC-AC-2 divergence-threshold (`0.5%`) is ADR-0066 Henrik-
  Caution-fixed; tightening or loosening it requires an ADR-Folge-
  Item, not a conftest-edit (enforced by sanity-test
  `test_welle_3_henrik_caution_divergence_threshold_is_zero_point_five`).
* The HC-AC-3 pre-cutover-baseline window (`7` days, `≥99.5%` per-day
  floor) is ADR-0066 Henrik-Caution-fixed; same ADR-Folge-Item
  discipline (sanity-test
  `test_welle_3_henrik_caution_baseline_window_is_seven_days`).
* The HC-AC layer is solo-welle-only; under no circumstance applies
  to Doppel-Welle 1+2, 4+5, or 6+7. ADR-0066 §Beschluss is explicit:
  bridge_audit_writer never pairs.
