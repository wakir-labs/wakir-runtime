---
title: "Operator-Hand Welle-5 Day-of-Recipe-Patch (Tag-73)"
status: "active"
owner: "kai"
audience: "operator,ar,engineering,internal-audit"
created: "2026-05-19"
tag: "tag-73"
predecessors:
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
  - "docs/operations/operator-hand-welle-3-eve-recipe-patch.md"
  - "docs/operations/phase-3c-welle-5-runbook.md"
  - "docs/operations/g1-g2-last-mile-operator-checklist.md"
  - "docs/ci/welle-5-hot-spot-probe-runbook.md"
related_adrs:
  - "ADR-0065"
  - "ADR-0066"
related_docs:
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
  - "docs/operations/operator-hand-welle-3-eve-recipe-patch.md"
  - "docs/operations/phase-3c-welle-5-runbook.md"
  - "docs/operations/welle-1-2-doppel-telemetry-runbook.md"
  - "docs/ci/welle-5-hot-spot-probe-runbook.md"
  - "docs/operations/phase-3c-cutover-runbook.md"
related_prs:
  - "#454"
  - "#455"
related_memory:
  - "Welle-5 ist propagation-target Hot-Spot (Henrik Tag-44 + Tag-45). FSM-Phantom-Detection live + Capability-Token-Rotation-Drift erfordert chirurgische Patch-Lage; Standard-Welle-Pattern reicht nicht."
---

# Operator-Hand Welle-5 Day-of-Recipe-Patch

**Tag-73 Companion-Doc** zum Tag-66 Eve-Recipe-Konsolidat. Welle-5
(`lifecycle_state_machine` / `persona-engine-fsm`) ist die zweite
Welle in der Phase-3c-Marathon-Sequenz mit **Pre-Auditor-Section-11-
Disziplin** (IIA-1130) -- die erste war Welle-3 (Tag-71-Patch). Im
Unterschied zu Welle-3 (Audit-Stream-Selbstreferenz) traegt Welle-5
zwei verschraenkte Hot-Spots:

* **FSM-Phantom-Transition** -- Henrik Tag-22 A2 + Tag-44/45-Re-Probe
  identifizieren Phantom-Transitions als Live-Replay-Variante (statische
  A2-Coverage allein nicht ausreichend).
* **Capability-Token-Rotation-Drift** -- jede FSM-Transition rotiert
  Capability-Tokens (Reza-Wirelang Layer-2). Drift zwischen Rust-FSM-
  Resolver und Python-FSM-Resolver propagiert in das Capability-Token-
  Rotations-Substrate.

Daher ist das Standard-Welle-Pattern (Stand-up -> Welle-Merge ->
Stability-Check -> Welle-Smoke -> Dashboard-Update -> AR-Sign-off)
fuer Welle-5 **nicht hinreichend**: vor dem Welle-Merge muessen vier
zusaetzliche **Pre-Auditor-Signaling-Schritte** P1..P4 die Operator-
Hand passieren, und nach dem Welle-Merge ein fuenfter Post-Sign-off-
Step P5.

## Scope und Abgrenzung

Diese Doc ist **kein Ersatz** fuer das Tag-66 Eve-Recipe, das
phase-3c-welle-5-runbook oder das Welle-3-Recipe-Patch (Tag-71). Sie
ist eine **chirurgische Patch-Lage** ueber dem Welle-5-Day-Section
des Tag-66 Eve-Recipes (§4.4 dort, T0+4-Block in der KW-26-Doppel-
Welle mit Welle-4) und ueber dem phase-3c-welle-5-runbook (Step 3).

Die Patch-Lage besteht aus:

* **Welle-5-Day Pre-Sequence P1..P4** -- vier Pre-Auditor-Signaling-
  Schritte, jeweils mit Owner, Action, Stop-on-Fail, Verdict-Marker,
  die **vor** dem Standard-Welle-Stand-up (06:00 CEST) liegen
  muessen.
* **Welle-5-Day Post-Sequence P5** -- ein Post-Sign-off-Step der
  **nach** dem Standard-AR-Sign-off (12:00 CEST) den Pre-Auditor-
  Decision-File commitet, das Capability-Token-Rotations-Substrate
  re-verifiziert und an die Welle-6/7-Downstream-Workflows propagiert.

