---
title: "Operator-Hand Welle-6 Day-of-Recipe-Patch (Tag-74)"
status: "active"
owner: "kai"
audience: "operator,ar,engineering,internal-audit"
created: "2026-05-19"
tag: "tag-74"
predecessors:
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
  - "docs/operations/operator-hand-welle-3-eve-recipe-patch.md"
  - "docs/operations/operator-hand-welle-5-eve-recipe-patch.md"
  - "docs/operations/phase-3c-welle-6-runbook.md"
  - "docs/operations/g1-g2-last-mile-operator-checklist.md"
  - "docs/ci/welle-6-hot-spot-probe-runbook.md"
related_adrs:
  - "ADR-0065"
  - "ADR-0066"
related_docs:
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
  - "docs/operations/operator-hand-welle-3-eve-recipe-patch.md"
  - "docs/operations/operator-hand-welle-5-eve-recipe-patch.md"
  - "docs/operations/phase-3c-welle-6-runbook.md"
  - "docs/operations/phase-3c-welle-7-runbook.md"
  - "docs/ci/welle-6-hot-spot-probe-runbook.md"
  - "docs/operations/phase-3c-cutover-runbook.md"
related_prs:
  - "#463"
related_memory:
  - "Welle-6 ist propagation-target Hot-Spot (Henrik Tag-44 + Tag-45). NATS-Subscribe-Mode-Live-Check + Subscribe-Loop-Cascade-into-Recovery-Workflow (Welle-7) erfordert chirurgische Patch-Lage; Standard-Welle-Pattern reicht nicht. KW-27-Doppel-Welle handhabt Cross-Modul-Stress out-of-band (Asymmetrie zu KW-26)."
---

# Operator-Hand Welle-6 Day-of-Recipe-Patch

**Tag-74 Companion-Doc** zum Tag-66 Eve-Recipe-Konsolidat. Welle-6
(`subscribe_loop` / `persona-engine-subscribe-loop`) ist die dritte
Welle in der Phase-3c-Marathon-Sequenz mit **Pre-Auditor-Section-11-
Disziplin** (IIA-1130) -- nach Welle-3 (Tag-71-Patch) und Welle-5
(Tag-73-Patch). Im Unterschied zu Welle-5 (KW-26-Doppel-Welle mit
inline Cross-Modul-Stress) traegt Welle-6 zwei verschraenkte Hot-
Spots **plus** eine strukturelle KW-27-Doppel-Welle-Asymmetrie:

* **NATS-Subscribe-Mode-Live-Check** -- Henrik Tag-46 A8-Finding
  (NATS-JetStream-Loss-Recovery) identifiziert Subscribe-Mode-
  Mismatch als silent-message-loss-Klasse. Statische A8-Coverage
  landete Tag-46; das Cutover-Window benoetigt Live-Mode-
  Verification gegen den Produktions-JetStream-Cluster.
* **Subscribe-Loop-Cascade-into-Recovery-Workflow (Welle-7)** --
  ein Subscribe-Mode-Mismatch in Welle-6 propagiert direkt in
  Welle-7 als Recovery-Replay-Divergenz. Anders als die KW-26-
  Doppel-Welle (Welle-4+Welle-5 mit symmetrischen Cross-Modul-
  Schnittstellen) ist die KW-27-Kopplung **asymmetrisch und gerichtet**
  (Welle-6 -> Welle-7).

Daher ist das Standard-Welle-Pattern (Stand-up -> Welle-Merge ->
Stability-Check -> Welle-Smoke -> Dashboard-Update -> AR-Sign-off)
fuer Welle-6 **nicht hinreichend**: vor dem Welle-Merge muessen vier
zusaetzliche **Pre-Auditor-Signaling-Schritte** P1..P4 die Operator-
Hand passieren, und nach dem Welle-Merge ein fuenfter Post-Sign-off-
Step P5.

## Scope und Abgrenzung

