---
title: "Operator-Hand Welle-7 Day-of-Recipe-Patch (Tag-75)"
status: "active"
owner: "kai"
audience: "operator,ar,engineering,internal-audit"
created: "2026-05-19"
tag: "tag-75"
predecessors:
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
  - "docs/operations/operator-hand-welle-3-eve-recipe-patch.md"
  - "docs/operations/operator-hand-welle-5-eve-recipe-patch.md"
  - "docs/operations/operator-hand-welle-6-eve-recipe-patch.md"
  - "docs/operations/phase-3c-welle-7-runbook.md"
  - "docs/operations/g1-g2-last-mile-operator-checklist.md"
  - "docs/ci/welle-7-hot-spot-probe-runbook.md"
related_adrs:
  - "ADR-0065"
  - "ADR-0066"
related_docs:
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
  - "docs/operations/operator-hand-welle-3-eve-recipe-patch.md"
  - "docs/operations/operator-hand-welle-5-eve-recipe-patch.md"
  - "docs/operations/operator-hand-welle-6-eve-recipe-patch.md"
  - "docs/operations/phase-3c-welle-6-runbook.md"
  - "docs/operations/phase-3c-welle-7-runbook.md"
  - "docs/ci/welle-7-hot-spot-probe-runbook.md"
  - "docs/operations/phase-3c-cutover-runbook.md"
  - "docs/quality-gates/pre-cutover-acceptance-run-order.md"
  - "docs/quality-gates/phase-3-marathon-final-acceptance.md"
related_prs:
  - "#469"
related_memory:
  - "Welle-7 ist terminal-propagation-target Hot-Spot UND Final-Sealing-Welle der Phase-3c (Henrik Tag-39 Welle-6+7-Pre-Audit-Bundle; original IIA-1130-Fall). Post-Welle-7 fires Layer-1-full + Layer-3-full + Live-Verify-Gate als Global Acceptance-Verdict (pre-cutover-acceptance-run-order.md §3.2, §5.4, §7.2). Recovery-Drill-Live + IIA-1130-Pre-Auditor-Decision-Tracking erfordern chirurgische Patch-Lage; Standard-Welle-Pattern reicht nicht. KW-27-Doppel-Welle (Partner Welle-6) handhabt Cross-Modul-Stress out-of-band (Asymmetrie zu KW-26)."
---

# Operator-Hand Welle-7 Day-of-Recipe-Patch

**Tag-75 Companion-Doc** zum Tag-66 Eve-Recipe-Konsolidat. Welle-7
(`recovery_workflow` / `persona-engine-recovery` + `persona-engine-
recovery-replay`) ist die vierte Welle in der Phase-3c-Marathon-
Sequenz mit **Pre-Auditor-Section-11-Disziplin** (IIA-1130) -- nach
Welle-3 (Tag-71-Patch), Welle-5 (Tag-73-Patch) und Welle-6 (Tag-74-
Patch). Welle-7 ist zugleich die **Final-Sealing-Welle der Phase-3c**:
post-Welle-7 fires die Global Acceptance-Verdict-Aggregation (Layer-
1-full + Layer-3-full + Marathon-Final-Acceptance-Live-Verify-Gate)
nach `docs/quality-gates/pre-cutover-acceptance-run-order.md` §3.2 +
§5.4 + §7.2. Anders als Welle-3/5/6 (Hot-Spots mit downstream-
Propagation) ist Welle-7 **terminal**: zwei verschraenkte Hot-Spots
schliessen den Marathon-Lauf ab, und ein roter Pre-Auditor-Verdict
hier blockiert direkt das Phase-3-COMPLETE-Marker-Fire:

* **Recovery-Drill-Live** -- Henrik Tag-44 + Tag-45 Pre-Mortem-
  Mitigation-Map identifiziert Welle-7 als terminal-propagation-
  target Hot-Spot mit Recovery-Drill-Live als worst-case Signalklasse.
  Static R1..R4 hermetic suite landete bis Tag-48; das Cutover-
  Window benoetigt eine Live-Drill-Variante gegen live state-
  backing snapshots. Drift zwischen canonical-trace und live-replay-
  outcome bedeutet, die Produktions-Recovery-Story bricht beim Bedarf.
* **IIA-1130-Pre-Auditor-Decision-Tracking** -- Welle-7 ist der
  Original-IIA-1130-Fall (Henrik Tag-39 Welle-6+7-Pre-Audit-Bundle).
  Der Audit-Stream-Contract-Author kann das Recovery-Story-Substrat
  nicht selbst zertifizieren; ein AR-designierter externer Pre-
  Auditor ist mandatorisch und ist hier zugleich Final-Sealing-
  Sign-off-Authority fuer die Phase-3-COMPLETE-Marker-Auspraegung.

Anders als bei Welle-3/5/6 (Hot-Spots mit downstream-Propagation in
die naechste Welle hinein) ist **Welle-7 die letzte Welle**: ein
Pre-Auditor-REJECTED hier propagiert nicht in eine Welle-8 (es gibt
keine), sondern direkt in den **Phase-3-COMPLETE-Marker-NO-FIRE-
Pfad** -- mit unmittelbarer Konsequenz fuer das Marathon-Endergebnis
und den ADR-0066-Cutover-Abschluss.

Daher ist das Standard-Welle-Pattern (Stand-up -> Welle-Merge ->
Stability-Check -> Welle-Smoke -> Dashboard-Update -> AR-Sign-off)
fuer Welle-7 **nicht hinreichend**: vor dem Welle-Merge muessen vier
zusaetzliche **Pre-Auditor-Signaling-Schritte** P1..P4 die Operator-
Hand passieren, und nach dem Welle-Merge ein fuenfter Post-Sign-off-
Step P5 mit **Final-Sealing-Spezifika** (Global-Verdict-Aggregation +
Phase-3-COMPLETE-Marker-Gate).

## Scope und Abgrenzung