## Zeit-Domain

Welle-5 hat zwei kandidierende Anker, beide weniger fluktuierend als
Welle-3:

| Anker | Date | Quelle |
|---|---|---|
| Tag-66 Eve-Recipe §4.4 | T0+4 = KW-26 Mi 2026-06-17 | Tag-66 Marathon-Plan, ADR-0066-Sequenz |
| ADR-0066 §Welle-Sequenz (Doppel-Welle KW-26) | KW-26 Mi 2026-06-17 | ADR-0066 Welle-4+Welle-5 parallel |
| Brief Tag-73 Auftrag | KW-26 Mi 2026-06-17 | Continuous-Mode-Spawn-Anker |

**Operativer Schluss**: Welle-5-Day-Datum ist konvergent (KW-26-Mi,
2026-06-17). Diese Patch-Lage gilt unverruechlich an diesem Anker,
mit der zusaetzlichen Constraint, dass die KW-26-Doppel-Welle
(Welle-4+Welle-5) zwei parallel laufende Recipe-Patches benoetigt
(Welle-4 hat eigene Patch-Lage in Tag-74-Folge-Auftrag-Antizipation;
Welle-5 ist diese Doc).

Der Pre-Auditor-Designation-Step (P1) muss **mindestens 48 h vor**
dem Welle-5-Day landen, damit der Pre-Auditor-Review realistisch ist.

## Pre-Auditor-Section-11-Hintergrund (IIA-1130)

Henrik Tag-44 Pre-Mortem (`agents-workspaces/mira/inbox/2026-05-18-
henrik-tag-44-pre-mortem-done.md`) und Tag-45 Mitigation-Map-Deep-Dives
identifizieren Welle-5 als propagation-target Hot-Spot mit zwei
verschraenkten Self-Reference-Risiken:

* **FSM-Phantom-Transition (Tag-22 A2-Lineage)**: live-replay variant
  des phantom-transition class. Transition liegt in canonical-trace
  vor, hat aber keine matching FSM-edge in live-engine.
* **Capability-Token-Rotation-Self-Reference**: der Rotations-
  Mechanismus rotiert Capability-Tokens fuer FSM-Transitions, deren
  Schema-Audit gleichzeitig dieselben Tokens konsumiert. Reviewer
  der Rotations-Logik ist nicht unabhaengig vom Rotations-Substrate.

IIA-1130 "Impairment to Independence or Objectivity" verbietet, dass
die Cutover-Entscheidung von einem Reviewer kommt, der gleichzeitig
Co-Eigner eines der beiden Cutover-Substrate ist.

Daraus folgt: die Welle-5-Day-Sign-off-Entscheidung kann **nicht**
vom Standard-AR-Pair-Mode allein getragen werden. Sie braucht einen
externen Pre-Auditor, der von der AR-Hand designiert wird, dessen
Mandat sowohl FSM-Phantom-Live-Probe als auch Capability-Token-
Rotations-Drift umfasst, und dessen Sign-off als hard-pass-
Voraussetzung neben dem AR-Pair-Sign-off steht.

## §1 -- Pre-Sequence P1..P4 (vor 06:00 CEST am Welle-5-Day)

### P1 -- Pre-Auditor-Designation-Verify

**Time-Window**: 48 h vor Welle-5-Day (= ab Montag 2026-06-15 06:00
CEST), taegliches Re-Check bis Welle-5-Day-Morning 05:00 CEST.

**Action**: verify `state/welle-5-pre-auditor-decision.json` exists,
parses, has `auditor_role: "external-pre-auditor"`, `welle: 5`,
`hot_spot_axes: ["fsm-phantom", "capability-token-rotation"]`,
`decision` field is one of {`PENDING`, `APPROVED`, `REJECTED`}. The
48-h-ahead window REQUIRES at minimum a `PENDING` entry naming the
designated external Pre-Auditor and listing both hot-spot axes.

**Owner**: Operator-Hand (Mira).