Diese Doc ist **kein Ersatz** fuer das Tag-66 Eve-Recipe, das
phase-3c-welle-6-runbook oder die Welle-3/5-Recipe-Patches (Tag-71
+ Tag-73). Sie ist eine **chirurgische Patch-Lage** ueber dem
Welle-6-Day-Section des Tag-66 Eve-Recipes (§4.5 dort, T0+5-Block
im post-ADR-0066-revidierten KW-27-Doppel-Welle-Schedule) und ueber
dem phase-3c-welle-6-runbook (Step 3, Welle-6-Validation-Workflow).

Die Patch-Lage besteht aus:

* **Welle-6-Day Pre-Sequence P1..P4** -- vier Pre-Auditor-Signaling-
  Schritte, jeweils mit Owner, Action, Stop-on-Fail, Verdict-Marker,
  die **vor** dem Standard-Welle-Stand-up (06:00 CEST) liegen
  muessen.
* **Welle-6-Day Post-Sequence P5** -- ein Post-Sign-off-Step der
  **nach** dem Standard-AR-Sign-off (12:00 CEST) den Pre-Auditor-
  Decision-File commitet, das Subscribe-Loop-Cascade-Substrate
  re-verifiziert und an die Welle-7-Downstream-Workflows propagiert.

## Zeit-Domain

Welle-6 hat zwei kandidierende Anker, post-ADR-0066-revidiert:

| Anker | Date | Quelle |
|---|---|---|
| ADR-0066 §Welle-Sequenz (Doppel-Welle KW-27) | KW-27 Mi 2026-06-24 | ADR-0066 Welle-6+Welle-7 parallel |
| Tag-66 Eve-Recipe §4.5 (vor ADR-0066) | T0+5 (alter Plan) | Tag-66 Marathon-Plan, **superseded** |
| Brief Tag-74 Auftrag | KW-27 Mi 2026-06-24 | Continuous-Mode-Spawn-Anker (ADR-0066-konform) |

**Operativer Schluss**: Welle-6-Day-Datum ist konvergent (KW-27-Mi,
2026-06-24, post-ADR-0066). Diese Patch-Lage gilt unverruechlich an
diesem Anker, mit der zusaetzlichen Constraint, dass die KW-27-
Doppel-Welle (Welle-6+Welle-7) zwei parallel laufende Recipe-Patches
benoetigt (Welle-7 hat eigene Patch-Lage in Tag-75-Folge-Auftrag-
Antizipation; Welle-6 ist diese Doc).

Der Pre-Auditor-Designation-Step (P1) muss **mindestens 48 h vor**
dem Welle-6-Day landen, damit der Pre-Auditor-Review realistisch ist.

## Pre-Auditor-Section-11-Hintergrund (IIA-1130)

Henrik Tag-44 Pre-Mortem (`agents-workspaces/mira/inbox/2026-05-18-
henrik-tag-44-pre-mortem-done.md`) und Tag-45 Mitigation-Map-Deep-Dives
identifizieren Welle-6 als propagation-target Hot-Spot mit zwei
verschraenkten Self-Reference-Risiken:

* **NATS-Subscribe-Mode-Mismatch (Tag-46 A8-Lineage)**: live-mode-
  verification variant der NATS-JetStream-Loss-Recovery-Klasse.
  Subscribe-Mode (ack_policy, consumer_durable_name) liegt in
  canonical-config vor, hat aber keine matching subscribe-state in
  live-cluster.
* **Subscribe-Loop-Self-Reference (Welle-3-aehnlich)**: der Subscribe-
  Loop-Resolver konsumiert NATS-Events, die er selbst geprueft hat
  -- Reviewer der Subscribe-Logik ist nicht unabhaengig vom NATS-
  Substrate. Identisches Muster zu Welle-3 (Audit-Stream-
  Selbstreferenz), wegen NATS-Substrate aber distinct in der
  cascading-Wirkung auf Welle-7.

IIA-1130 "Impairment to Independence or Objectivity" verbietet, dass
die Cutover-Entscheidung von einem Reviewer kommt, der gleichzeitig
Co-Eigner eines der beiden Cutover-Substrate ist.

