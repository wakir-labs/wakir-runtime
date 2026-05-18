# Quality-Gate — Phase-3c Cutover Welle E2E Acceptance

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Draft skeleton — pending Phase-3c-Welle-Start trigger (ADR-0065 §Decision-Trigger) |
| Phase | 3c — Per-Welle Cutover from Python-Default to Rust-Default for 7 Engine-Komponenten |
| Source | ADR-0065 §Verifikations-Plan, ADR-0066 §Beschluss (Doppel-Welle-Beschleunigung), ADR-0063 §Phase-3c-Final-Cutover, ADR-0058 §Phase-3 |
| Date | 2026-05-17 (skeleton creation); 2026-05-17 Doppel-Welle-Extension (Tag-30 Mini-Welle, ADR-0066 §Folge-Item); 2026-05-17 Doppel-Welle-4+5 Cross-Modul-Drift-Extension (Tag-32 Mini-Welle, ADR-0066 §Beschluss Doppel-Welle-4+5 Cross-Modul-Drift-Focus + Priya CTO-Coordination-Plan v2); 2026-05-18 Rollback-Drill SLA-Verifikations-Suite (Tag-32 Mini-Welle Retry, ADR-0065 §Rollback-Strategie + ADR-0066 §Rollback) |

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

## 11. Doppel-Welle-4+5 Cross-Modul-Drift-Extension (ADR-0066 §Beschluss Cross-Modul-Drift-Focus)

ADR-0066 §Beschluss labels Doppel-Welle-4+5 (KW 26, `state_backing` ×
`lifecycle_state_machine`) as **Cross-Modul-Drift-Focus** — the
highest cross-modul-drift-risk Doppel-Welle slot. Priya
CTO-Coordination-Plan v2 (Tag-32 Mini-Welle) identified this slot as
requiring four additional acceptance criteria layered atop the
DW-AC-1...DW-AC-5 baseline, drilling deeper into the Rust-Rust
producer/consumer contract.

These criteria are **Doppel-Welle-4+5-specific** — DW-1+2 (read-only-
paar) and DW-6+7 (stateful-loop-paar) do not carry the CMD-AC layer.
ADR-0066 §Beschluss is explicit: only the `state_backing` ×
`lifecycle_state_machine` pair has a producer/consumer JCS-schema-
contract risky enough to warrant the layer.

The DW-AC layer already covers single-touchpoint byte-parity (DW-AC-2)
and aggregate stress-test zero-failure (DW-AC-4). The CMD-AC layer
extends this with deserialization round-trip parity, cross-lang wire-
form parity vs. Python baselines, per-Komponente consistency-rate
floor, and an atomic-flip rollback discipline.

### 11.1 CMD-AC-1 ... CMD-AC-4 Acceptance-Kriterien