**Stop-on-Fail**: `WELLE-5-P1-HOLD` -- Welle-5-Day-Sequence does NOT
start. Operator-Hand triggers AR-pair-mode escalation to fast-track
Pre-Auditor designation. KW-26-Doppel-Welle constraint: if P1-HOLD
persists past 24 h, Welle-4-Day stays on calendar but Welle-5 falls
out of the Doppel-Welle and reschedules to KW-27 solo.

**Verdict-Marker**: `WELLE-5-P1-PRE-AUDITOR-DESIGNATED` (green),
`WELLE-5-P1-PENDING` (yellow, file present with PENDING decision and
both axes named), `WELLE-5-P1-HOLD` (red, file missing, schema invalid,
or hot-spot-axes list incomplete).

**Sandbox-OK**: yes, no merge-mutating action.

### P2 -- Pre-Auditor-Review-Window-Confirm

**Time-Window**: 24 h vor Welle-5-Day (= Dienstag 2026-06-16 06:00
CEST).

**Action**: confirm via AR-pair voice channel that the designated
Pre-Auditor has had a contiguous 24-h review window with access to:

* Welle-5 hot-spot probe last 7 daily envelopes
  (`.welle-5-hot-spot-probe/` artifacts).
* `state/welle-5-fsm-phantom-detection.json`.
* `state/welle-5-capability-token-rotation-drift.json`.
* `state/welle-5-validation-last-verdict.json`.
* Tag-44 Henrik Pre-Mortem document.
* Tag-45 Henrik Mitigation-Map-Deep-Dives document.
* phase-3c-welle-5-runbook §3 (Step 5 Cross-Modul-Stress with
  KW-26-Doppel-Welle partner Welle-4).
* Welle-3-Recipe-Patch (Tag-71) as precedent template (Pre-Auditor
  may not be the same person as the Welle-3-Pre-Auditor; if same,
  IIA-1120 conflict-of-interest declaration must be on file).

**Owner**: AR-pair (Mira moderates, AR-pair confirms voice-channel
contact).

**Stop-on-Fail**: `WELLE-5-P2-HOLD` -- Welle-5-Day defers by 24 h
(falls out of KW-26-Doppel-Welle to KW-26-Do-solo). Re-attempt next
morning.

**Verdict-Marker**: `WELLE-5-P2-REVIEW-WINDOW-CONFIRMED` (green),
`WELLE-5-P2-REVIEW-WINDOW-PARTIAL` (yellow, less than 24-h-contiguous
or missing access to one of the two hot-spot-state-files),
`WELLE-5-P2-HOLD` (red, contact failed).

**Sandbox-OK**: yes.

### P3 -- Pre-Auditor-Decision-Receive

**Time-Window**: 04:30 -- 05:30 CEST on Welle-5-Day-Morning
(2026-06-17).

**Action**: receive the Pre-Auditor's signed decision file update
(APPROVED, REJECTED, or extended-PENDING). The decision file MUST
include `axis_verdicts: {fsm_phantom: APPROVED|REJECTED,
capability_token_rotation: APPROVED|REJECTED}`. Both axis-verdicts
must be APPROVED for the aggregate `decision` to be APPROVED;
asymmetric verdicts (one APPROVED, one REJECTED) collapse to
aggregate REJECTED. Operator-Hand commits the updated
`state/welle-5-pre-auditor-decision.json` via a Mira-Hand-PR with
explicit `pre-auditor-decision-update` label. The PR is **not auto-
mergeable**: it requires AR-pair sign-off as a sanity-check on the
schema before merge.

**Owner**: Operator-Hand (Mira), AR-pair sanity-check.

**Stop-on-Fail**: `WELLE-5-P3-HOLD` -- if REJECTED, Welle-5-Day
becomes `WELLE-5-VERDICT-NO-GO`; if PENDING extended past 06:00 CEST,
Welle-5-Day defers by 24 h.

**Verdict-Marker**: `WELLE-5-P3-APPROVED` (green, both axes APPROVED,
AR-pair-sanity passed, PR merged), `WELLE-5-P3-PENDING-EXTENDED`
(yellow, decision file PENDING with `deferred_until_utc` field
present), `WELLE-5-P3-AXIS-ASYMMETRIC` (yellow, one axis APPROVED
one REJECTED; collapses to NO-GO unless AR-Hand-Override
documented), `WELLE-5-P3-HOLD` (red, aggregate REJECTED or PR-merge-
fail).