Daraus folgt: die Welle-6-Day-Sign-off-Entscheidung kann **nicht**
vom Standard-AR-Pair-Mode allein getragen werden. Sie braucht einen
externen Pre-Auditor, der von der AR-Hand designiert wird, dessen
Mandat sowohl NATS-Subscribe-Mode-Live-Check als auch Subscribe-Loop-
Cascade-into-Welle-7 umfasst, und dessen Sign-off als hard-pass-
Voraussetzung neben dem AR-Pair-Sign-off steht.

## §1 -- Pre-Sequence P1..P4 (vor 06:00 CEST am Welle-6-Day)

### P1 -- Pre-Auditor-Designation-Verify

**Time-Window**: 48 h vor Welle-6-Day (= ab Montag 2026-06-22 06:00
CEST), taegliches Re-Check bis Welle-6-Day-Morning 05:00 CEST.

**Action**: verify `state/welle-6-pre-auditor-decision.json` exists,
parses, has `auditor_role: "external-pre-auditor"`, `welle: 6`,
`hot_spot_axes: ["nats-subscribe-mode", "subscribe-loop-cascade"]`,
`decision` field is one of {`PENDING`, `APPROVED`, `REJECTED`}. The
48-h-ahead window REQUIRES at minimum a `PENDING` entry naming the
designated external Pre-Auditor and listing both hot-spot axes.

**Owner**: Operator-Hand (Mira).

**Stop-on-Fail**: `WELLE-6-P1-HOLD` -- Welle-6-Day-Sequence does NOT
start. Operator-Hand triggers AR-pair-mode escalation to fast-track
Pre-Auditor designation. KW-27-Doppel-Welle constraint: if P1-HOLD
persists past 24 h, Welle-7-Day stays on calendar but Welle-6 falls
out of the Doppel-Welle and reschedules to KW-28 solo.

**Verdict-Marker**: `WELLE-6-P1-PRE-AUDITOR-DESIGNATED` (green),
`WELLE-6-P1-PENDING` (yellow, file present with PENDING decision and
both axes named), `WELLE-6-P1-HOLD` (red, file missing, schema invalid,
or hot-spot-axes list incomplete).

**Sandbox-OK**: yes, no merge-mutating action.

### P2 -- Pre-Auditor-Review-Window-Confirm

**Time-Window**: 24 h vor Welle-6-Day (= Dienstag 2026-06-23 06:00
CEST).

**Action**: confirm via AR-pair voice channel that the designated
Pre-Auditor has had a contiguous 24-h review window with access to:

* Welle-6 hot-spot probe last 7 daily envelopes
  (`.welle-6-hot-spot-probe/` artifacts).
* `state/welle-6-subscribe-mode-live.json`.
* `state/welle-6-cascade-into-welle-7-drift.json`.
* `state/welle-6-validation-last-verdict.json`.
* Tag-44 Henrik Pre-Mortem document.
* Tag-45 Henrik Mitigation-Map-Deep-Dives document.
* Tag-46 A8 NATS-JetStream-Loss-Recovery static-coverage report.
* phase-3c-welle-6-runbook §3 (Step 5 Render-Cutover-Acceptance-
  Decision with KW-27-Doppel-Welle partner Welle-7).
* Welle-3-Recipe-Patch (Tag-71) AND Welle-5-Recipe-Patch (Tag-73)
  as precedent templates (Pre-Auditor may not be the same person as
  either previous Pre-Auditor; if same, IIA-1120 conflict-of-
  interest declaration must be on file).

**Owner**: AR-pair (Mira moderates, AR-pair confirms voice-channel
contact).

**Stop-on-Fail**: `WELLE-6-P2-HOLD` -- Welle-6-Day defers by 24 h
(falls out of KW-27-Doppel-Welle to KW-27-Do-solo). Re-attempt next
morning.

**Verdict-Marker**: `WELLE-6-P2-REVIEW-WINDOW-CONFIRMED` (green),
`WELLE-6-P2-REVIEW-WINDOW-PARTIAL` (yellow, less than 24-h-contiguous
or missing access to one of the two hot-spot-state-files),
`WELLE-6-P2-HOLD` (red, contact failed).

**Sandbox-OK**: yes.

### P3 -- Pre-Auditor-Decision-Receive

