# Quality-Gate — Phase-3-Marathon-Schluss-Acceptance Definition-of-Done

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Draft — pending Phase-3c-Welle-Marathon execution (ADR-0066 four-Wochen-Cadence KW-24 -> KW-27) |
| Phase | 3 (closing): end-to-end marathon-sequence Definition-of-Done |
| Source | Tag-43 Amara Auftrag (Continuous-Mode, 2026-05-18); ADR-0066 §Beschluss + §Wochen-Plan; ADR-0065 §Verifikations-Plan + §Welle-Ende-Acceptance; ADR-0058 §Phase-3; Henrik Tag-39 Welle-6+7 Pre-Audit-Bundle (IIA-1130 anchor); `.github/workflows/phase-3-complete-marker.yml` (AC-1..AC-5 emit-gate) |
| Date | 2026-05-18 (creation, Tag-43 marathon-schluss spawn) |
| Test-File | `tests/phase_3c/test_marathon_schluss_acceptance_drill.py` |
| Companion (aggregate state-machine) | `tests/phase_3c/test_phase_3_final_regression.py` (Tag-40) |
| Companion (per-day walkthrough) | `tests/phase_3c/test_cutover_day_e2e_drill.py` (Tag-41) |
| Companion (DW-6+7 acceptance) | `tests/phase_3c/test_doppel_welle_6_7_acceptance.py` (Tag-39) |
| Companion (marker workflow) | `.github/workflows/phase-3-complete-marker.yml` (Tomás Tag-40) |
| Companion (audit-spec) | `agents-workspaces/internal-audit/outbox/2026-05-18-welle-6-7-pre-audit-bundle.md` (Henrik) |

## 0. Contract scope

This document is the **end-to-end marathon-sequence** Definition-of-
Done for the Phase-3c-Welle-Marathon: replaying the four-Wochen-
Cadence (KW-24 -> KW-27) in chronological order, threading per-day
sign-off-records into per-KW bundles, threading the bundles into the
Phase-3-COMPLETE-marker AC-1..AC-5 conjunction, and threading the
green marker into the Phase-3-Marathon-Bilanz-Trigger.

The Phase-3-Acceptance pyramid is the three-suite stack:

| Layer | Suite | Owner | Contract |
|---|---|---|---|
| 1 — State-Machine | `test_phase_3_final_regression.py` (Tag-40) | Amara | Given seven sign-off-records, does the Phase-3-COMPLETE-marker fire? |
| 2 — Per-Day | `test_cutover_day_e2e_drill.py` (Tag-41) | Amara | Does one Cutover-Mittwoch produce a correctly-shaped sign-off-record? |
| 3 — Marathon | `test_marathon_schluss_acceptance_drill.py` (Tag-43, this doc) | Amara | Does the four-Wochen-Sequence thread the per-day records into the AC-1..AC-5 conjunction, fire the marker, fire the Bilanz-Trigger? |

The three suites are **complementary, not substitutive**. None of the
three replaces the live-VM-acceptance-lane (operator-hand-territory,
ADR-0058 §Nachtrag).

## 1. The four-KW marathon-sequence (KW-24 -> KW-27)

Per ADR-0066 §Wochen-Plan:

| KW | Pattern | Wellen | Modul(e) | Notes |
|----|---------|--------|----------|-------|
| KW-24 | Doppel-Welle-1+2 (parallel) | 1, 2 | `v907_verify`, `svid_workload_identity` | Shared cutover-ISO + signoff-ISO; risk-class lowest/low |
| KW-25 | Solo-Welle-3 | 3 | `bridge_audit_writer` | Henrik-Caution risk-class; pre-audit-path |
| KW-26 | Doppel-Welle-4+5 (parallel) | 4, 5 | `state_backing`, `lifecycle_state_machine` | Symmetric A7-cross-modul-drift expectation |
| KW-27 | Doppel-Welle-6+7 (parallel) | 6, 7 | `subscribe_loop`, `recovery_workflow` | Phase-3-Schluss-slot; IIA-1130 Welle-7-Pre-Auditor-Decision required |

Per-KW timestamps (ADR-0066 four-Wochen-Cadence, mirrors Tag-40
`MARATHON_TRACE_TIMESTAMPS`):