**Sandbox-OK**: no (merge-mutating action; in dry-run, the PR is
created but not merged).

### P4 -- Pre-Auditor-Decision-Propagation-Check

**Time-Window**: 05:30 -- 06:00 CEST on Welle-5-Day-Morning.

**Action**: run the welle-5-hot-spot-probe-aggregator
(`tooling/ci/welle_5_hot_spot_aggregator.py`) and confirm Check-4
(IIA-1130-Pre-Auditor-Decision-Tracking) reports `green`. Confirm
that the aggregator emits `cross_welle_propagation` block with
`pre_conditional_blocked: []` (empty list -- downstream Welle-6/7
are NOT pre-conditionally blocked by Welle-5 fsm-phantom or
capability-token-rotation drift). Additionally confirm
`kw_26_doppel_welle.welle_4_partner_status` is `green|caution` (red
on the Welle-4 partner cascades into Welle-5-P4-HOLD).

**Owner**: Operator-Hand (Mira), Tomas (Matrix-Lead) reads artifact.

**Stop-on-Fail**: `WELLE-5-P4-HOLD` -- if Check-4 reports red/yellow,
Welle-5-Day stays on calendar but blocks at P4 until the upstream
state reconciles. If the `pre_conditional_blocked` list is non-
empty, Welle-6/7 are also flagged as downstream-blocked and the
marathon-dashboard tile flips to `WELLE-5-CASCADE-RISK`. If the
KW-26-Doppel-Welle partner (Welle-4) status is red, Welle-5
de-couples from the Doppel-Welle and reschedules to KW-26-Do-solo
(operator-hand decision).

**Verdict-Marker**: `WELLE-5-P4-PROPAGATION-CLEAR` (green),
`WELLE-5-P4-PROPAGATION-YELLOW` (yellow, single check yellow OR
Welle-4-partner caution), `WELLE-5-P4-HOLD` (red, propagation blocked
or Welle-4-partner red).

**Sandbox-OK**: yes (probe is hermetic, no side-effects).

## §2 -- Standard-Welle-5 Day-Sequence (06:00 -- 12:00 CEST)

After P1..P4 pass green, the Standard-Welle-Day-Sequence proceeds
**unchanged** from the Tag-66 Eve-Recipe §4.4 + phase-3c-welle-5-
runbook §3:

* **06:00 -- 06:30 CEST**: Stand-up.
* **06:30 -- 09:00 CEST**: Welle-5-Merge (per phase-3c-welle-5-
  runbook §3). In the KW-26-Doppel-Welle, Welle-4-Merge runs in
  parallel; merge-conflict-coordination is via the matrix-lead
  voice-channel.
* **09:00 -- 10:00 CEST**: Welle-1/2/3-Stability-Check (and Welle-4
  partner stability, given Doppel-Welle).
* **10:00 -- 11:00 CEST**: Welle-5-Smoke + Welle-4-Smoke (parallel,
  per KW-26-Doppel-Welle).
* **11:00 -- 11:30 CEST**: Dashboard-Update.
* **11:30 -- 12:00 CEST**: AR-Sign-off.

The Welle-5-Step-5-Cross-Modul-Stress (`scripts/doppelbetrieb-score-
aggregator.py --mode=cross-modul-stress`) **must** be re-run between
Welle-5-Smoke and Dashboard-Update; this is the operator-side
equivalent of the CI workflow Step 5 (per phase-3c-welle-5-runbook
§"Step 5 -- Cross-modul-stress"). The Cross-Modul-Stress probe is
symmetric between Welle-4 and Welle-5 and must show green on both
sides.

## §3 -- Post-Sequence P5 (12:00 -- 13:00 CEST)

### P5 -- Pre-Auditor-Final-Sign-off-Commit

**Time-Window**: 12:00 -- 13:00 CEST on Welle-5-Day, after the
standard AR-Sign-off.