Diese Doc ist **kein Ersatz** fuer das Tag-66 Eve-Recipe, das
phase-3c-welle-7-runbook oder die Welle-3/5/6-Recipe-Patches (Tag-71
+ Tag-73 + Tag-74). Sie ist eine **chirurgische Patch-Lage** ueber
dem Welle-7-Day-Section des Tag-66 Eve-Recipes (§4.6 dort, post-ADR-
0066-revidierter KW-27-Doppel-Welle-Schedule) und ueber dem phase-3c-
welle-7-runbook (Step 3, Welle-7-Validation-Workflow).

Die Patch-Lage besteht aus:

* **Welle-7-Day Pre-Sequence P1..P4** -- vier Pre-Auditor-Signaling-
  Schritte, jeweils mit Owner, Action, Stop-on-Fail, Verdict-Marker,
  die **vor** dem Standard-Welle-Stand-up (06:00 CEST) liegen
  muessen.
* **Welle-7-Day Post-Sequence P5** -- ein Post-Sign-off-Step der
  **nach** dem Standard-AR-Sign-off (12:00 CEST) den Pre-Auditor-
  Final-Sealing-Decision-File commitet, das Recovery-Drill-Live-
  Substrate re-verifiziert, **die Global Acceptance-Verdict-
  Aggregation triggert** und entweder das Phase-3-COMPLETE-Marker-
  Fire freigibt oder den NO-FIRE-Pfad eskaliert.

## Zeit-Domain

Welle-7 hat einen konvergenten Anker, post-ADR-0066-revidiert und
durch den Tag-57 Pre-Cutover-Acceptance-Run-Order-Doc kanonisiert:

| Anker | Date | Quelle |
|---|---|---|
| ADR-0066 §Welle-Sequenz (Doppel-Welle KW-27) | KW-27 Mi 2026-07-01 | ADR-0066 Welle-6+Welle-7 parallel |
| Pre-Cutover-Acceptance-Run-Order (Tag-57) §3 Table | KW-27 Mi 2026-07-01, Sign-off-Freitag 2026-07-03 | Amara Tag-57 canonical run-order map |
| Tag-66 Eve-Recipe §4.6 (vor ADR-0066) | T0+6 (alter Plan) | Tag-66 Marathon-Plan, **superseded** |
| Brief Tag-75 Auftrag | KW-27 Mi 2026-07-01 | Continuous-Mode-Spawn-Anker (ADR-0066- und Tag-57-konform) |

**Operativer Schluss**: Welle-7-Day-Datum ist konvergent (KW-27-Mi,
2026-07-01, post-ADR-0066, Tag-57-bestaetigt). Diese Patch-Lage gilt
unverruechlich an diesem Anker, mit der zusaetzlichen Constraint,
dass die KW-27-Doppel-Welle (Welle-6+Welle-7) zwei parallel laufende
Recipe-Patches benoetigt (Welle-6 hat eigene Patch-Lage in Tag-74;
Welle-7 ist diese Doc).

Der Pre-Auditor-Designation-Step (P1) muss **mindestens 48 h vor**
dem Welle-7-Day landen, damit der Pre-Auditor-Review realistisch ist.
Wegen der Final-Sealing-Rolle ist die Designation-Frist nicht
verhandelbar -- ein P1-HOLD fuehrt zur Phase-3-Marathon-Schluss-
Verschiebung mit ADR-0066-Cadence-Konsequenz.

## Pre-Auditor-Section-11-Hintergrund (IIA-1130)

Henrik Tag-39 Welle-6+7-Pre-Audit-Bundle, Tag-44 Pre-Mortem
(`agents-workspaces/mira/inbox/2026-05-18-henrik-tag-44-pre-mortem-
done.md`) und Tag-45 Mitigation-Map-Deep-Dives identifizieren Welle-7
als terminal-propagation-target Hot-Spot UND Original-IIA-1130-Fall
mit zwei verschraenkten Self-Reference-Risiken:

* **Recovery-Drill-Live-Self-Reference (Welle-7-spezifisch)**: der
  Recovery-Workflow konsumiert R1..R4 canonical-traces als Replay-
  Input, die er selbst emittieren koennte. Reviewer der Recovery-
  Logik ist nicht unabhaengig vom Recovery-Replay-Substrate. Live-
  Drill-Variante verschaerft das Risiko: drift zwischen canonical
  trace und live replay outcome ist nur erkennbar, wenn der Drill
  **gegen einen Live-State-Backing-Snapshot** laeuft, der NICHT vom
  Recovery-Workflow selbst produziert wurde.
* **IIA-1130-Self-Certification-Prohibition (Welle-7 Original-Fall)**:
  der Audit-Stream-Contract-Author kann die Recovery-Story nicht
  selbst zertifizieren -- das ist der Originaltext der IIA-1130-
  Impairment-to-Independence-Klausel. Welle-7 war der erste Welle,
  fuer den Henrik (Tag-39) explizit einen externen Pre-Auditor
  designierte. Welle-3, Welle-5 und Welle-6 sind Folge-Faelle der
  gleichen Klausel; Welle-7 ist der Praezedenzfall.

IIA-1130 "Impairment to Independence or Objectivity" verbietet, dass
die Cutover-Entscheidung -- **und insbesondere die Final-Sealing-
Sign-off-Entscheidung** -- von einem Reviewer kommt, der gleichzeitig
Co-Eigner eines der beiden Cutover-Substrate ist.

Daraus folgt: die Welle-7-Day-Sign-off-Entscheidung kann **nicht**
vom Standard-AR-Pair-Mode allein getragen werden. Sie braucht einen
externen Pre-Auditor, der von der AR-Hand designiert wird, dessen
Mandat sowohl Recovery-Drill-Live als auch IIA-1130-Pre-Auditor-
Decision-Tracking umfasst, dessen Sign-off als hard-pass-
Voraussetzung neben dem AR-Pair-Sign-off steht, und dessen P5-
Final-Sealing-Decision das Phase-3-COMPLETE-Marker-Fire freigibt
(oder ablehnt).

## §1 -- Pre-Sequence P1..P4 (vor 06:00 CEST am Welle-7-Day)