**Time-Window**: 04:30 -- 05:30 CEST on Welle-6-Day-Morning
(2026-06-24).

**Action**: receive the Pre-Auditor's signed decision file update
(APPROVED, REJECTED, or extended-PENDING). The decision file MUST
include `axis_verdicts: {nats_subscribe_mode: APPROVED|REJECTED,
subscribe_loop_cascade: APPROVED|REJECTED}`. Both axis-verdicts
must be APPROVED for the aggregate `decision` to be APPROVED;
asymmetric verdicts (one APPROVED, one REJECTED) collapse to
aggregate REJECTED. Operator-Hand commits the updated
`state/welle-6-pre-auditor-decision.json` via a Mira-Hand-PR with
explicit `pre-auditor-decision-update` label. The PR is **not auto-
mergeable**: it requires AR-pair sign-off as a sanity-check on the
schema before merge.

**Owner**: Operator-Hand (Mira), AR-pair sanity-check.

**Stop-on-Fail**: `WELLE-6-P3-HOLD` -- if REJECTED, Welle-6-Day
becomes `WELLE-6-VERDICT-NO-GO`; if PENDING extended past 06:00 CEST,
Welle-6-Day defers by 24 h.

**Verdict-Marker**: `WELLE-6-P3-APPROVED` (green, both axes APPROVED,
AR-pair-sanity passed, PR merged), `WELLE-6-P3-PENDING-EXTENDED`
(yellow, decision file PENDING with `deferred_until_utc` field
present), `WELLE-6-P3-AXIS-ASYMMETRIC` (yellow, one axis APPROVED
one REJECTED; collapses to NO-GO unless AR-Hand-Override
documented), `WELLE-6-P3-HOLD` (red, aggregate REJECTED or PR-merge-
fail).

**Sandbox-OK**: no (merge-mutating action; in dry-run, the PR is
created but not merged).

### P4 -- Pre-Auditor-Decision-Propagation-Check

**Time-Window**: 05:30 -- 06:00 CEST on Welle-6-Day-Morning.

**Action**: run the welle-6-hot-spot-probe-aggregator
(`tooling/ci/welle_6_hot_spot_aggregator.py`) and confirm Check-4
(IIA-1130-Pre-Auditor-Decision-Tracking) reports `green`. Confirm
that the aggregator emits `cross_welle_propagation` block with
`pre_conditional_blocked: []` (empty list -- downstream Welle-7 is
NOT pre-conditionally blocked by Welle-6 nats-subscribe-mode or
subscribe-loop-cascade drift). Additionally confirm
`kw_27_doppel_welle.welle_7_partner_status` is `green|caution` (red
on the Welle-7 partner cascades into Welle-6-P4-HOLD because the
KW-27-cascade is directional Welle-6 -> Welle-7; a red Welle-7
already-merged signals upstream-substrate-defect-in-Welle-6).

**Owner**: Operator-Hand (Mira), Tomas (Matrix-Lead) reads artifact.

**Stop-on-Fail**: `WELLE-6-P4-HOLD` -- if Check-4 reports red/yellow,
Welle-6-Day stays on calendar but blocks at P4 until the upstream
state reconciles. If the `pre_conditional_blocked` list is non-
empty, Welle-7 is also flagged as downstream-blocked and the
marathon-dashboard tile flips to `WELLE-6-CASCADE-RISK`. If the
KW-27-Doppel-Welle partner (Welle-7) status is red, Welle-6
de-couples from the Doppel-Welle and reschedules to KW-27-Do-solo
(operator-hand decision).

**Verdict-Marker**: `WELLE-6-P4-PROPAGATION-CLEAR` (green),
`WELLE-6-P4-PROPAGATION-YELLOW` (yellow, single check yellow OR
Welle-7-partner caution), `WELLE-6-P4-HOLD` (red, propagation blocked
or Welle-7-partner red).

**Sandbox-OK**: yes (probe is hermetic, no side-effects).

## §2 -- Standard-Welle-6 Day-Sequence (06:00 -- 12:00 CEST)

After P1..P4 pass green, the Standard-Welle-Day-Sequence proceeds
**unchanged** from the Tag-66 Eve-Recipe §4.5 + phase-3c-welle-6-
runbook §3:

* **06:00 -- 06:30 CEST**: Stand-up.
* **06:30 -- 09:00 CEST**: Welle-6-Merge (per phase-3c-welle-6-
  runbook §3). In the KW-27-Doppel-Welle, Welle-7-Merge runs in
  parallel; merge-conflict-coordination is via the matrix-lead
  voice-channel.
* **09:00 -- 10:00 CEST**: Welle-1/2/3/4/5-Stability-Check (and
  Welle-7 partner stability, given Doppel-Welle).
* **10:00 -- 11:00 CEST**: Welle-6-Smoke + Welle-7-Smoke (parallel,
  per KW-27-Doppel-Welle).
* **11:00 -- 11:30 CEST**: Dashboard-Update.
* **11:30 -- 12:00 CEST**: AR-Sign-off.

**KW-27 Cross-Modul-Asymmetrie zu KW-26 (Welle-5)**: Im Unterschied
zur KW-26-Doppel-Welle (welche den Cross-Modul-Stress-Test als sechsten
inline-Step verlangt) handhabt die KW-27-Doppel-Welle Cross-Modul-
Drift **out-of-band** via Phase-2-Acceptance-Gate daily rollup
(siehe `docs/operations/phase-3c-welle-6-runbook.md` §"KW-27 Doppel-
Welle posture"). Die KW-27-Standard-5-Step-Sequence enthaelt **keinen
inline-Cross-Modul-Step**; statt dessen muss vor 06:00 CEST der
Phase-2-Acceptance-Gate daily-rollup-Verdict mit der Axe
`cross-modul-subscribe-loop-recovery-workflow` auf green stehen.
Operator-Hand validiert diese Out-of-band-Axe als Teil von P4 (siehe
oben). Bei Ad-hoc-Bedarf laesst sich der Cross-Modul-Aggregator
manuell auslosen:

```bash
python scripts/doppelbetrieb-score-aggregator.py \
    --mode cross-modul-stress \
    --out /tmp/kw27-cross-modul.json
```

## §3 -- Post-Sequence P5 (12:00 -- 13:00 CEST)

### P5 -- Pre-Auditor-Final-Sign-off-Commit

**Time-Window**: 12:00 -- 13:00 CEST on Welle-6-Day, after the
standard AR-Sign-off.

**Action**: the designated external Pre-Auditor confirms the
post-merge state of Welle-6 (Welle-1/2/3/4/5/6-Stability-Check green,
Welle-6-Smoke green, Welle-7-Smoke green, NATS-Subscribe-Mode-Live
indicator green, Subscribe-Loop-Cascade-into-Welle-7 indicator green)
and updates `state/welle-6-pre-auditor-decision.json` with a final
`decision_finalised_at_utc` timestamp, `post_merge_review:
"clean|drift|defect"` field, and `axis_post_merge: {nats_subscribe_mode:
clean|drift|defect, subscribe_loop_cascade: clean|drift|defect}`
field. Operator-Hand commits via Mira-Hand-PR with `pre-auditor-
final-sign-off` label.

**Owner**: External Pre-Auditor produces the artifact; Operator-Hand
(Mira) commits.

**Stop-on-Fail**: `WELLE-6-P5-DRIFT` if any axis-post-merge reports
`drift`; the marathon proceeds but the Welle-7-cascade-watch is
activated. `WELLE-6-P5-DEFECT` if any axis-post-merge reports
`defect`; Welle-7 defers 24 h and Henrik (Internal Audit) is
notified for a Cross-Welle-Hot-Spot-Re-Probe with explicit
subscribe-loop-cascade forensic focus.

**Verdict-Marker**: `WELLE-6-P5-CLEAN` (green, both axes clean),
`WELLE-6-P5-DRIFT` (yellow, at least one axis drift), `WELLE-6-P5-
DEFECT` (red, at least one axis defect).

**Sandbox-OK**: no (commit-mutating action).

## §4 -- Welle-6-Day Aggregate Verdict-Roll-up

The aggregate Welle-6-Day verdict is computed from P1..P5 plus the
Standard-Welle-Day green-state:

| All P1..P5 green + Welle-Day clean | -> `WELLE-6-VERDICT-CUTOVER-DONE` |
| Any P-step yellow, all rest green | -> `WELLE-6-VERDICT-CAUTION` |
| P3 yellow (PENDING-EXTENDED) | -> `WELLE-6-VERDICT-DEFER-24H` |
| P3 yellow (AXIS-ASYMMETRIC, no override) | -> `WELLE-6-VERDICT-NO-GO` |
| P3 red (REJECTED) | -> `WELLE-6-VERDICT-NO-GO` |
| P4 yellow (Welle-7-partner-caution) | -> `WELLE-6-VERDICT-DOPPEL-DECOUPLE` |
| P5 red (DEFECT) | -> `WELLE-6-VERDICT-CASCADE-WATCH` |
| Any other red | -> `WELLE-6-VERDICT-HOLD` |

The aggregate verdict is emitted to `state/welle-6-day-verdict.json`
and consumed by the marathon-dashboard-tile-emitter.

## §5 -- Rollback-Pfade (Welle-6-spezifisch)

Welle-6-spezifische Rollback-Pfade ergaenzen die fuenf generischen
R1..R5-Pfade aus dem Tag-66 Eve-Recipe §5:

### R-W6-A -- Pre-Auditor-Designation-Failure

**Trigger**: P1-HOLD persists past 48-h-window AND AR-Hand-
escalation cannot designate within 24 h. Or: designated Pre-Auditor
declares IIA-1120 conflict-of-interest after 24-h-window has begun.

**Recovery**: defer Welle-6-Day by minimum 72 h. Falls out of KW-27-
Doppel-Welle; reschedules to KW-28-Mo-solo at earliest. Marathon-
Dashboard flips Welle-6-tile to `DESIGNATION-PENDING`. Welle-7
stays on calendar but is pre-conditionally flagged (KW-27-cascade
directional: Welle-6 -> Welle-7).

**Recovery-Time-Budget**: minimum 72 h (24 h re-escalation + 48 h
new review window).

**Fall-back-Pin**: Welle-6-component default backend stays `python`
(no flip). `WAKIR_SUBSCRIBE_LOOP_BACKEND` remains on Python-Subscribe-
Loop-resolver path. Welle-7 may proceed if its own substrate is
isolatable from the Welle-6-defer (per ADR-0066 substrate-coupling-
map; in practice the KW-27-cascade directionality means Welle-7 is
also pre-conditionally flagged for AR-Hand-decision).

### R-W6-B -- Pre-Auditor-REJECTED-Decision (Aggregate or Axis)

**Trigger**: P3 receives an aggregate-REJECTED decision file, OR P3
receives an AXIS-ASYMMETRIC verdict (one axis REJECTED) without an
AR-Hand-Override on file.

**Recovery**: invoke the Welle-6-Henrik-Audit-Loop -- Henrik
(Internal Audit) reviews the Pre-Auditor's rationale per axis
(nats-subscribe-mode and subscribe-loop-cascade are reviewed
independently) and either endorses or contests the REJECTED axis-
verdict. If endorsed, the rejected axis substrate is re-engineered
per Henrik recommendations and a new Pre-Auditor-Review-Cycle
(P1..P5) re-runs. If contested, AR-Hand-Entscheidung breaks the
tie.

**Recovery-Time-Budget**: 7..14 days (Henrik review + substrate
re-engineering + new review cycle). Subscribe-Loop-Cascade-specific
re-engineering may extend the budget by an additional 7 days (Reza
Cross-Review-Zone-B disziplin, NATS-JetStream-Schema interaction).

**Fall-back-Pin**: Welle-6-component default backend stays `python`.
Welle-7 either also defers (cascade-block) or proceeds without
Welle-6-dependency (per ADR-0066 substrate-coupling-map; KW-27-
cascade directionality biases toward cascade-block).

### R-W6-C -- Post-Merge-DEFECT-Cascade (Subscribe-Loop-Cascade
Forensic Branch)