**Action**: the designated external Pre-Auditor confirms the
post-merge state of Welle-5 (Welle-1/2/3/4/5-Stability-Check green,
Welle-5-Smoke green, Welle-4-Smoke green, FSM-Phantom-Detection live
indicator green, Capability-Token-Rotation-Drift indicator green)
and updates `state/welle-5-pre-auditor-decision.json` with a final
`decision_finalised_at_utc` timestamp, `post_merge_review:
"clean|drift|defect"` field, and `axis_post_merge: {fsm_phantom:
clean|drift|defect, capability_token_rotation: clean|drift|defect}`
field. Operator-Hand commits via Mira-Hand-PR with `pre-auditor-
final-sign-off` label.

**Owner**: External Pre-Auditor produces the artifact; Operator-Hand
(Mira) commits.

**Stop-on-Fail**: `WELLE-5-P5-DRIFT` if any axis-post-merge reports
`drift`; the marathon proceeds but the Welle-6/7-cascade-watch is
activated. `WELLE-5-P5-DEFECT` if any axis-post-merge reports
`defect`; Welle-6/7 defer 24 h and Henrik (Internal Audit) is
notified for a Cross-Welle-Hot-Spot-Re-Probe with explicit
capability-token-rotation-drift forensic focus.

**Verdict-Marker**: `WELLE-5-P5-CLEAN` (green, both axes clean),
`WELLE-5-P5-DRIFT` (yellow, at least one axis drift), `WELLE-5-P5-
DEFECT` (red, at least one axis defect).

**Sandbox-OK**: no (commit-mutating action).

## §4 -- Welle-5-Day Aggregate Verdict-Roll-up

The aggregate Welle-5-Day verdict is computed from P1..P5 plus the
Standard-Welle-Day green-state:

| All P1..P5 green + Welle-Day clean | -> `WELLE-5-VERDICT-CUTOVER-DONE` |
| Any P-step yellow, all rest green | -> `WELLE-5-VERDICT-CAUTION` |
| P3 yellow (PENDING-EXTENDED) | -> `WELLE-5-VERDICT-DEFER-24H` |
| P3 yellow (AXIS-ASYMMETRIC, no override) | -> `WELLE-5-VERDICT-NO-GO` |
| P3 red (REJECTED) | -> `WELLE-5-VERDICT-NO-GO` |
| P4 yellow (Welle-4-partner-caution) | -> `WELLE-5-VERDICT-DOPPEL-DECOUPLE` |
| P5 red (DEFECT) | -> `WELLE-5-VERDICT-CASCADE-WATCH` |
| Any other red | -> `WELLE-5-VERDICT-HOLD` |

The aggregate verdict is emitted to `state/welle-5-day-verdict.json`
and consumed by the marathon-dashboard-tile-emitter.

## §5 -- Rollback-Pfade (Welle-5-spezifisch)

Welle-5-spezifische Rollback-Pfade ergaenzen die fuenf generischen
R1..R5-Pfade aus dem Tag-66 Eve-Recipe §5:

### R-W5-A -- Pre-Auditor-Designation-Failure

**Trigger**: P1-HOLD persists past 48-h-window AND AR-Hand-
escalation cannot designate within 24 h. Or: designated Pre-Auditor
declares IIA-1120 conflict-of-interest after 24-h-window has begun.

**Recovery**: defer Welle-5-Day by minimum 72 h. Falls out of KW-26-
Doppel-Welle; reschedules to KW-27-Mo-solo at earliest. Marathon-
Dashboard flips Welle-5-tile to `DESIGNATION-PENDING`. Welle-6/7
stay on calendar but are pre-conditionally flagged.

**Recovery-Time-Budget**: minimum 72 h (24 h re-escalation + 48 h
new review window).

**Fall-back-Pin**: Welle-5-component default backend stays `python`
(no flip). Capability-Token-Rotation continues on the Python-FSM-
resolver path.

### R-W5-B -- Pre-Auditor-REJECTED-Decision (Aggregate or Axis)

**Trigger**: P3 receives an aggregate-REJECTED decision file, OR P3
receives an AXIS-ASYMMETRIC verdict (one axis REJECTED) without an
AR-Hand-Override on file.