| KW | Cutover-Mittwoch | Cross-Review-Donnerstag | Sign-Off-Freitag |
|----|------------------|-------------------------|------------------|
| KW-24 | 2026-06-10 09:00 CEST | 2026-06-11 14:00 CEST | 2026-06-12 17:00 CEST |
| KW-25 | 2026-06-17 09:00 CEST | 2026-06-18 14:00 CEST | 2026-06-19 17:00 CEST |
| KW-26 | 2026-06-24 09:00 CEST | 2026-06-25 14:00 CEST | 2026-06-26 17:00 CEST |
| KW-27 | 2026-07-01 09:00 CEST | 2026-07-02 14:00 CEST | 2026-07-03 17:00 CEST |

## 2. Phase-3-COMPLETE-Marker AC-1..AC-5 conjunction

The marker emits **only on the Boolean conjunction** of AC-1..AC-5
(per `.github/workflows/phase-3-complete-marker.yml` §Emit-step
predicate):

| AC | Anchor | Source artefact | Gate |
|----|--------|-----------------|------|
| AC-1 | Seven welle-sign-offs | `state/welle-{1..7}-sign-off.json` | All seven present, status in `{green, yellow_henrik_hand_approval}` |
| AC-2 | Aggregate validation | `phase-3c-welle-{1..7}-validation.yml` on main HEAD | All seven workflows `conclusion=success` |
| AC-3 | Predecessor closure | `state/phase-3{a,b,c}-closure.json` | 3a=15, 3b=9, 3c=7 attested |
| AC-4 | Henrik R-A1..R-A6 ratification | `state/henrik-phase-3-complete-ratification.json` | `aggregate_verdict="ratified"` |
| AC-5 | AR-Hand stamp (IIA-1130) | `state/ar-hand-phase-3-complete-stamp.json` | `ar_hand_ratification=True` + non-empty `ar_hand_quote` |

**IIA-1130 anchor (AC-5):** Per Henrik Spec §3 Pt-5, the marker
setting is mechanical-executive (workflow emits the file); Internal
Audit RATIFIES (AC-4), AR-Hand RATIFIES FINAL (AC-5). At no point is
Internal Audit the marker-actor.

## 3. The IIA-1130 Welle-7-Pre-Auditor-Decision

Per Henrik Tag-39 Welle-6+7-Pre-Audit-Bundle:

> Welle-7 sign-off triggers the Phase-3-COMPLETE-marker workflow. If
> Internal Audit ratified marker-setting as an active step, that
> would impair IIA-1130 independence. The AR-Hand-Pre-Auditor-
> Decision at the Welle-7-cutover-day is the substitute control: AR
> decides Pre-Auditor on the cutover-Mittwoch; AR-Hand-stamp
> ratifies post-marker-emit.

Artefacts:

* `state/welle-7-pre-auditor-decision.json` — AR-Hand decision on
  Welle-7 cutover-day, surfacing `decision_present`, `decision_id`,
  `ar_hand_signature`, `iia_1130_independence_anchor`.
* `state/ar-hand-phase-3-complete-stamp.json` — AR-Hand final
  ratification of the Phase-3-COMPLETE-marker, surfacing
  `ar_hand_ratification`, `ar_hand_quote` (AC-5).

The Tag-43 test-suite enforces both artefacts as part of the marathon-
sequence green-path. Missing either => marker MUST NOT fire.

## 4. Anti-False-Positive contract (NEG-axis)

The marker MUST NOT fire under any of the following conditions
(walked symmetrically across all relevant permutations):

| Condition | Failing gate |
|---|---|
| Welle-3 rolls back | Cascade-block (state-machine) + AC-1 (downstream wellen pending) |
| Welle-7-Pre-Auditor-Decision missing | KW-27 bundle `is_green=False` + AC-5 quote empty |
| Cross-modul drift Welle-4↔5 > 0 (blocker) | State-machine drift-aggregation `"blocker"` |
| 6/7 sign-offs (any one missing) | AC-1 fails (count != 7) |
| KW-26 partial Doppel-Welle sign-off | KW-26 bundle `is_green=False` + AC-1 (count=6) |
| AC-4 Henrik aggregate_verdict="blocked" | AC-4 fails (Bilanz-Trigger surfaces "AC-4") |
| AC-5 AR-Hand-quote empty/whitespace | AC-5 fails (IIA-1130 anchor broken) |

The test-suite walks each branch and confirms (a) the marker does
not fire, and (b) the Bilanz-Trigger does not fire, and (c) the
failing AC IDs are surfaced in `blocking_reasons`.