**Trigger**: P5 reports `DEFECT` on the subscribe-loop-cascade
axis -- post-merge state shows Subscribe-Loop-Cascade-into-Welle-7
drift between Rust-Subscribe-Loop-resolver and Python-Subscribe-
Loop-resolver after Welle-6-merge landed, with downstream replay-
divergence in Welle-7-recovery-workflow.

**Recovery**: invoke generic R3 (Welle-N-Post-Cutover-Defect)
**plus** the Welle-6-specific cascade-watch on Welle-7 **plus** a
forensic subscribe-loop-cascade trace via the Reza Cross-Review-
Zone-B Wirelang-Layer-2-team (NATS-JetStream-Schema impact assessment).
Henrik runs the Cross-Welle-Hot-Spot-Re-Probe with subscribe-loop-
cascade forensic focus. Decision to roll-forward or roll-back rests
on the Re-Probe verdict + AR-pair sign-off **plus** a Pre-Auditor-
Cascade-Review (compressed to 12 h).

**Recovery-Time-Budget**: 12..36 h.

**Fall-back-Pin**: rollback Welle-6-merge if Re-Probe + Pre-Auditor
cascade-review both flag red. Welle-7 stays deferred until re-
validation. Subscribe-Loop falls back to Python-Subscribe-Loop-
resolver-path until forensic-trace is closed. KW-27-Doppel-Welle
aggregate verdict re-computes as `KW-27-DECOUPLE-CASCADE`.