**Recovery**: invoke the Welle-5-Henrik-Audit-Loop -- Henrik
(Internal Audit) reviews the Pre-Auditor's rationale per axis
(fsm-phantom and capability-token-rotation are reviewed
independently) and either endorses or contests the REJECTED axis-
verdict. If endorsed, the rejected axis substrate is re-engineered
per Henrik recommendations and a new Pre-Auditor-Review-Cycle
(P1..P5) re-runs. If contested, AR-Hand-Entscheidung breaks the
tie.

**Recovery-Time-Budget**: 7..14 days (Henrik review + substrate
re-engineering + new review cycle). Capability-Token-Rotation-
specific re-engineering may extend the budget by an additional 7
days (Reza Cross-Review-Zone-B disziplin).

**Fall-back-Pin**: Welle-5-component default backend stays `python`.
Welle-6/7 either also defer (cascade-block) or proceed without
Welle-5-dependency (per ADR-0066 substrate-coupling-map).

### R-W5-C -- Post-Merge-DEFECT-Cascade (Capability-Token-Rotation
Forensic Branch)

**Trigger**: P5 reports `DEFECT` on the capability-token-rotation
axis -- post-merge state shows Capability-Token-Rotation-Drift
between Rust-FSM-resolver and Python-FSM-resolver after Welle-5-
merge landed.

**Recovery**: invoke generic R3 (Welle-N-Post-Cutover-Defect)
**plus** the Welle-5-specific cascade-watch on Welle-6/7 **plus** a
forensic capability-token-rotation-drift trace via the Reza
Cross-Review-Zone-B Wirelang-Layer-2-team. Henrik runs the Cross-
Welle-Hot-Spot-Re-Probe with capability-token-rotation-drift
forensic focus. Decision to roll-forward or roll-back rests on the
Re-Probe verdict + AR-pair sign-off **plus** a Pre-Auditor-Cascade-
Review (compressed to 12 h).

**Recovery-Time-Budget**: 12..36 h.

**Fall-back-Pin**: rollback Welle-5-merge if Re-Probe + Pre-Auditor
cascade-review both flag red. Welle-6/7 stay deferred until re-
validation. Capability-Token-Rotation falls back to Python-FSM-
resolver-path until forensic-trace is closed.

### R-W5-D -- KW-26-Doppel-Welle-Decouple

**Trigger**: P4 reports `WELLE-5-P4-PROPAGATION-YELLOW` with Welle-
4-partner-caution OR Welle-4-Day reports red after Welle-5-P3-
APPROVED has already merged.

**Recovery**: de-couple Welle-5 from the KW-26-Doppel-Welle. Welle-
4-Day-Sequence handles its own rollback per its own R-W4-* paths
(forthcoming Tag-74-Patch); Welle-5 either proceeds solo (if its own
P1..P5 are green and the Cross-Modul-Stress probe shows isolated
Welle-5-substrate green) or defers to KW-26-Do-solo.

**Recovery-Time-Budget**: 0..24 h (decision-only).

**Fall-back-Pin**: Welle-5 keeps cutover progress if P1..P5 all
green; Welle-4 handles its own fall-back-pin per Tag-74-Patch.

## §6 -- AR-Hand-Touchpoints (Welle-5-spezifisch)

In addition to the six generic AR-Hand-Touchpoints TP1..TP6 from the
Tag-66 Eve-Recipe §6, Welle-5-Day introduces three Welle-5-specific
Touchpoints:

### TP-W5-1 -- Pre-Auditor-Designation-Sign-off (T-48 h)

**Question**: "Confirm the designated external Pre-Auditor and the
48-h review window, with mandate covering BOTH fsm-phantom AND
capability-token-rotation axes?"

**Stop-on-Fail**: P1-HOLD -> Welle-5-defer (falls out of KW-26-
Doppel-Welle if defer >24 h).

**AR-Hand**: Mandatory pair-mode.

### TP-W5-2 -- P3-Decision-Commit-Sanity (T-1 h)

**Question**: "Confirm the Pre-Auditor's decision file: both
axis_verdicts APPROVED (aggregate APPROVED), schema-valid, ready to
commit?"