### P1 -- Pre-Auditor-Designation-Verify

**Time-Window**: 48 h vor Welle-7-Day (= ab Montag 2026-06-29 06:00
CEST), taegliches Re-Check bis Welle-7-Day-Morning 05:00 CEST.

**Action**: verify `state/welle-7-pre-auditor-decision.json` exists,
parses, has `auditor_role: "external-pre-auditor"`, `welle: 7`,
`hot_spot_axes: ["recovery-drill-live", "iia-1130-pre-auditor"]`,
`decision` field is one of {`PENDING`, `APPROVED`, `REJECTED`}, AND
includes `final_sealing_authority: true` (Welle-7-spezifisch: dieser
Pre-Auditor traegt das Phase-3-COMPLETE-Marker-Sign-off-Mandat). The
48-h-ahead window REQUIRES at minimum a `PENDING` entry naming the
designated external Pre-Auditor, listing both hot-spot axes, AND
flagging final-sealing-authority.

**Owner**: Operator-Hand (Mira).

**Stop-on-Fail**: `WELLE-7-P1-HOLD` -- Welle-7-Day-Sequence does NOT
start. Operator-Hand triggers AR-pair-mode escalation to fast-track
Pre-Auditor designation. Final-Sealing-Constraint: if P1-HOLD persists
past 24 h, Welle-7 falls out of the KW-27-Doppel-Welle, reschedules
to KW-28-Mo-solo, AND the Phase-3-Marathon-Schluss-target slips by
minimum 7 days with ADR-0066-Cadence-Konsequenz.

**Verdict-Marker**: `WELLE-7-P1-PRE-AUDITOR-DESIGNATED` (green),
`WELLE-7-P1-PENDING` (yellow, file present with PENDING decision,
both axes named, final-sealing-authority flagged), `WELLE-7-P1-HOLD`
(red, file missing, schema invalid, hot-spot-axes list incomplete,
or final-sealing-authority not flagged).

**Sandbox-OK**: yes, no merge-mutating action.

### P2 -- Pre-Auditor-Review-Window-Confirm

**Time-Window**: 24 h vor Welle-7-Day (= Dienstag 2026-06-30 06:00
CEST).

**Action**: confirm via AR-pair voice channel that the designated
Pre-Auditor has had a contiguous 24-h review window with access to:

* Welle-7 hot-spot probe last 7 daily envelopes
  (`.welle-7-hot-spot-probe/` artifacts).
* `state/welle-7-recovery-drill-live.json`.
* `state/welle-7-pre-auditor-decision.json` (with `final_sealing_
  authority: true`).
* `state/welle-7-validation-last-verdict.json`.
* Tag-39 Henrik Welle-6+7-Pre-Audit-Bundle (original IIA-1130
  designation context).
* Tag-44 Henrik Pre-Mortem document.
* Tag-45 Henrik Mitigation-Map-Deep-Dives document.
* Welle-7 Recovery-Drill-Live last 7 daily R1..R4 replay-traces
  (live-state-backing snapshots).
* phase-3c-welle-7-runbook §3 (Step 5 Render-Cutover-Acceptance-
  Decision with KW-27-Doppel-Welle partner Welle-6).
* `docs/quality-gates/pre-cutover-acceptance-run-order.md` §3.2 +
  §5.4 + §7.2 (Final-Sealing-context: Post-Welle-7 fires L1-full +
  L3-full + Live-Verify-Gate, Global Acceptance-Verdict).
* `docs/quality-gates/phase-3-marathon-final-acceptance.md`
  (Surface-1..5-conjunction for Phase-3-COMPLETE-marker).
* Welle-3-Recipe-Patch (Tag-71), Welle-5-Recipe-Patch (Tag-73), AND
  Welle-6-Recipe-Patch (Tag-74) as precedent templates (Pre-Auditor
  may not be the same person as any previous Pre-Auditor; if same,
  IIA-1120 conflict-of-interest declaration must be on file PLUS an
  AR-Hand-Override is mandatory for Welle-7 final-sealing-authority
  -- stricter than Welle-3/5/6 because the Final-Sealing-Sign-off
  is irreversible).

**Owner**: AR-pair (Mira moderates, AR-pair confirms voice-channel
contact).

**Stop-on-Fail**: `WELLE-7-P2-HOLD` -- Welle-7-Day defers by 24 h
(falls out of KW-27-Doppel-Welle to KW-27-Do-solo; if KW-27 fully
consumed, slips to KW-28-Mo-solo with Phase-3-Marathon-Schluss-
target slip). Re-attempt next morning.

**Verdict-Marker**: `WELLE-7-P2-REVIEW-WINDOW-CONFIRMED` (green),
`WELLE-7-P2-REVIEW-WINDOW-PARTIAL` (yellow, less than 24-h-contiguous
or missing access to one of the two hot-spot-state-files or to the
Final-Sealing-context-docs), `WELLE-7-P2-HOLD` (red, contact failed).

**Sandbox-OK**: yes.

### P3 -- Pre-Auditor-Decision-Receive

**Time-Window**: 04:30 -- 05:30 CEST on Welle-7-Day-Morning
(2026-07-01).

**Action**: receive the Pre-Auditor's signed decision file update
(APPROVED, REJECTED, or extended-PENDING). The decision file MUST
include `axis_verdicts: {recovery_drill_live: APPROVED|REJECTED,
iia_1130_pre_auditor: APPROVED|REJECTED}`. Both axis-verdicts must
be APPROVED for the aggregate `decision` to be APPROVED; asymmetric
verdicts (one APPROVED, one REJECTED) collapse to aggregate REJECTED.
The decision file MUST additionally include `final_sealing_intent:
"FIRE_PHASE_3_COMPLETE_MARKER" | "BLOCK_PHASE_3_COMPLETE_MARKER" |
"DEFER_FINAL_SEALING"` -- the Welle-7-spezifische Final-Sealing-
Authority-Direktive an die Global-Verdict-Aggregator-Helper. Operator-
Hand commits the updated `state/welle-7-pre-auditor-decision.json`
via a Mira-Hand-PR with explicit `pre-auditor-decision-update` AND
`final-sealing-intent` labels. The PR is **not auto-mergeable**: it
requires AR-pair sign-off as a sanity-check on the schema AND the
final-sealing-intent value before merge (stricter than Welle-3/5/6
PR-policy because the intent value pre-commits to a Phase-3-COMPLETE-
marker action).

