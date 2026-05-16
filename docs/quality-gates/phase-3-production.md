# Quality-Gate — Phase 3 (Production)

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Draft for Phase-2 → Phase-3 cutover preparation |
| Phase | 3 — Production (wakir-Tomás-Container is authoritative; Pre-Framework-Tomás is decommissioned or runs in observe-only fallback) |
| Source | ADR-0058 §"Phase 4 Cutover-Entscheidung", ADR-0055 |
| Date approved | 2026-05-16 (draft; entry from Phase-2 still 6 weeks out by stable schedule) |

## 0. Phase contract

Phase 3 begins when the ADR-0058 cutover-decision-artefact has been
approved by the Aufsichtsrat (governance decision, gated on the
Phase-2 acceptance-gates per `phase-2-doppelbetrieb.md` §5).

In Phase 3:

* `wakir-persona-tomas.service` is the authoritative
  Tomás-Persona-Container (the Pre-Framework-Tomás-spawn is either
  decommissioned or runs in *observe-only* fallback for emergency
  rollback).
* The Doppelbetrieb-Score-CLI continues to run if Pre-Framework-Tomás
  is in observe-only fallback, but is **non-blocking** (the wakir-
  Tomás output is authoritative, the Pre-Framework output is the
  audit-comparator only).
* New persona-migrations follow the same ADR-0058 pilot →
  doppelbetrieb → production lifecycle; this document is the
  template for future personas.

## 1. Acceptance-Gates

### 3.1 All Phase-2 gates remain green for production-traffic

* **Gate:** Every gate from `phase-2-doppelbetrieb.md` §1 still
  passes, with the wakir-Tomás-Container now load-bearing.
* **Owned-by:** Amara (enforcement), Selin (engine), Noa (substrate).

### 3.2 Rollback-runbook drill cleared

* **Gate:** The Phase-2 → Phase-3 emergency-rollback runbook
  (revert authoritative back to Pre-Framework-Tomás) has been
  executed against a Pilot-VM at least once in the 30 days
  preceding cutover, with a measured rollback-time ≤ 15 minutes.
* **Evidence:** Runbook-drill report signed off by Noa and Aisha.
* **Owned-by:** Noa (runbook) + Aisha (drill moderation).
* **Test-Vector:** This is a runbook-drill, not a hermetic test.
  QA-evidence is the drill-report; not a pytest entry.

### 3.3 V-907 / OTS audit-trail end-to-end

* **Gate:** Every Tomás-Persona-Container spawn in the 30 days
  preceding cutover has a complete OTS-anchored audit-trail (axis-A
  pin → V-907 verify → engineering-output → reply-publish), with
  zero gaps in the audit-chain.
* **Evidence:** OTS audit-trail Merkle-root reconciliation report
  (Tomás-owned).
* **Owned-by:** Tomás (WAT/OTS) + Henrik (audit).

### 3.4 Recovery-drill green on production substrate

* **Gate:** The OI-PEF-11 recovery-drill (per Sprint-Pengine-7
  schema-registry entry `recovery_drill_outcome`) has been executed
  against the production substrate at least once in the 14 days
  preceding cutover, with `outcome == "pass"`.
* **Evidence:** `recovery-drill-anchor` Quadlet log + signed
  outcome-record.
* **Owned-by:** Selin + Noa.

### 3.5 No regressions vs. Phase-2 baseline

* **Gate:** Output quality (functional-equivalence ≥ 0.95 vs.
  Phase-2 baseline) and substrate stability (Phase-2 SLOs) maintained
  for first 28 days post-cutover.
* **Evidence:** Post-cutover Doppelbetrieb-Score weekly rollup
  + Noa SLO-rollup.
* **Owned-by:** Amara + Selin + Noa.

## 2. Test-Coverage thresholds

Inherits all Phase-1b and Phase-2 thresholds. No new Phase-3-specific
component-coverage thresholds (Phase-3 promotes existing components
to production-authoritative; it does not introduce new components).

Phase-3-specific thresholds at the **end-to-end** test level:

| Component | Test-vector count | Source |
|---|---|---|
| Production-traffic E2E happy-path (full lifecycle on production substrate) | ≥ 5 distinct auftrag-classes | Amara |
| Emergency-rollback runbook drill | ≥ 1 successful drill in last 30d | Noa |
| Recovery-drill (OI-PEF-11) | ≥ 1 successful run in last 14d | Selin+Noa |

## 3. SLI/SLO requirements (coordination with Noa SRE)

Phase 3 SLOs are **production-grade** — tighter than Phase 2:

| SLI | Window | SLO | Owner |
|---|---|---|---|
| Output-reply timeliness p99 (publish → reply) | rolling 1h | ≤ 30s | Noa |
| Bridge-Forward fan-out drop-rate (if Pre-Framework still observe-only) | rolling 24h | ≤ 0.01% | Noa |
| Persona-Container `up` (Quadlet active) | rolling 30d | ≥ 99.9% | Noa |
| V-907 pin-drift event count | rolling 28d | 0 (zero-tolerance) | Noa+Selin |
| Recovery-drill `outcome == pass` rate | rolling 90d | ≥ 95% | Noa+Selin |

Coordination note (vorläufig per P2): Phase-3 SLO numbers are
production-target placeholders. Noa-design-review remains a Phase-2
→ Phase-3 promotion-prerequisite (gate §5.3 in
`phase-2-doppelbetrieb.md`).

## 4. Henrik-Audit-Punkte (Zone N)

Henrik's Audit-Sample for Phase 3 consumes everything from Phase-1b
and Phase-2 plus:

* **H.** The full OTS audit-trail Merkle-root reconciliation report
  (Tomás-owned) — full audit, not sample.
* **I.** The Aufsichtsrat-approved cutover-decision-artefact.
* **J.** The post-cutover 28-day stability report
  (output-quality + substrate-stability + recovery-drill).
* **K.** Any Phase-3 incident-post-mortems (full audit).

Henrik does **not** consume:

* Per-output Doppelbetrieb diffs (sample only).
* Live SLI dashboards (Noa-domain).

## 5. Cross-phase invariants

The following invariants hold across all three phases. They are
**not** phase-gates per-se but each phase-gate must be consistent
with them:

* **No-regret-test-evidence rule:** every test-vector in
  Phase 1b's suite that passes Phase 1b must continue to pass in
  Phase 2 and Phase 3 (no retrofit erosion).
* **Bug-vector classification completeness:** every smoke-check
  the acceptance-gate maps must trace to at least one bug-class
  in `feedback_live_bringup_sandbox_gap`. If a future live-bug
  surfaces that the gate did not classify, QA opens a follow-up
  PR to extend the CHECK_TO_BUGS map within 7 days.
* **V-907 pin-attest is mandatory at every container spawn** —
  removing this gate at any phase requires a new ADR and is **not**
  a QA-discretionary call.
* **Quality-Gate document edits require Zone-N cross-review** —
  Amara cannot unilaterally relax a gate; Henrik signs off via the
  Zone-N quarterly review (or ad-hoc if a gate-relaxation is
  proposed mid-quarter).

— Amara
