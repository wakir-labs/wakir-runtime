# Phase-3 Production-Trigger Checklist

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Draft skeleton — flipped from skeleton to binding when Phase-3-trigger sprint (~KW 27) begins |
| Source | ADR-0058 §"Phase 3 — Validation (Wochen 5-6)" + §"Phase 4 Cutover-Entscheidung", ADR-0063 §"Phase 3 — Rust-Engine-Cutover", `docs/quality-gates/phase-3-production.md` |
| Companion test-suite | `tests/infra/test_phase_3_acceptance_gates.py` (skip-by-default, opt-in via `WAKIR_PHASE_3_SKELETON=1`) |
| Date drafted | 2026-05-17 (UTC: 2026-05-17T00:01:31Z, AR-Cut Sprint-Phase-3-Validation-Test-Suite-Skeleton-MINI) |

## 0. Purpose

This checklist is the **pre-trigger gate** for the
Sprint-Phase-3-Validation-Test-Suite spawn. It does **not** gate the
Phase-2 → Phase-3 cutover decision itself — that decision is owned
by the Aufsichtsrat per ADR-0058 §"Phase 4 Cutover-Entscheidung",
fed by `phase-3-production.md` §1.

It gates the *prior* question: are we ready to *run* the Phase-3
validation sprint at all? If a checklist item is red, the sprint
spawn is premature and would either consume cycles producing noise
or produce false-positive confidence in Phase-3 readiness.

Two consumers:

1. **Mira (CEO)** — uses the checklist as the operational
   green-light before spawning the Sprint-Phase-3-Validation-Test-
   Suite-Full follow-up (~KW 27).
2. **Henrik (Internal Audit)** — uses the checklist's last-completed-
   item dates as the Audit-Sample anchor for "did QA gate the
   sprint-trigger on documented criteria, or wing it?".

## 1. The 10-item Pre-Trigger Checklist

Each item carries:

* **What** — the criterion in one sentence.
* **Who** — the owner of the evidence.
* **How verified** — the artefact or test the checklist signer
  inspects.
* **Status** — `[ ]` open, `[~]` partial, `[x]` complete (with date).

### Substrate-readiness (items 1–4)

#### 1. Phase-2 acceptance-gates all green for ≥ 14 consecutive days

* **Who:** Amara (QA), Selin (engine), Noa (substrate).
* **How verified:** `tests/infra/test_phase_2_acceptance_gates.py`
  aggregator green in every nightly CI run over the trailing 14-day
  window; weekly Doppelbetrieb-rollup signed off by Amara.
* **Status:** `[ ]` open.

#### 2. wakir-Tomás-Container has been Quadlet-`up` ≥ 99.9% over rolling 30d