**Owner**: Operator-Hand (Mira), AR-pair sanity-check.

**Stop-on-Fail**: `WELLE-7-P3-HOLD` -- if REJECTED, Welle-7-Day
becomes `WELLE-7-VERDICT-NO-GO` AND Phase-3-COMPLETE-marker becomes
`PHASE-3-COMPLETE-NO-FIRE-WELLE-7-BLOCK`; if PENDING extended past
06:00 CEST, Welle-7-Day defers by 24 h.

**Verdict-Marker**: `WELLE-7-P3-APPROVED` (green, both axes APPROVED,
final_sealing_intent in {FIRE_PHASE_3_COMPLETE_MARKER, DEFER_FINAL_
SEALING}, AR-pair-sanity passed, PR merged), `WELLE-7-P3-PENDING-
EXTENDED` (yellow, decision file PENDING with `deferred_until_utc`
field present), `WELLE-7-P3-AXIS-ASYMMETRIC` (yellow, one axis
APPROVED one REJECTED; collapses to NO-GO unless AR-Hand-Override
documented WITH explicit final-sealing-intent flag), `WELLE-7-P3-
HOLD` (red, aggregate REJECTED, final_sealing_intent invalid, or
PR-merge-fail).

**Sandbox-OK**: no (merge-mutating action; in dry-run, the PR is
created but not merged).

### P4 -- Pre-Auditor-Decision-Propagation-Check

**Time-Window**: 05:30 -- 06:00 CEST on Welle-7-Day-Morning.

**Action**: run the welle-7-hot-spot-probe-aggregator
(`tooling/ci/welle_7_hot_spot_aggregator.py`) and confirm Check-4
(IIA-1130-Pre-Auditor-Decision-Tracking) reports `green`. Confirm
that the aggregator emits `cross_welle_propagation` block as `null`
(terminal-Welle: no downstream propagation; the field is present in
the schema but always null for Welle-7 by design -- see aggregator
Terminal-Welle-propagation-note). Additionally confirm
`kw_27_doppel_welle.welle_6_partner_status` is `green|caution` (red
on the Welle-6 partner cascades into Welle-7-P4-HOLD because the
KW-27-cascade is directional Welle-6 -> Welle-7; a red Welle-6-
merged signals an upstream-substrate-defect that propagates into
Welle-7-Recovery-Workflow as Replay-Divergenz). Finally, confirm
the Global-Acceptance-Verdict-Aggregator dry-run
(`tooling/ci/aggregate_pyramide_run_order_verdict.py --welle 7
--dry-run`) reports `dry_run_global_verdict_reachable: true` -- a
pre-flight check that the Layer-1-full + Layer-3-full + Live-Verify-
Gate substrate ist intact and ready to fire post-merge.

**Owner**: Operator-Hand (Mira), Tomas (Matrix-Lead) reads artifact.

**Stop-on-Fail**: `WELLE-7-P4-HOLD` -- if Check-4 reports red/yellow,
Welle-7-Day stays on calendar but blocks at P4 until the upstream
state reconciles. If the Welle-6 partner is red, Welle-7 inherits
the cascade-block (KW-27-cascade directional Welle-6 -> Welle-7).
If the dry-run-Global-Verdict-Aggregator reports `dry_run_global_
verdict_reachable: false`, Welle-7-Day blocks until the L1/L3/Live-
Verify-Gate substrate is repaired (this is a Final-Sealing-Pre-
Flight-Check unique to Welle-7).

**Verdict-Marker**: `WELLE-7-P4-PROPAGATION-CLEAR` (green; note:
"propagation" is a misnomer for the terminal Welle but kept for
parallel-structure with Welle-3/5/6 markers; semantically green
means "Welle-6-partner-clear + dry-run-Global-Verdict-reachable"),
`WELLE-7-P4-PROPAGATION-YELLOW` (yellow, Welle-6-partner caution OR
dry-run-Global-Verdict-reachable-with-warning), `WELLE-7-P4-HOLD`
(red, Welle-6-partner red, dry-run-Global-Verdict not reachable, or
aggregator-Check-4 red).

**Sandbox-OK**: yes (probe + dry-run-aggregator are hermetic, no
side-effects).

## §2 -- Standard-Welle-7 Day-Sequence (06:00 -- 12:00 CEST)

After P1..P4 pass green, the Standard-Welle-Day-Sequence proceeds
**unchanged** from the Tag-66 Eve-Recipe §4.6 + phase-3c-welle-7-
runbook §3:

* **06:00 -- 06:30 CEST**: Stand-up.
* **06:30 -- 09:00 CEST**: Welle-7-Merge (per phase-3c-welle-7-
  runbook §3). In the KW-27-Doppel-Welle, Welle-6-Merge runs in
  parallel; merge-conflict-coordination is via the matrix-lead
  voice-channel.
* **09:00 -- 10:00 CEST**: Welle-1/2/3/4/5/6-Stability-Check (and
  Welle-6 partner stability, given Doppel-Welle).
* **10:00 -- 11:00 CEST**: Welle-7-Smoke + Welle-6-Smoke (parallel,
  per KW-27-Doppel-Welle).
* **11:00 -- 11:30 CEST**: Dashboard-Update.
* **11:30 -- 12:00 CEST**: AR-Sign-off.