## 5. Phase-3-Marathon-Bilanz-Trigger

Once the Phase-3-COMPLETE-marker is set green, the **Phase-3-
Marathon-Bilanz-Trigger** fires. The trigger is the input-event for
the Noa Tag-43 Phase-3-Bilanz-Generator (pre-spawn this doc is the
contract anchor).

Trigger payload schema (`BilanzTrigger` dataclass, pure-fn derivation
from marathon + AC-1..AC-5):

```python
@dataclass(frozen=True)
class BilanzTrigger:
    fires: bool
    marker_iso: str = ""
    kw_24_signoff_iso: str = ""
    kw_25_signoff_iso: str = ""
    kw_26_signoff_iso: str = ""
    kw_27_signoff_iso: str = ""
    welle_signoff_count: int = 0
    blocking_reasons: Tuple[str, ...] = ()
```

Firing rules:

* `fires=True` iff AC-1..AC-5 all green.
* If `fires=False`, `blocking_reasons` carries the failing AC IDs
  (e.g. `("AC-1", "AC-5")`).
* `marker_iso` is the workflow-emit-time of `state/phase-3-complete-
  marker.json`; chronologically after `kw_27_signoff_iso`.
* `welle_signoff_count` mirrors the AC-1 count (7 on green).
* The four `kw_*_signoff_iso` fields carry the per-KW sign-off-
  Freitag-ISOs (per §1 §1 table).

## 6. Zone-N coordination with Internal Audit

Per ADR-0044 §Zone-N (Amara-Henrik boundary):

* QA-evidence here is **complementary** to Henrik's audit-sample.
  The test-suite is *not* a substitute for Henrik's Welle-6+7-Pre-
  Audit-Bundle, the Cutover-Day-Audit-Sample, or the Aggregate-
  Phase-3-Schluss-Audit-Spec.
* The marker-emit-event is **AR-Hand-ratified**, not Henrik-
  ratified (IIA-1130 anchor). Henrik retains independent sampling
  rights on the rollback-cascade audit-trail.
* Henrik's Welle-7-Pre-Auditor-Decision sample at Welle-7 cutover-
  day consumes the `Welle7PreAuditorDecision` shape this file
  carries as the contract-anchor surface.

## 7. Acceptance criteria (Definition-of-Done)

The Tag-43 Marathon-Schluss-Acceptance Definition-of-Done is met
when:

1. `tests/phase_3c/test_marathon_schluss_acceptance_drill.py` exists
   and passes all 20 tests across MAR, AC15, NEG, BIL, DOC axes.
2. The test-file imports the Tag-40 `Phase3CompleteMarkerStateMachine`
   and Tag-41 `CUTOVER_DAY_DRILL_SCHEDULE` as companion-module
   constants, keeping the three suites in contract-lock-step.
3. The five conjunctive AC-1..AC-5 acceptance criteria are mirrored
   one-for-one against the `.github/workflows/phase-3-complete-
   marker.yml` emit-step predicate.
4. The Bilanz-Trigger contract surfaces every KW sign-off-ISO + the
   marker-emit-ISO; pre-Noa-spawn this dataclass is the canonical
   input-event schema.
5. The IIA-1130 Welle-7-Pre-Auditor-Decision is enforced as a
   gating artefact for the KW-27 bundle.
6. This Definition-of-Done document is present at
   `docs/quality-gates/phase-3-marathon-schluss-acceptance.md` and
   references AC-1..AC-5 + IIA-1130 by ID (asserted by DOC-axis
   tests).

## 8. Open follow-ups

* **Noa Tag-43 Bilanz-Generator** — once the Noa-side generator is
  spawned, this file's `BilanzTrigger` dataclass migrates from
  test-side contract-anchor to canonical input-event module (likely
  `wakir-runtime/observability/phase_3_bilanz_trigger.py`).
* **Tomás Tag-43 marker-workflow substance** — once the marker-
  workflow's AC-4 + AC-5 file-readers land, this file's
  `HenrikRatification` and `ArHandStamp` dataclasses migrate from
  test-side contract-anchor to canonical state-file readers.
* **Henrik Welle-7-Pre-Auditor-Decision audit-spec** — Henrik's
  Tag-43 Audit-Spec for the Welle-7-cutover-day Pre-Auditor-Decision
  will consume the `Welle7PreAuditorDecision` shape; the shape
  should remain in lock-step.

— Amara Osei (QA), 2026-05-18