### R-W6-D -- KW-27-Doppel-Welle-Decouple

**Trigger**: P4 reports `WELLE-6-P4-PROPAGATION-YELLOW` with Welle-
7-partner-caution OR Welle-7-Day reports red after Welle-6-P3-
APPROVED has already merged (KW-27-cascade directionality means a
Welle-7-red signals upstream Welle-6 substrate defect).

**Recovery**: de-couple Welle-6 from the KW-27-Doppel-Welle. Welle-
7-Day-Sequence handles its own rollback per its own R-W7-* paths
(forthcoming Tag-75-Patch); Welle-6 either proceeds solo (if its own
P1..P5 are green and the Phase-2-Acceptance-Gate cross-modul-
subscribe-loop-recovery-workflow axis still green) or defers to
KW-27-Do-solo. Asymmetrie zu R-W5-D (KW-26): die KW-27-cascade-
directionality biases die Decouple-Entscheidung gegen Welle-6-solo,
weil Welle-7-red den Verdacht auf Welle-6-substrate-Defekt nahelegt.

**Recovery-Time-Budget**: 0..24 h (decision-only).

**Fall-back-Pin**: Welle-6 keeps cutover progress only if P1..P5 all
green AND the Phase-2-Acceptance-Gate cross-modul axis remained green
through the Welle-7-failure-window. Welle-7 handles its own fall-back-
pin per Tag-75-Patch.

## §6 -- AR-Hand-Touchpoints (Welle-6-spezifisch)

In addition to the six generic AR-Hand-Touchpoints TP1..TP6 from the
Tag-66 Eve-Recipe §6, Welle-6-Day introduces three Welle-6-specific
Touchpoints:

### TP-W6-1 -- Pre-Auditor-Designation-Sign-off (T-48 h)

**Question**: "Confirm the designated external Pre-Auditor and the
48-h review window, with mandate covering BOTH nats-subscribe-mode
AND subscribe-loop-cascade axes?"

**Stop-on-Fail**: P1-HOLD -> Welle-6-defer (falls out of KW-27-
Doppel-Welle if defer >24 h).

**AR-Hand**: Mandatory pair-mode.

### TP-W6-2 -- P3-Decision-Commit-Sanity (T-1 h)

**Question**: "Confirm the Pre-Auditor's decision file: both
axis_verdicts APPROVED (aggregate APPROVED), schema-valid, ready to
commit?"

**Stop-on-Fail**: P3-HOLD -> Welle-6-defer. P3-AXIS-ASYMMETRIC ->
AR-pair decides whether to invoke AR-Hand-Override or fall to NO-GO.

**AR-Hand**: Mandatory pair-mode.