**KW-27 Cross-Modul-Asymmetrie zu KW-26 (Welle-4+Welle-5)**: Im
Unterschied zur KW-26-Doppel-Welle (welche den Cross-Modul-Stress-
Test als sechsten inline-Step verlangt) handhabt die KW-27-Doppel-
Welle Cross-Modul-Drift **out-of-band** via Phase-2-Acceptance-Gate
daily rollup (siehe `docs/operations/phase-3c-welle-7-runbook.md`
§"KW-27 Doppel-Welle posture"). Die KW-27-Standard-5-Step-Sequence
enthaelt **keinen inline-Cross-Modul-Step**; statt dessen muss vor
06:00 CEST der Phase-2-Acceptance-Gate daily-rollup-Verdict mit der
Axe `cross-modul-subscribe-loop-recovery-workflow` auf green stehen.
Operator-Hand validiert diese Out-of-band-Axe als Teil von P4 (siehe
oben). Bei Ad-hoc-Bedarf laesst sich der Cross-Modul-Aggregator
manuell ausloesen:

```bash
python scripts/doppelbetrieb-score-aggregator.py \
    --mode cross-modul-stress \
    --out /tmp/kw27-cross-modul.json
```

## §3 -- Post-Sequence P5 (12:00 -- 13:00 CEST) -- Final-Sealing

### P5 -- Pre-Auditor-Final-Sealing-Sign-off-Commit

**Time-Window**: 12:00 -- 13:00 CEST on Welle-7-Day, after the
standard AR-Sign-off. **Welle-7-spezifisch: P5 ist Final-Sealing-
Step der Phase-3c-Marathon** -- nicht nur ein Post-Merge-Review,
sondern der formelle Trigger fuer die Global Acceptance-Verdict-
Aggregation und das Phase-3-COMPLETE-Marker-Fire (oder NO-FIRE-
Pfad-Eskalation).

**Action**: the designated external Pre-Auditor confirms the
post-merge state of Welle-7 (Welle-1/2/3/4/5/6/7-Stability-Check
green, Welle-7-Smoke green, Welle-6-Smoke green, Recovery-Drill-Live
indicator green, IIA-1130-Pre-Auditor-Tracking indicator green) and
updates `state/welle-7-pre-auditor-decision.json` with a final
`decision_finalised_at_utc` timestamp, `post_merge_review:
"clean|drift|defect"` field, `axis_post_merge: {recovery_drill_live:
clean|drift|defect, iia_1130_pre_auditor: clean|drift|defect}` field,
AND a final `final_sealing_decision: "FIRE_PHASE_3_COMPLETE_MARKER" |
"BLOCK_PHASE_3_COMPLETE_MARKER" | "DEFER_FINAL_SEALING"` field.
Operator-Hand commits via Mira-Hand-PR with `pre-auditor-final-
sealing-sign-off` label.

**Final-Sealing-Aggregation**: after the P5-PR merges, Operator-Hand
triggers the Global-Acceptance-Verdict-Aggregator
(`tooling/ci/aggregate_pyramide_run_order_verdict.py --welle global`)
which:

1. Reads per-Welle-verdicts for Welle-1..Welle-7.
2. Runs Layer-1-full (State-Machine aggregate marker-emit-gate).
3. Runs Layer-3-full (Marathon four-Wochen-sequence threading).
4. Runs the Marathon-Final-Acceptance-Live-Verify-Gate
   (`.github/workflows/marathon-final-acceptance-live-verify.yml`).
5. Cross-checks `final_sealing_decision` field from this P5-step.
6. Emits Global-Verdict (`GREEN|CAUTION|RED`) into
   `state/phase-3-marathon-global-verdict.json`.
7. If Global-Verdict is `GREEN` AND `final_sealing_decision ==
   FIRE_PHASE_3_COMPLETE_MARKER`: fires the Phase-3-COMPLETE-marker
   via `tooling/ci/fire_phase_3_complete_marker.py` (operator-hand-
   commit with `phase-3-complete-marker-fire` label).
8. If any disagreement (e.g. Global-Verdict GREEN but
   final_sealing_decision is BLOCK or DEFER): escalate to AR-Hand-
   tiebreak per IIA-1130-conflict-resolution-protocol.

**Owner**: External Pre-Auditor produces the artifact; Operator-Hand
(Mira) commits + triggers aggregator; AR-pair signs off on the
Final-Sealing-trigger.

**Stop-on-Fail**: `WELLE-7-P5-DRIFT` if any axis-post-merge reports
`drift`; the Final-Sealing-trigger pauses and the Recovery-Drill-
Live-watch is activated, plus a 24-h-Defer of the Phase-3-COMPLETE-
marker-fire pending AR-Hand-tiebreak. `WELLE-7-P5-DEFECT` if any
axis-post-merge reports `defect`; the Final-Sealing-trigger is
**blocked**, Henrik (Internal Audit) is notified for a Cross-Welle-
Hot-Spot-Re-Probe with explicit recovery-drill-live forensic focus,
and the Phase-3-COMPLETE-marker enters `PHASE-3-COMPLETE-NO-FIRE-
WELLE-7-DEFECT` state. `WELLE-7-P5-DISAGREE` if Global-Verdict and
final_sealing_decision disagree; AR-Hand-tiebreak per IIA-1130-
conflict-resolution-protocol decides.

**Verdict-Marker**: `WELLE-7-P5-CLEAN-FIRED` (green, both axes clean,
Global-Verdict GREEN, final_sealing_decision == FIRE, marker fired),
`WELLE-7-P5-CLEAN-DEFERRED` (green-yellow, both axes clean, Global-
Verdict GREEN, final_sealing_decision == DEFER -- pause-with-intent),
`WELLE-7-P5-DRIFT` (yellow, at least one axis drift), `WELLE-7-P5-
DEFECT` (red, at least one axis defect), `WELLE-7-P5-DISAGREE` (red,
Global-Verdict and final_sealing_decision disagree, AR-Hand-tiebreak
pending).

**Sandbox-OK**: no (commit-mutating action + marker-fire-action).

## §4 -- Welle-7-Day Aggregate Verdict-Roll-up

The aggregate Welle-7-Day verdict is computed from P1..P5 plus the
Standard-Welle-Day green-state PLUS the Final-Sealing-aggregation
outcome:

| All P1..P5 green + Welle-Day clean + Marker fired | -> `WELLE-7-VERDICT-CUTOVER-DONE-MARKER-FIRED` |
| All P1..P5 green + Welle-Day clean + Marker deferred | -> `WELLE-7-VERDICT-CUTOVER-DONE-MARKER-DEFERRED` |
| Any P-step yellow, all rest green | -> `WELLE-7-VERDICT-CAUTION` |
| P3 yellow (PENDING-EXTENDED) | -> `WELLE-7-VERDICT-DEFER-24H` |
| P3 yellow (AXIS-ASYMMETRIC, no override) | -> `WELLE-7-VERDICT-NO-GO` |
| P3 red (REJECTED) | -> `WELLE-7-VERDICT-NO-GO` |
| P4 yellow (Welle-6-partner-caution) | -> `WELLE-7-VERDICT-DOPPEL-DECOUPLE` |
| P5 red (DEFECT) | -> `WELLE-7-VERDICT-FINAL-SEALING-BLOCK` |
| P5 red (DISAGREE) | -> `WELLE-7-VERDICT-FINAL-SEALING-TIEBREAK` |
| Any other red | -> `WELLE-7-VERDICT-HOLD` |

The aggregate verdict is emitted to `state/welle-7-day-verdict.json`
and consumed by the marathon-dashboard-tile-emitter AND -- uniquely
for Welle-7 -- by the Phase-3-COMPLETE-marker-fire-gate (see §3 P5
Final-Sealing-Aggregation).

## §5 -- Rollback-Pfade (Welle-7-spezifisch)

Welle-7-spezifische Rollback-Pfade ergaenzen die fuenf generischen
R1..R5-Pfade aus dem Tag-66 Eve-Recipe §5. Anders als Welle-3/5/6
sind Welle-7-Rollbacks IRREVERSIBEL in der Marker-Konsequenz: ein
einmal gefeuerter Phase-3-COMPLETE-marker laesst sich nicht zurueck-
nehmen, sondern nur durch einen formalen Phase-3-RE-OPEN-ADR
revidieren.

### R-W7-A -- Pre-Auditor-Designation-Failure

**Trigger**: P1-HOLD persists past 48-h-window AND AR-Hand-
escalation cannot designate within 24 h. Or: designated Pre-Auditor
declares IIA-1120 conflict-of-interest after 24-h-window has begun.
Or: designated Pre-Auditor accepts mandate but declines `final_
sealing_authority` flag (Welle-7-spezifisch).

**Recovery**: defer Welle-7-Day by minimum 72 h. Falls out of KW-27-
Doppel-Welle; reschedules to KW-28-Mo-solo at earliest. Marathon-
Dashboard flips Welle-7-tile to `DESIGNATION-PENDING-FINAL-SEALING`.
Welle-6 either stays on calendar (if its own P1..P5 still green and
KW-27-cascade-directionality permits) or follows the de-couple-pfad
in its own Tag-74-Patch R-W6-D branch.

**Recovery-Time-Budget**: minimum 72 h (24 h re-escalation + 48 h
new review window). Final-Sealing-Constraint: Phase-3-Marathon-
Schluss-target slips by at minimum 7 days, with ADR-0066-Cadence-
Konsequenz dokumentiert in `state/phase-3-marathon-schluss-slip.json`.

**Fall-back-Pin**: Welle-7-component default backend stays `python`
(no flip). `WAKIR_RECOVERY_BACKEND` remains on Python-Recovery-
Workflow-resolver path. Welle-6 may proceed if its own substrate is
isolatable from the Welle-7-defer (per ADR-0066 substrate-coupling-
map; in practice the KW-27-cascade directionality biases Welle-6
into a partner-defer if Welle-7 is held back, but the decision is
operator-hand). Phase-3-COMPLETE-marker stays in `PHASE-3-COMPLETE-
NO-FIRE-WELLE-7-PENDING-DESIGNATION` state.

### R-W7-B -- Pre-Auditor-REJECTED-Decision (Aggregate or Axis or Final-Sealing-Intent)