| ID | Gate | Test-Helper | Constant |
|---|---|---|---|
| **CMD-AC-1** | `state_backing-rust` schreibt → `lifecycle_state_machine-rust` liest mit byte-identischer Schema-Deserialization (deserialize → re-serialize round-trip parity, schema-version-survival). | `assert_cross_modul_drift_ac_1_deserialization_round_trip` | — |
| **CMD-AC-2** | `lifecycle_state_machine-rust` State-Transition triggert `state_backing-rust` Persist mit gleicher Wire-Form wie Python-Pendant (Rust-Rust vs. `python-python-baseline` + `python-rust-welle-4-only` oracles). | `assert_cross_modul_drift_ac_2_write_back_wire_form_parity` | `CROSS_MODUL_DRIFT_WIRE_FORM_ORACLES` |
| **CMD-AC-3** | Cross-Modul-Stress-Test (PR #197) zeigt Welle-4+5 Konsistenz beider Komponenten ≥99.5%; joint-rate = `min(rate_a, rate_b)`. | `assert_cross_modul_drift_ac_3_per_komponente_consistency` | `CROSS_MODUL_DRIFT_CONSISTENCY_PCT_FLOOR = 0.995` |
| **CMD-AC-4** | Drift > 0.5pp → atomic single-Komponente rollback (high-drift modul auf `python`, partner bleibt `rust`-Default), ≤10min SLA, single restart-cycle. | `assert_cross_modul_drift_ac_4_atomic_flip_rollback` | `CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD = 0.5` |

### 11.2 Gate-Schwerpunkt — Cross-Modul-Drift-Focus Justification

Each CMD-AC drills deeper than a related DW-AC or AC criterion:

* **CMD-AC-1 vs DW-AC-2**: DW-AC-2 checks byte-parity on a single
  cross-modul touchpoint (producer side). CMD-AC-1 closes the round-
  trip loophole: the bytes may write correctly but mutate on
  deserialize→re-serialize, especially under Rust-side serde
  field-ordering drift or schema-version stripping. CMD-AC-1 catches
  the consumer-side mutation that DW-AC-2 does not see.
* **CMD-AC-2 vs DW-AC-2**: DW-AC-2 compares producer-bytes against
  consumer-bytes within the same cutover (Rust-Rust). CMD-AC-2
  compares the Rust-Rust wire-form against historical baselines
  (python-python pre-Welle-4 production state + synthetic python-
  rust-welle-4-only). A Rust-Rust regression vs. the long-standing
  Python production state breaks Welle-7 recovery_workflow even when
  Rust-Rust internal parity holds.
* **CMD-AC-3 vs DW-AC-4**: DW-AC-4 sets zero-failure on aggregate
  stress (binary count-floor). CMD-AC-3 sets a quantitative per-
  Komponente consistency-rate floor (≥99.5%) on the same stress-
  window. Captures non-throw-class drift (e.g. transient latency-
  tail without an exception) that DW-AC-4 misses but that operationally
  signals a Cross-Modul-Drift-Focus regression.
* **CMD-AC-4 vs DW-AC-3**: DW-AC-3 covers manual Operator-Hand
  asymmetric rollback discipline. CMD-AC-4 adds the *trigger-
  precondition* (drift > 0.5pp) + the *atomicity property* (single
  restart-cycle, no partial state). A flip on sub-threshold drift is
  rejected as spurious; a multi-restart-cycle flip is rejected as
  non-atomic. Tightens the runbook discipline beyond DW-AC-3's
  post-fact backend-state-check.

### 11.3 Cross-Modul-Stress-Test substrate (PR #197) wire-up

CMD-AC-3 references PR #197 Cross-Modul-Stress-Test substrate output
broken out per Komponente. PR #197 emits aggregate failure-count for
DW-AC-4; the Doppel-Welle-4+5 trigger-sprint extends the substrate's
output schema with two per-Komponente consistency-rate fields:

* `state_backing_consistency_rate` — Rust-side write-path consistency
  observed during the joint-load stress-window.
* `lifecycle_state_machine_consistency_rate` — Rust-side read+
  transition-path consistency observed in the same window.

The Phase-3c-trigger-sprint wires `mocked_cross_modul_drift_per_
komponente_consistency` against this extended substrate output. Pre-
sprint, the fixture is parity-by-construction (both rates 0.999).

### 11.4 Atomic-flip-pattern runbook substrate

CMD-AC-4 enforces an atomic-flip-pattern: when measured cross-modul-
drift exceeds 0.5pp, exactly one ENV-flag rewrite + ``systemctl
restart`` cycle flips the high-drift modul back to python-Default;
the partner stays untouched on rust-Default. The runbook substrate:

1. **Drift-observability:** Noa-Prometheus-Gauges emit per-Komponente
   drift-pct in real time (post-trigger-sprint wire-up; pre-sprint
   the CMD-AC-3 stress-test record carries the same numbers offline).
2. **Operator-Hand-trigger:** at the 0.5pp threshold, the runbook
   fires the atomic-flip on the high-drift modul only.
3. **Post-flip verification:** ENV-flag rewrite verified, restart-
   cycle completed inside 10min SLA, partner-modul backend confirmed
   rust.
4. **Audit-trail:** Backend-Decision-Audit emits a single rollback-
   record (not a cutover-record); Henrik's Zone-N-Audit-Sample
   distinguishes rollback-record from cutover-record at audit-time.

The runbook substrate is Operator-Hand territory; the CMD-AC-4 test
shape is the QA-side oracle the live drill compares against.

### 11.5 Zone-N coordination — Cross-Modul-Drift-Focus delta

Henrik (Internal Audit) Zone-N-Quarterly-Review (Aisha-moderiert)
gets a Doppel-Welle-4+5-specific evidence-bundle at the Doppel-Welle-
4+5 Cutover-Mittwoch:

* CMD-AC-1 deserialization round-trip log + schema-version-survival
  attestation (Operator-Hand-runbook).
* CMD-AC-2 wire-form-parity matrix (Rust-Rust × all reference oracles)
  with per-transition row-by-row diff.
* CMD-AC-3 per-Komponente consistency-rate matrix over the stress-
  window with joint-rate computation.
* CMD-AC-4 atomic-flip decision-records (if any drift > 0.5pp was
  observed) with trigger-precondition evidence + atomicity-property
  evidence (single restart-cycle log).

Per Zone-N-Boundary-Discipline (ADR-0044 §Zone-N): QA-evidence from
the CMD-AC layer is *complementary* to Henrik's audit-sample, **not
substitutive**. Henrik retains independent sampling rights on the
Backend-Decision-Audit-Trail under the Doppel-Welle-4+5 cutover and
on the atomic-flip rollback-records.

### 11.6 Doppel-Welle-4+5-Opt-In-Gate

CMD-AC tests carry the `phase_3c_doppel_welle_acceptance` marker —
they are Doppel-Welle-specific gates, opt-in via
`WAKIR_PHASE_3C_DOPPEL_E2E=1` env-var or `pytest --phase-3c-doppel-
welle-acceptance` CLI flag. The KW 26 Doppel-Welle-4+5 trigger-sprint
runs the Doppel-Welle lane; the per-welle lane (`WAKIR_PHASE_3C_E2E=1`)
covers Welle-4 + Welle-5 solo files independently.

### 11.7 Vermutungs-Kennzeichnung (P2) — Cross-Modul-Drift delta

* The CMD-AC-1 record-ids and CMD-AC-2 transition-ids in the fixture
  defaults (`rec-initial-state`, `transition-spawn-to-ready`, etc.)
  are placeholder shape-anchors pending Phase-3c-trigger-sprint wire-
  up against real `state_backing` + `lifecycle_state_machine` Rust-
  crate output.
* The CMD-AC-2 oracle-set (`python-python-baseline`,
  `python-rust-welle-4-only`) is ADR-0066-fixed; adding a Rust-Rust
  self-referential oracle is explicitly forbidden (sanity-test
  `test_doppel_welle_4_5_cmd_ac_2_oracles_anchor_to_adr_0066`).
* The CMD-AC-3 consistency-floor (`0.995`, 99.5%) is ADR-0066-fixed;
  loosening requires an ADR-Folge-Item, not a conftest-edit (sanity-
  test `test_doppel_welle_4_5_cmd_ac_3_consistency_floor_anchored_
  to_adr_0066`).
* The CMD-AC-4 drift-threshold (`0.5`, 0.5pp) is ADR-0066-fixed;
  mirrors the Welle-3 Henrik-Caution divergence threshold numerically
  but applies *per-modul*, not whole-bridge-audit-writer (sanity-
  test `test_doppel_welle_4_5_cmd_ac_4_threshold_anchored_to_adr_
  0066`).
* The CMD-AC layer is Doppel-Welle-4+5-exclusive; under no circumstance
  applies to DW-1+2 (read-only-paar, no schema-touchpoint) or DW-6+7
  (stateful-loop-paar, different drift-surface addressed by DW-6+7
  schwerpunkte).

## 12. Rollback-Drill SLA-Verifikations-Suite (ADR-0065 §Rollback-Strategie + ADR-0066 §Rollback)

ADR-0065 §Rollback-Strategie and ADR-0066 §Rollback fix the rollback
contract for every Phase-3c-Komponente: an ENV-Flag-Switch from
`rust` back to `python` must complete inside a 10-minute SLA and
emit a Backend-Decision-Audit-Record for the rollback event. The
Rollback-Drill-Suite (`tests/acceptance/phase_3c/rollback_drill/`)
is the End-to-End QA-Evidence layer for that contract.

### 12.1 Drill scope — nine Komponenten

The drill-suite covers all nine Phase-3c-Komponenten that share the
`WAKIR_ENGINE_<MODUL>_BACKEND=rust|python` ENV-Flag substrate. Seven
of the nine map to the per-welle cutover-sequence (welle-1 ...
welle-7); two additional Komponenten share the substrate but do not
occupy a numbered welle-slot.

| # | Komponente | Welle-Slot | Test-File |
|---|---|---|---|
| 1 | `v907_verify` | Welle-1 | `test_rollback_drill_v907_verify.py` |
| 2 | `svid_workload_identity` | Welle-2 | `test_rollback_drill_svid_workload_identity.py` |
| 3 | `bridge_audit_writer` | Welle-3 (Henrik-Caution-Carve-out) | `test_rollback_drill_bridge_audit_writer.py` |
| 4 | `state_backing` | Welle-4 | `test_rollback_drill_state_backing.py` |
| 5 | `lifecycle_state_machine` | Welle-5 | `test_rollback_drill_lifecycle_state_machine.py` |
| 6 | `subscribe_loop` | Welle-6 | `test_rollback_drill_subscribe_loop.py` |
| 7 | `recovery_workflow` | Welle-7 | `test_rollback_drill_recovery_workflow.py` |
| 8 | `anchor_emitter` | — (additional, Phase-3c-Cutover-eligibel) | `test_rollback_drill_anchor_emitter.py` |
| 9 | `federation_resolver` | — (additional, Phase-3c-Cutover-eligibel) | `test_rollback_drill_federation_resolver.py` |

### 12.2 RD-1 ... RD-4 Acceptance-Kriterien

Each drill-file carries exactly four tests, one per RD-criterion.
The four criteria are encoded as assertion-helpers in
`tests/acceptance/phase_3c/rollback_drill/conftest.py`.

| ID | Gate | Test-Helper |
|---|---|---|
| **RD-1** | ENV-Flag `rust → python` switch hat Effekt — pre-switch backend `rust`, post-switch backend `python`, modul-identity matches drill-target. | `assert_rd_1_env_flag_switch_effective` |
| **RD-2** | Backend-Decision-Audit-Record dokumentiert Rollback-Event — modul-name, `target_backend=python`, non-empty cutover-cycle-id, operator-actor populated. | `assert_rd_2_audit_record_documents_rollback` |
| **RD-3** | Cross-Modul-Konsistenz nach Rollback grün — mocked Phase-2-Acceptance-Gate re-run returns `gate_green=True` with no failed sub-gates. | `assert_rd_3_cross_modul_konsistenz_post_rollback` |
| **RD-4** | Time-to-rollback ≤10min SLA — mocked-clock elapsed-seconds strictly positive and ≤`ROLLBACK_SLA_SECONDS` (600.0s). | `assert_rd_4_time_to_rollback_within_sla` |

### 12.3 Fixture substrate

Two fixtures carry the drill-evidence shapes:

* `mocked_rollback_event` — produces `RollbackEvent` records with
  pre/post-switch ENV-state, mocked-clock elapsed-seconds, the
  associated `BackendDecisionRecord`, and the Bridge-Audit-Writer-
  Re-Verify status (ADR-0065 §Rollback-Strategie step 4).
* `mocked_phase_2_acceptance_gate` — produces
  `Phase2AcceptanceGateRecord` records for the post-rollback Phase-2-
  Acceptance-Gate re-run; default green, with failure-mode injection
  via `gate_green=False` + `failed_sub_gates=(...)`.

### 12.4 Opt-in gate

The drill-suite is **skip-by-default**, independently from the per-
welle and Doppel-Welle skeletons:

* **Drill opt-in:** `WAKIR_PHASE_3C_ROLLBACK_DRILL=1` env-var or
  `pytest --rollback-drill` CLI flag.
* **Marker:** `phase_3c_rollback_drill` (registered in
  `pyproject.toml`).

This separation lets the cutover-week + post-rollback-event drills
run independently from the per-welle and Doppel-Welle acceptance
lanes. A real rollback-event in production triggers the drill-suite
to validate that the recovery completed inside the SLA contract.

### 12.5 Zone-N coordination — Rollback-Drill delta

Henrik-Zone-N (Internal Audit) consumes the RD-2 audit-record
evidence on his audit-sample of the Backend-Decision-Audit-Trail.
Per the Amara/Henrik Zone-N-Quarterly-Review, the drill-suite's
RD-2 happy-path evidence is **complementary** to Henrik's audit-
sample — Henrik retains his own ADR-0035 §C-Drift-Closure
compliance-check on rollback-event audit-trails.

The drill-suite's RD-1, RD-3, RD-4 evidence is QA-only (no Zone-N
hand-off); RD-2 is the explicit Zone-N touchpoint.