**Stop-on-Fail**: P3-HOLD -> Welle-5-defer. P3-AXIS-ASYMMETRIC ->
AR-pair decides whether to invoke AR-Hand-Override or fall to NO-GO.

**AR-Hand**: Mandatory pair-mode.

### TP-W5-3 -- P5-Post-Merge-Cascade-Sign-off (T+5 h)

**Question**: "Confirm Pre-Auditor's post-merge-review: both axes
CLEAN (fsm-phantom + capability-token-rotation)? Welle-4 partner
state? KW-26-Doppel-Welle aggregate clean?"

**Stop-on-Fail**: P5-DRIFT -> cascade-watch on Welle-6/7 activated;
P5-DEFECT -> R-W5-C invoked.

**AR-Hand**: Mandatory pair-mode.

## §7 -- Helper-Substrat

| Artifact | Path |
|---|---|
| Welle-5-Hot-Spot-Probe Aggregator (Check-4-Owner) | `tooling/ci/welle_5_hot_spot_aggregator.py` |
| Welle-5-Day Recipe-Patch Verifier (Tag-73) | `tooling/ci/verify_welle_5_recipe_patch_doc.py` |
| Welle-5-Day Pre-Auditor-State-File | `state/welle-5-pre-auditor-decision.json` |
| Welle-5-Day FSM-Phantom-State-File | `state/welle-5-fsm-phantom-detection.json` |
| Welle-5-Day Capability-Token-Rotation-Drift-State-File | `state/welle-5-capability-token-rotation-drift.json` |
| Welle-5-Day Aggregate-Verdict-File | `state/welle-5-day-verdict.json` |
| Welle-5-Day Marathon-Dashboard-Tile | (per marathon-dashboard-substrate) |
| Welle-5-Day Test-Suite | `tests/observability/test_welle_5_recipe_patch_tag73.py` |

## §8 -- Sandbox-Posture

Per ADR-0058 + AR-Direktive Tag-44 + AR-Direktive Tag-66 + AR-
Direktive Tag-71 (Welle-3-Patch precedent), this recipe-patch is
**doc-form-only** in the hermetic sandbox. Operator-Hand actions
(PR-creates, PR-merges, state-file commits) happen in the live
environment with explicit Mira-Hand-Authorisation per push. The
Tag-73-verifier and the Welle-5-Hot-Spot-Probe-Aggregator are both
stdlib-only Python and run hermetically in CI; neither produces
side-effects outside the artifact tree.

The Capability-Token-Rotation-Drift forensic trace (R-W5-C) crosses
Reza-Cross-Review-Zone-B (NATS-JetStream-Schema × Wirelang-Layer-2)
and is therefore additionally protocol-guarded; the operator-hand
must coordinate with Reza before invoking the forensic-trace branch.

## §9 -- Cross-Substrate-Links

| Link | Path |
|---|---|
| Tag-66 Eve-Recipe Konsolidat | `docs/operations/operator-hand-cutover-eve-final-recipe.md` |
| Welle-3-Recipe-Patch (Tag-71 precedent) | `docs/operations/operator-hand-welle-3-eve-recipe-patch.md` |
| Tag-69 G1+G2 Last-Mile Checklist | `docs/operations/g1-g2-last-mile-operator-checklist.md` |
| Tag-70 Cross-Validation-Probe | `tooling/ci/cross_validate_eve_recipes.py` |
| Welle-5-Hot-Spot-Probe Runbook | `docs/ci/welle-5-hot-spot-probe-runbook.md` |
| Welle-5-Validation Runbook | `docs/operations/phase-3c-welle-5-runbook.md` |
| Welle-4-Runbook (KW-26-Doppel-Welle partner) | `docs/operations/phase-3c-welle-4-runbook.md` |
| phase-3c-cutover-runbook | `docs/operations/phase-3c-cutover-runbook.md` |
| Henrik Tag-44 Pre-Mortem | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-44-pre-mortem-done.md` |
| Henrik Tag-45 Mitigation-Map-Deep-Dives | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-45-mitigation-map-done.md` |

-- Kai