**Trigger**: P3 receives an aggregate-REJECTED decision file, OR P3
receives an AXIS-ASYMMETRIC verdict (one axis REJECTED) without an
AR-Hand-Override on file, OR P3 receives a final_sealing_intent ==
"BLOCK_PHASE_3_COMPLETE_MARKER" decision (Welle-7-spezifisch: this
is a hard-block on the marker even if both axis-verdicts are
APPROVED, used for situations where the Pre-Auditor identifies an
extra-axis risk outside Welle-7's two named axes).

**Recovery**: invoke the Welle-7-Henrik-Audit-Loop -- Henrik
(Internal Audit) reviews the Pre-Auditor's rationale per axis
(recovery-drill-live and iia-1130-pre-auditor are reviewed
independently) PLUS the final_sealing_intent rationale (Welle-7-
spezifisch). If endorsed, the rejected axis substrate is re-
engineered per Henrik recommendations and a new Pre-Auditor-Review-
Cycle (P1..P5) re-runs. If contested, AR-Hand-Entscheidung breaks
the tie. Phase-3-COMPLETE-marker stays in `PHASE-3-COMPLETE-NO-FIRE-
WELLE-7-REJECTED` state.

**Recovery-Time-Budget**: 7..21 days (Henrik review + substrate
re-engineering + new review cycle). Recovery-Drill-Live re-
engineering may extend the budget by an additional 7 days if the
issue is in the live-state-backing-snapshot substrate (Reza Cross-
Review-Zone-A disziplin, identity/recovery interaction). If
final_sealing_intent is BLOCK, additional 7..14 days are
budgeted for the extra-axis-risk investigation (worst-case 28-day
slip).

**Fall-back-Pin**: Welle-7-component default backend stays `python`.
Welle-6 either also defers (cascade-block) or proceeds without
Welle-7-dependency (per ADR-0066 substrate-coupling-map; KW-27-
cascade directionality biases toward cascade-block but Welle-6-solo
is an operator-hand option if Welle-6 own substrate proves
isolatable). Phase-3-COMPLETE-marker stays NO-FIRE.

### R-W7-C -- Post-Merge-DEFECT-Cascade (Recovery-Drill-Live Forensic Branch)

**Trigger**: P5 reports `DEFECT` on the recovery-drill-live axis --
post-merge state shows Recovery-Drill-Live drift between canonical
trace and live-state-backing-snapshot replay outcome after Welle-7-
merge landed, OR Recovery-Workflow-self-reference detected (replay
of own emitted recovery-trace) in the live drill.

**Recovery**: invoke generic R3 (Welle-N-Post-Cutover-Defect)
**plus** the Welle-7-specific recovery-drill-live forensic trace
**plus** an immediate Phase-3-COMPLETE-marker BLOCK (no fire). Henrik
runs the Cross-Welle-Hot-Spot-Re-Probe with recovery-drill-live
forensic focus, including a forensic comparison of canonical R1..R4
traces vs. the live replay outcomes that triggered the defect.
Decision to roll-forward or roll-back rests on the Re-Probe verdict
+ AR-pair sign-off **plus** a Pre-Auditor-Cascade-Review (compressed
to 12 h) **plus** an explicit `final_sealing_decision` update from
the Pre-Auditor to either re-FIRE or permanent-BLOCK the Phase-3-
COMPLETE-marker.

**Recovery-Time-Budget**: 12..48 h.

**Fall-back-Pin**: rollback Welle-7-merge if Re-Probe + Pre-Auditor
cascade-review both flag red. Welle-6 stays deferred until Welle-7
re-validation completes. Recovery-Workflow falls back to Python-
Recovery-resolver-path until forensic-trace is closed. KW-27-Doppel-
Welle aggregate verdict re-computes as `KW-27-DECOUPLE-CASCADE`.
Phase-3-COMPLETE-marker stays NO-FIRE with explicit
`recovery_drill_live_forensic_pending: true` flag in state.

### R-W7-D -- KW-27-Doppel-Welle-Decouple (Final-Sealing-Variant)

**Trigger**: P4 reports `WELLE-7-P4-PROPAGATION-YELLOW` with Welle-6-
partner-caution OR Welle-6-Day reports red after Welle-7-P3-APPROVED
has already merged (KW-27-cascade directionality means a Welle-6-
red signals upstream substrate defect that propagates into Welle-7-
Recovery-Workflow).

**Recovery**: de-couple Welle-7 from the KW-27-Doppel-Welle. Welle-6-
Day-Sequence handles its own rollback per its own R-W6-* paths
(Tag-74-Patch); Welle-7 either proceeds solo (if its own P1..P5 are
green AND the Phase-2-Acceptance-Gate cross-modul-subscribe-loop-
recovery-workflow axis still green AND the Welle-6-defect proves
isolatable from Welle-7-Recovery-Workflow per Reza-Cross-Review-
Zone-A disziplin) or defers to KW-28-Mo-solo. Asymmetrie zu R-W6-D
(Welle-6 perspective): die KW-27-cascade-directionality erlaubt
Welle-7-solo nur unter strikten Isolations-Bedingungen (Welle-7-
Recovery-Workflow darf nicht auf Welle-6-Subscribe-Loop-output
angewiesen sein im live-Substrate). Final-Sealing-Implikation: ein
Welle-7-solo bedeutet, dass Welle-6 nachgereicht werden muss BEVOR
das Phase-3-COMPLETE-marker fired (kein FIRE auf incomplete-Doppel-
Welle).

**Recovery-Time-Budget**: 0..24 h (decision-only) + 7..14 d (Welle-6
re-validation before marker-fire).

**Fall-back-Pin**: Welle-7 keeps cutover progress only if P1..P5 all
green AND the Phase-2-Acceptance-Gate cross-modul axis remained green
through the Welle-6-failure-window AND the recovery-drill-live live-
state-backing-snapshot does NOT include Welle-6-subscribe-loop-output
as input. Welle-6 handles its own fall-back-pin per Tag-74-Patch.
Phase-3-COMPLETE-marker stays NO-FIRE until both Welle-6 and Welle-7
are green (no partial-marker-fire).

## §6 -- AR-Hand-Touchpoints (Welle-7-spezifisch)

In addition to the six generic AR-Hand-Touchpoints TP1..TP6 from the
Tag-66 Eve-Recipe §6, Welle-7-Day introduces three Welle-7-specific
Touchpoints:

### TP-W7-1 -- Pre-Auditor-Designation-Sign-off (T-48 h, Final-Sealing-Authority)

**Question**: "Confirm the designated external Pre-Auditor and the
48-h review window, with mandate covering BOTH recovery-drill-live
AND iia-1130-pre-auditor axes, AND with the `final_sealing_authority:
true` flag explicitly approved?"

**Stop-on-Fail**: P1-HOLD -> Welle-7-defer (falls out of KW-27-
Doppel-Welle if defer >24 h) + Phase-3-Marathon-Schluss-slip.

**AR-Hand**: Mandatory pair-mode (stricter than Welle-3/5/6 because
of Final-Sealing-Authority irreversibility).

### TP-W7-2 -- P3-Decision-Commit-Sanity (T-1 h, Final-Sealing-Intent)

**Question**: "Confirm the Pre-Auditor's decision file: both
axis_verdicts APPROVED (aggregate APPROVED), schema-valid, AND
`final_sealing_intent` value in {FIRE_PHASE_3_COMPLETE_MARKER,
DEFER_FINAL_SEALING} (BLOCK is hard-NO-GO), ready to commit?"

**Stop-on-Fail**: P3-HOLD -> Welle-7-defer. P3-AXIS-ASYMMETRIC ->
AR-pair decides whether to invoke AR-Hand-Override or fall to NO-GO.
P3 with final_sealing_intent == BLOCK -> R-W7-B (treated as
extra-axis-rejection).

**AR-Hand**: Mandatory pair-mode.

### TP-W7-3 -- P5-Final-Sealing-Sign-off (T+5 h, Phase-3-COMPLETE-Marker-Gate)

**Question**: "Confirm Pre-Auditor's post-merge-review: both axes
CLEAN (recovery-drill-live + iia-1130-pre-auditor)? Welle-6 partner
state? KW-27-Doppel-Welle aggregate clean? Phase-2-Acceptance-Gate
cross-modul axis remained green throughout? Global-Acceptance-
Verdict-Aggregator GREEN? `final_sealing_decision` value confirmed
(FIRE / BLOCK / DEFER)? AR-pair approves the Final-Sealing-trigger
action (or the BLOCK/DEFER alternative)?"

**Stop-on-Fail**: P5-DRIFT -> Recovery-Drill-Live-watch activated,
24-h-Defer of marker-fire pending AR-Hand-tiebreak; P5-DEFECT ->
R-W7-C invoked, marker NO-FIRE; P5-DISAGREE -> AR-Hand-tiebreak per
IIA-1130-conflict-resolution-protocol.

**AR-Hand**: Mandatory pair-mode (this is the irreversible marker-
fire decision; pair-mode is non-negotiable).

## §7 -- Helper-Substrat

| Artifact | Path |
|---|---|
| Welle-7-Hot-Spot-Probe Aggregator (Check-4-Owner) | `tooling/ci/welle_7_hot_spot_aggregator.py` |
| Welle-7-Day Recipe-Patch Verifier (Tag-75) | `tooling/ci/verify_welle_7_recipe_patch_doc.py` |
| Global-Acceptance-Verdict-Aggregator (Final-Sealing) | `tooling/ci/aggregate_pyramide_run_order_verdict.py` |
| Welle-7-Day Pre-Auditor-State-File (Final-Sealing-Authority) | `state/welle-7-pre-auditor-decision.json` |
| Welle-7-Day Recovery-Drill-Live-State-File | `state/welle-7-recovery-drill-live.json` |
| Welle-7-Day Validation-Last-Verdict-State-File | `state/welle-7-validation-last-verdict.json` |
| Welle-7-Day Aggregate-Verdict-File | `state/welle-7-day-verdict.json` |
| Phase-3-Marathon-Global-Verdict-File (Final-Sealing-Output) | `state/phase-3-marathon-global-verdict.json` |
| Welle-7-Day Marathon-Dashboard-Tile | (per marathon-dashboard-substrate) |
| Welle-7-Day Test-Suite | `tests/observability/test_welle_7_recipe_patch_tag75.py` |

## §8 -- Sandbox-Posture

Per ADR-0058 + AR-Direktive Tag-44 + AR-Direktive Tag-66 + AR-
Direktive Tag-71 (Welle-3-Patch precedent) + AR-Direktive Tag-73
(Welle-5-Patch precedent) + AR-Direktive Tag-74 (Welle-6-Patch
precedent), this recipe-patch is **doc-form-only** in the hermetic
sandbox. Operator-Hand actions (PR-creates, PR-merges, state-file
commits, Final-Sealing-marker-fires) happen in the live environment
with explicit Mira-Hand-Authorisation per push. The Tag-75-verifier,
the Welle-7-Hot-Spot-Probe-Aggregator, and the Global-Acceptance-
Verdict-Aggregator are all stdlib-only Python and run hermetically
in CI; none produce side-effects outside the artifact tree.

The Recovery-Drill-Live forensic trace (R-W7-C) crosses Reza-Cross-
Review-Zone-A (Container-Identity-Substrate × Recovery-Replay-
Substrate) and is therefore additionally identity-guarded; the
operator-hand must coordinate with Reza before invoking the
forensic-trace branch. The Phase-3-COMPLETE-marker-fire (P5 Final-
Sealing-Aggregation step 7) crosses Reza-Cross-Review-Zone-D (V-904
Phase-3 substrate) and requires Reza-cross-check on the marker-fire-
payload schema before the marker-fire-PR merges.

## §9 -- Cross-Substrate-Links

| Link | Path |
|---|---|
| Tag-66 Eve-Recipe Konsolidat | `docs/operations/operator-hand-cutover-eve-final-recipe.md` |
| Welle-3-Recipe-Patch (Tag-71 precedent) | `docs/operations/operator-hand-welle-3-eve-recipe-patch.md` |
| Welle-5-Recipe-Patch (Tag-73 precedent) | `docs/operations/operator-hand-welle-5-eve-recipe-patch.md` |
| Welle-6-Recipe-Patch (Tag-74 precedent) | `docs/operations/operator-hand-welle-6-eve-recipe-patch.md` |
| Tag-69 G1+G2 Last-Mile Checklist | `docs/operations/g1-g2-last-mile-operator-checklist.md` |
| Tag-70 Cross-Validation-Probe | `tooling/ci/cross_validate_eve_recipes.py` |
| Welle-7-Hot-Spot-Probe Runbook | `docs/ci/welle-7-hot-spot-probe-runbook.md` |
| Welle-7-Validation Runbook | `docs/operations/phase-3c-welle-7-runbook.md` |
| Welle-6-Runbook (KW-27-Doppel-Welle partner) | `docs/operations/phase-3c-welle-6-runbook.md` |
| Pre-Cutover-Acceptance-Run-Order (Final-Sealing anchor) | `docs/quality-gates/pre-cutover-acceptance-run-order.md` |
| Marathon-Final-Acceptance Spec | `docs/quality-gates/phase-3-marathon-final-acceptance.md` |
| Marathon-Acceptance-Pyramide structural map | `docs/quality-gates/marathon-acceptance-pyramide.md` |
| phase-3c-cutover-runbook | `docs/operations/phase-3c-cutover-runbook.md` |
| Henrik Tag-39 Welle-6+7-Pre-Audit-Bundle | `agents-workspaces/internal-audit/outbox/2026-05-18-welle-6-7-pre-audit-bundle.md` |
| Henrik Tag-44 Pre-Mortem | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-44-pre-mortem-done.md` |
| Henrik Tag-45 Mitigation-Map-Deep-Dives | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-45-mitigation-map-done.md` |

-- Kai