### 12.6 Hermetic-only sandbox boundary

All fixtures are hermetic mocks. No live `systemctl restart wakir-
persona-engine`, no host-side ENV-rewrite, no live NATS reconnect.
The Phase-3c-trigger-sprint wires the mock against the real
Operator-Hand-runbook output (Quadlet-ENV-rewrite + Prometheus-
Gauge elapsed-seconds measurement). The live-VM-acceptance-lane
(ADR-0060) remains Operator-Hand responsibility for the rollback
drill execution itself.

### 12.7 Vermutungs-Kennzeichnung (P2) — Rollback-Drill delta

* The `ROLLBACK_SLA_SECONDS = 600.0` constant in
  `tests/acceptance/phase_3c/rollback_drill/conftest.py` mirrors the
  same constant in `tests/acceptance/phase_3c/_ac_assertions.py`
  (ADR-0065/-0066-fixed 10min ENV-Flag-Switch SLA). Drift between
  the two constants should be flagged at Phase-3c-trigger-sprint
  wire-up time.
* The `mocked_rollback_event` default elapsed-seconds (240.0s) is a
  conservative anchor; Phase-3a benchmark data suggests typical
  engine-boot-time ≤60s under steady-state load.
* The Schema-Migrations-Rollback path (2-hour SLA per ADR-0065
  §Rollback-Strategie) is **not** covered by this drill-suite — it
  falls under a separate Reza-Folge-Spawn-Artefakt scoped to
  `state_backing` + `lifecycle_state_machine` schema-touching
  changes only.
