# Quality-Gate — Phase-3c Cutover Welle E2E Acceptance

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Draft skeleton — pending Phase-3c-Welle-Start trigger (ADR-0065 §Decision-Trigger) |
| Phase | 3c — Per-Welle Cutover from Python-Default to Rust-Default for 7 Engine-Komponenten |
| Source | ADR-0065 §Verifikations-Plan, ADR-0066 §Beschluss (Doppel-Welle-Beschleunigung), ADR-0063 §Phase-3c-Final-Cutover, ADR-0058 §Phase-3 |
| Date | 2026-05-17 (skeleton creation); 2026-05-17 Doppel-Welle-Extension (Tag-30 Mini-Welle, ADR-0066 §Folge-Item) |

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