* **Who:** Noa (SRE).
* **How verified:** Noa SLO-rollup over trailing 30-day window
  (mirror of `phase-3-production.md` §3 SLI row "Persona-Container
  `up`").
* **Status:** `[ ]` open.

#### 3. Bridge-Forward fan-out drop-rate ≤ 0.01% over rolling 24h, no excursions in 14d

* **Who:** Noa (SRE), Selin (engine).
* **How verified:** Bridge-audit reconciliation report over trailing
  14-day window; zero excursion-rows in Noa's alert log.
* **Status:** `[ ]` open.

#### 4. Zero V-907 pin-drift events over rolling 28d

* **Who:** Noa (SRE), Selin (engine).
* **How verified:** `EXIT_V907_HASH_DRIFT` event count == 0 over
  trailing 28-day window in the audit-substrate (mirror of
  `phase-3-production.md` §3 SLI zero-tolerance row).
* **Status:** `[ ]` open.

### Engineering-readiness (items 5–7)

#### 5. Rust-engine cutover replay-tape corpus frozen (15 canonical vectors)

* **Who:** Reza (Wirelang spec), Selin (engine).
* **How verified:** Corpus file checked into `tests/fixtures/`
  with 15 deterministic vectors; Reza + Selin sign-off ADR-comment
  on ADR-0063.
* **Status:** `[ ]` open.

#### 6. Rust-engine wakir.persona_engine.rust_bridge module byte-identical to Python engine on local hermetic smoke

* **Who:** Selin (engine).
* **How verified:** Hermetic CI smoke (independent of Gate-3-1 test
  skeleton) runs the 15-vector corpus through both engines; reports
  ≥ 14/15 parity before sprint-trigger and 15/15 at sprint-completion.
* **Status:** `[ ]` open. (Threshold is 14/15 pre-trigger to allow
  one in-flight fix during the sprint; 15/15 hardens during the
  sprint itself.)

#### 7. OTS audit-trail end-to-end p99 ≤ 60s sampled over 7 days

* **Who:** Tomás (WAT/OTS), Noa (SRE).
* **How verified:** Reconciliation report's latency-rollup column
  median + p99 over trailing 7-day window; Tomás sign-off comment
  in the rollup-PR.
* **Status:** `[ ]` open.

### Process-readiness (items 8–10)

#### 8. Phase-3a Module-Readiness matrix signed off

* **Who:** Priya (CTO) aggregates from engineering personae.
* **How verified:** Per-module readiness-row (Rust-bridge, OTS
  end-to-end, Bridge-Forward, V-907, recovery-drill harness) all
  marked green by their respective owner-persona in the matrix
  document; matrix-PR merged.
* **Status:** `[ ]` open.

#### 9. Rollback-runbook drill executed against Pilot-VM in trailing 30 days

* **Who:** Noa (runbook), Aisha (drill moderation).
* **How verified:** Signed-off drill-report with measured rollback-
  time, `outcome == "pass"`, and both Noa + Aisha named in the
  sign-off block (mirror of `phase-3-production.md` §3.2).
* **Status:** `[ ]` open.

#### 10. Zone-N cross-review with Henrik scheduled and any quarterly findings addressed

* **Who:** Amara (QA), Henrik (Internal Audit), Aisha (moderation).
* **How verified:** Calendar invite for Zone-N Phase-3-trigger
  review issued ≥ 7 days before sprint-spawn; any open findings
  from the most-recent quarterly Zone-N review either closed or
  explicitly deferred-with-justification by Henrik.
* **Status:** `[ ]` open.

## 2. Phase-3a Module-Readiness Matrix

Item 8 references this matrix. It is the per-module roll-up of "is
this component production-ready as the Phase-3-cutover-authoritative
substrate?". The matrix is populated by Priya (CTO) aggregating each
engineering-persona's self-assessment; QA does not author module-
readiness verdicts.

| Module | Owner-persona | Gate-evidence | Phase-3a status |
|---|---|---|---|
| `wakir.persona_engine.rust_bridge` (Rust engine) | Selin (Pengine) | ADR-0063 Phase-3 §"Cutover" + Gate-3-1 (15/15 parity) | `[ ]` open |
| `wat` + `wat-anchor-cycle` (OTS end-to-end) | Tomás (WAT) | Gate-3-3 (p99 ≤ 60s) + Henrik Audit-Punkt H | `[ ]` open |
| `wirelang.persona_engine.bridge_forward` (Bridge fan-out, observe-only fallback) | Selin (Pengine), Noa (SRE) | `phase-3-production.md` §3 SLI row (drop-rate ≤ 0.01%) | `[ ]` open |
| V-907 pin-attest middleware | Selin (Pengine) | `phase-3-production.md` §5 ("V-907 pin-attest is mandatory at every container spawn") | `[ ]` open |
| Recovery-drill harness (OI-PEF-11 production) | Selin + Noa | `phase-3-production.md` §3.4 + Gate-2-4 reference | `[ ]` open |

Matrix-edit policy: each row's `Phase-3a status` flip from `[ ]` to
`[x]` requires a sign-off comment on the matrix-PR from the named
owner-persona. Priya consolidates. No QA-discretion edit; QA reads
the matrix, does not edit it.

## 3. 28-Tage-Window Schwelle

The "28-Tage-Window" referenced in items 1, 2, 4 and in
`phase-3-production.md` §3.5 is the **post-cutover stability
window**. Three distinct uses of "28 days" must not be confused:

* **Phase-2 acceptance window** — the trailing window that gates
  Phase-2 → Phase-3 promotion (items 1, 2, 4 above; varies by SLI:
  14d, 30d, 28d depending on which gate).
* **Post-cutover stability window** — `phase-3-production.md` §3.5
  + Henrik Audit-Punkt J — the first **28 days after** the
  Aufsichtsrat-approved cutover, during which Gate-3-4 enforces
  per-day floor on functional-equivalence and zero SLO excursions.
* **V-907 pin-stability window** — `phase-3-production.md` §3 SLI
  row — rolling 28d, zero-tolerance for V-907 pin-drift events.
  Operates as both a pre-cutover and post-cutover invariant.

The skeleton-test `test_gate_3_4_28d_no_regression` exercises the
**post-cutover** flavour. The pre-trigger checklist items 1, 2, 4
above exercise the **pre-cutover** windows. The §5 invariants in
`phase-3-production.md` exercise the **rolling-28d** flavour.

Zone-N cross-review with Henrik (item 10) explicitly disambiguates
which "28d" applies to which Audit-Sample row, so the Audit-Punkt
ingest is not confused.

## 4. Sign-off block (populated at sprint-trigger time)

```
Pre-Trigger Checklist Sign-Off
------------------------------
Amara (QA):     ____________________  date: ____________
Priya (CTO):    ____________________  date: ____________
Henrik (Audit): ____________________  date: ____________
Mira (CEO):     ____________________  date: ____________

10-item-checklist status snapshot:
  [ ] 1.  Phase-2 acceptance-gates green ≥ 14d
  [ ] 2.  Persona-Container up ≥ 99.9% / 30d
  [ ] 3.  Bridge-Forward drop-rate ≤ 0.01% / 24h, no 14d excursions
  [ ] 4.  V-907 pin-drift = 0 / 28d
  [ ] 5.  Rust replay-tape corpus frozen (15 vectors)
  [ ] 6.  Rust ⇆ Python ≥ 14/15 hermetic parity
  [ ] 7.  OTS end-to-end p99 ≤ 60s / 7d
  [ ] 8.  Phase-3a Module-Readiness matrix signed off
  [ ] 9.  Rollback-runbook drill in trailing 30d, ≤ 15min
  [ ] 10. Zone-N Phase-3-trigger review scheduled, findings addressed

Skeleton-suite opt-in verified:
  WAKIR_PHASE_3_SKELETON=1 pytest -m phase_3_skeleton \
    tests/infra/test_phase_3_acceptance_gates.py
  Expected: 6/6 tests passing.
```

— Amara