### TP-W6-3 -- P5-Post-Merge-Cascade-Sign-off (T+5 h)

**Question**: "Confirm Pre-Auditor's post-merge-review: both axes
CLEAN (nats-subscribe-mode + subscribe-loop-cascade)? Welle-7 partner
state? KW-27-Doppel-Welle aggregate clean? Phase-2-Acceptance-Gate
cross-modul axis remained green throughout?"

**Stop-on-Fail**: P5-DRIFT -> cascade-watch on Welle-7 activated;
P5-DEFECT -> R-W6-C invoked.

**AR-Hand**: Mandatory pair-mode.

## §7 -- Helper-Substrat

| Artifact | Path |
|---|---|
| Welle-6-Hot-Spot-Probe Aggregator (Check-4-Owner) | `tooling/ci/welle_6_hot_spot_aggregator.py` |
| Welle-6-Day Recipe-Patch Verifier (Tag-74) | `tooling/ci/verify_welle_6_recipe_patch_doc.py` |
| Welle-6-Day Pre-Auditor-State-File | `state/welle-6-pre-auditor-decision.json` |
| Welle-6-Day NATS-Subscribe-Mode-Live-State-File | `state/welle-6-subscribe-mode-live.json` |
| Welle-6-Day Subscribe-Loop-Cascade-Drift-State-File | `state/welle-6-cascade-into-welle-7-drift.json` |
| Welle-6-Day Aggregate-Verdict-File | `state/welle-6-day-verdict.json` |
| Welle-6-Day Marathon-Dashboard-Tile | (per marathon-dashboard-substrate) |
| Welle-6-Day Test-Suite | `tests/observability/test_welle_6_recipe_patch_tag74.py` |

## §8 -- Sandbox-Posture

Per ADR-0058 + AR-Direktive Tag-44 + AR-Direktive Tag-66 + AR-
Direktive Tag-71 (Welle-3-Patch precedent) + AR-Direktive Tag-73
(Welle-5-Patch precedent), this recipe-patch is **doc-form-only** in
the hermetic sandbox. Operator-Hand actions (PR-creates, PR-merges,
state-file commits) happen in the live environment with explicit
Mira-Hand-Authorisation per push. The Tag-74-verifier and the
Welle-6-Hot-Spot-Probe-Aggregator are both stdlib-only Python and
run hermetically in CI; neither produces side-effects outside the
artifact tree.

The Subscribe-Loop-Cascade-Drift forensic trace (R-W6-C) crosses
Reza-Cross-Review-Zone-B (NATS-JetStream-Schema × Wirelang-Layer-2)
and is therefore additionally protocol-guarded; the operator-hand
must coordinate with Reza before invoking the forensic-trace branch.

## §9 -- Cross-Substrate-Links

| Link | Path |
|---|---|
| Tag-66 Eve-Recipe Konsolidat | `docs/operations/operator-hand-cutover-eve-final-recipe.md` |
| Welle-3-Recipe-Patch (Tag-71 precedent) | `docs/operations/operator-hand-welle-3-eve-recipe-patch.md` |
| Welle-5-Recipe-Patch (Tag-73 precedent) | `docs/operations/operator-hand-welle-5-eve-recipe-patch.md` |
| Tag-69 G1+G2 Last-Mile Checklist | `docs/operations/g1-g2-last-mile-operator-checklist.md` |
| Tag-70 Cross-Validation-Probe | `tooling/ci/cross_validate_eve_recipes.py` |
| Welle-6-Hot-Spot-Probe Runbook | `docs/ci/welle-6-hot-spot-probe-runbook.md` |
| Welle-6-Validation Runbook | `docs/operations/phase-3c-welle-6-runbook.md` |
| Welle-7-Runbook (KW-27-Doppel-Welle partner) | `docs/operations/phase-3c-welle-7-runbook.md` |
| phase-3c-cutover-runbook | `docs/operations/phase-3c-cutover-runbook.md` |
| Henrik Tag-44 Pre-Mortem | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-44-pre-mortem-done.md` |
| Henrik Tag-45 Mitigation-Map-Deep-Dives | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-45-mitigation-map-done.md` |

-- Kai
