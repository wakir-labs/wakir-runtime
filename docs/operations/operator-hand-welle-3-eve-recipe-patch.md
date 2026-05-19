---
title: "Operator-Hand Welle-3 Day-of-Recipe-Patch (Tag-71)"
status: "active"
owner: "kai"
audience: "operator,ar,engineering,internal-audit"
created: "2026-05-19"
tag: "tag-71"
predecessors:
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
  - "docs/operations/phase-3c-welle-3-runbook.md"
  - "docs/operations/g1-g2-last-mile-operator-checklist.md"
  - "docs/ci/welle-3-hot-spot-probe-runbook.md"
related_adrs:
  - "ADR-0065"
  - "ADR-0066"
related_docs:
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
  - "docs/operations/phase-3c-welle-3-runbook.md"
  - "docs/operations/welle-3-day-0-pipeline-runbook.md"
  - "docs/operations/welle-3-telemetry-runbook.md"
  - "docs/ci/welle-3-hot-spot-probe-runbook.md"
  - "docs/operations/phase-3c-cutover-runbook.md"
related_prs:
  - "#422"
  - "#447"
related_memory:
  - "Welle-3 hat Pre-Auditor-Section-11-Disziplin (IIA-1130). Standard-Welle-Pattern reicht nicht."
---

# Operator-Hand Welle-3 Day-of-Recipe-Patch

**Tag-71 Companion-Doc** zum Tag-66 Eve-Recipe-Konsolidat. Welle-3
ist die einzige Welle in der Phase-3c-Marathon-Sequenz mit
**Pre-Auditor-Section-11-Disziplin** (IIA-1130). Standard-Welle-
Pattern (Stand-up -> Welle-Merge -> Stability-Check -> Welle-Smoke ->
Dashboard-Update -> AR-Sign-off) ist fuer Welle-3 **nicht
hinreichend**: vor dem Welle-Merge muessen vier zusaetzliche
**Pre-Auditor-Signaling-Schritte** P1..P4 die Operator-Hand passieren,
und nach dem Welle-Merge ein fuenfter Post-Sign-off-Step P5.

## Scope und Abgrenzung

Diese Doc ist **kein Ersatz** fuer das Tag-66 Eve-Recipe oder das
phase-3c-welle-3-runbook. Sie ist eine **chirurgische Patch-Lage**
ueber dem Welle-3-Day-Section des Tag-66 Eve-Recipes (§4.2 dort,
T0+2-Block) und ueber dem phase-3c-welle-3-runbook (Step 3).

Die Patch-Lage besteht aus:

* **Welle-3-Day Pre-Sequence P1..P4** -- vier Pre-Auditor-Signaling-
  Schritte, jeweils mit Owner, Action, Stop-on-Fail, Verdict-Marker,
  die **vor** dem Standard-Welle-Stand-up (06:00 CEST) liegen
  muessen.
* **Welle-3-Day Post-Sequence P5** -- ein Post-Sign-off-Step der
  **nach** dem Standard-AR-Sign-off (12:00 CEST) den
  Pre-Auditor-Decision-File commitet und an die Welle-4/5/7-
  Downstream-Workflows propagiert.

## Zeit-Domain

Welle-3 ist die einzige Welle mit AR-fluktuierender Date-Domain:

| Anker | Date | Quelle |
|---|---|---|
| Tag-66 Eve-Recipe §4.2 | T0+2 = KW-24 Mi 2026-06-10 | Tag-66 Marathon-Plan, urspruengliche ADR-0066-Sequenz |
| ADR-0066 §Welle-Sequenz (solo) | KW-25 Mo 2026-06-15 | ADR-0066 spaeter-revidiert (Welle-3 als KW-25-solo) |
| Brief Tag-71 Auftrag | KW-24 Fr 2026-06-13 | Continuous-Mode-Spawn-Anker |

**Operativer Schluss**: die exakte Welle-3-Day-Datum ist nicht
finalisiert (drei Anker im Korpus). Diese Patch-Lage adressiert
die Welle-3-Day-**Sequenz** unabhaengig vom exakten Datum. Der
Tag-69-Last-Mile-Checklist legt T0 = 2026-06-08 fest; Welle-3-Day
ist innerhalb des KW-24/KW-25-Fensters ein operator-hand-
fixierbarer Anker per AR-Hand-Entscheidung.

Der Pre-Auditor-Designation-Step (P1) muss **mindestens 48 h vor**
dem finalisierten Welle-3-Day landen, damit der Pre-Auditor-Review
realistisch ist.

## Pre-Auditor-Section-11-Hintergrund (IIA-1130)

Henrik Tag-44 Pre-Mortem (`agents-workspaces/mira/inbox/2026-05-18-
henrik-tag-44-pre-mortem-done.md`) und Tag-39 Welle-6+7-Pre-Audit-
Bundle identifizieren Welle-3 als #1 Cross-Welle-Hot-Spot mit
strukturellem Self-Reference-Trap-Risiko (`bridge_audit_writer` ist
Cutover-Subjekt und Audit-Stream-Emitter gleichzeitig). IIA-1130
"Impairment to Independence or Objectivity" verbietet, dass die
Cutover-Entscheidung von einem Reviewer kommt, der gleichzeitig
Co-Eigner des Cutover-Substrats ist.

Daraus folgt: die Welle-3-Day-Sign-off-Entscheidung kann **nicht**
vom Standard-AR-Pair-Mode allein getragen werden. Sie braucht
einen externen Pre-Auditor, der von der AR-Hand designiert wird,
und dessen Sign-off als hard-pass-Voraussetzung neben dem AR-Pair-
Sign-off steht.

## §1 -- Pre-Sequence P1..P4 (vor 06:00 CEST am Welle-3-Day)

### P1 -- Pre-Auditor-Designation-Verify

**Time-Window**: 48 h vor Welle-3-Day, taegliches Re-Check bis
Welle-3-Day-Morning 05:00 CEST.

**Action**: verify `state/welle-3-pre-auditor-decision.json` exists,
parses, has `auditor_role: "external-pre-auditor"`, `decision`
field is one of {`PENDING`, `APPROVED`, `REJECTED`}. The 48-h-
ahead window REQUIRES at minimum a `PENDING` entry naming the
designated external Pre-Auditor.

**Owner**: Operator-Hand (Mira).

**Stop-on-Fail**: `WELLE-3-P1-HOLD` -- Welle-3-Day-Sequence does
NOT start. Operator-Hand triggers AR-pair-mode escalation to
fast-track Pre-Auditor designation. Until file lands with at
minimum PENDING, Welle-3 stays on the calendar but does not
execute.

**Verdict-Marker**: `WELLE-3-P1-PRE-AUDITOR-DESIGNATED` (green),
`WELLE-3-P1-PENDING` (yellow, file present with PENDING decision),
`WELLE-3-P1-HOLD` (red, file missing or schema invalid).

**Sandbox-OK**: yes, no merge-mutating action.

### P2 -- Pre-Auditor-Review-Window-Confirm

**Time-Window**: 24 h vor Welle-3-Day.

**Action**: confirm via AR-pair voice channel that the designated
Pre-Auditor has had a contiguous 24-h review window with access
to:

* Welle-3 hot-spot probe last 7 daily envelopes
  (`.welle-3-hot-spot-probe/` artifacts).
* `state/welle-3-validation-last-verdict.json`.
* `state/welle-3-audit-trail-integrity.json`.
* Tag-44 Henrik Pre-Mortem document.
* phase-3c-welle-3-runbook §3 (Step 4 independent-oracle method).

**Owner**: AR-pair (Mira moderates, AR-pair confirms voice-channel
contact).

**Stop-on-Fail**: `WELLE-3-P2-HOLD` -- Welle-3-Day defers by
24 h. Re-attempt next morning.

**Verdict-Marker**: `WELLE-3-P2-REVIEW-WINDOW-CONFIRMED` (green),
`WELLE-3-P2-REVIEW-WINDOW-PARTIAL` (yellow, less than 24-h-
contiguous), `WELLE-3-P2-HOLD` (red, contact failed).

**Sandbox-OK**: yes.

### P3 -- Pre-Auditor-Decision-Receive

**Time-Window**: 04:30 -- 05:30 CEST on Welle-3-Day-Morning.

**Action**: receive the Pre-Auditor's signed decision file update
(APPROVED, REJECTED, or extended-PENDING). Operator-Hand commits
the updated `state/welle-3-pre-auditor-decision.json` via a
Mira-Hand-PR with explicit `pre-auditor-decision-update` label.
The PR is **not auto-mergeable**: it requires AR-pair sign-off as
a sanity-check on the schema before merge.

**Owner**: Operator-Hand (Mira), AR-pair sanity-check.

**Stop-on-Fail**: `WELLE-3-P3-HOLD` -- if REJECTED, Welle-3-Day
becomes `WELLE-3-VERDICT-NO-GO`; if PENDING extended past
06:00 CEST, Welle-3-Day defers by 24 h.

**Verdict-Marker**: `WELLE-3-P3-APPROVED` (green, decision file
APPROVED, AR-pair-sanity passed, PR merged), `WELLE-3-P3-PENDING-
EXTENDED` (yellow, decision file PENDING with `deferred_until_utc`
field present), `WELLE-3-P3-HOLD` (red, REJECTED or PR-merge-fail).

**Sandbox-OK**: no (merge-mutating action; in dry-run, the PR
is created but not merged).

### P4 -- Pre-Auditor-Decision-Propagation-Check

**Time-Window**: 05:30 -- 06:00 CEST on Welle-3-Day-Morning.

**Action**: run the welle-3-hot-spot-probe-aggregator
(`tooling/ci/welle_3_hot_spot_aggregator.py`) and confirm Check-4
(IIA-1130-Pre-Auditor-Decision-Tracking) reports `green`. Confirm
that the aggregator emits `cross_welle_propagation` block with
`pre_conditional_blocked: []` (empty list -- downstream Welle-4/5/7
are NOT pre-conditionally blocked by Welle-3 audit-trail-integrity).

**Owner**: Operator-Hand (Mira), Tomas (Matrix-Lead) reads
artifact.

**Stop-on-Fail**: `WELLE-3-P4-HOLD` -- if Check-4 reports
red/yellow, Welle-3-Day stays on calendar but blocks at P4 until
the upstream state reconciles. If the `pre_conditional_blocked`
list is non-empty, Welle-4/5/7 are also flagged as downstream-
blocked and the marathon-dashboard tile flips to `WELLE-3-CASCADE-
RISK`.

**Verdict-Marker**: `WELLE-3-P4-PROPAGATION-CLEAR` (green),
`WELLE-3-P4-PROPAGATION-YELLOW` (yellow, single check yellow),
`WELLE-3-P4-HOLD` (red, propagation blocked).

**Sandbox-OK**: yes (probe is hermetic, no side-effects).

## §2 -- Standard-Welle-3 Day-Sequence (06:00 -- 12:00 CEST)

After P1..P4 pass green, the Standard-Welle-Day-Sequence proceeds
**unchanged** from the Tag-66 Eve-Recipe §4.2 + phase-3c-welle-3-
runbook §3:

* **06:00 -- 06:30 CEST**: Stand-up.
* **06:30 -- 09:00 CEST**: Welle-3-Merge (per phase-3c-welle-3-
  runbook §3).
* **09:00 -- 10:00 CEST**: Welle-1/2-Stability-Check.
* **10:00 -- 11:00 CEST**: Welle-3-Smoke.
* **11:00 -- 11:30 CEST**: Dashboard-Update.
* **11:30 -- 12:00 CEST**: AR-Sign-off.

The Welle-3-Step-4-Independent-Oracle (`scripts/doppelbetrieb-
score-aggregator.py --mode=cross-modul-stress`) **must** be re-run
between Welle-3-Smoke and Dashboard-Update; this is the
operator-side equivalent of the CI workflow Step 4 (per
phase-3c-welle-3-runbook §"Welle-3 Step 4 - independent oracle").

## §3 -- Post-Sequence P5 (12:00 -- 13:00 CEST)

### P5 -- Pre-Auditor-Final-Sign-off-Commit

**Time-Window**: 12:00 -- 13:00 CEST on Welle-3-Day, after the
standard AR-Sign-off.

**Action**: the designated external Pre-Auditor confirms the
post-merge state of Welle-3 (Welle-1/2/3-Stability-Check green,
Welle-3-Smoke green, no audit-trail-integrity drift) and updates
`state/welle-3-pre-auditor-decision.json` with a final
`decision_finalised_at_utc` timestamp and `post_merge_review:
"clean|drift|defect"` field. Operator-Hand commits via Mira-Hand-PR
with `pre-auditor-final-sign-off` label.

**Owner**: External Pre-Auditor produces the artifact; Operator-
Hand (Mira) commits.

**Stop-on-Fail**: `WELLE-3-P5-DRIFT` if post-merge-review reports
`drift`; the marathon proceeds but the Welle-4/5/7-cascade-watch
is activated. `WELLE-3-P5-DEFECT` if post-merge-review reports
`defect`; Welle-4/5/7 defer 24 h and Henrik (Internal Audit) is
notified for a Cross-Welle-Hot-Spot-Re-Probe.

**Verdict-Marker**: `WELLE-3-P5-CLEAN` (green), `WELLE-3-P5-DRIFT`
(yellow), `WELLE-3-P5-DEFECT` (red).

**Sandbox-OK**: no (commit-mutating action).

## §4 -- Welle-3-Day Aggregate Verdict-Roll-up

The aggregate Welle-3-Day verdict is computed from P1..P5 plus the
Standard-Welle-Day green-state:

| All P1..P5 green + Welle-Day clean | -> `WELLE-3-VERDICT-CUTOVER-DONE` |
| Any P-step yellow, all rest green | -> `WELLE-3-VERDICT-CAUTION` |
| P3 yellow (PENDING-EXTENDED) | -> `WELLE-3-VERDICT-DEFER-24H` |
| P3 red (REJECTED) | -> `WELLE-3-VERDICT-NO-GO` |
| P5 red (DEFECT) | -> `WELLE-3-VERDICT-CASCADE-WATCH` |
| Any other red | -> `WELLE-3-VERDICT-HOLD` |

The aggregate verdict is emitted to `state/welle-3-day-
verdict.json` and consumed by the marathon-dashboard-tile-emitter.

## §5 -- Rollback-Pfade (Welle-3-spezifisch)

Welle-3-spezifische Rollback-Pfade ergaenzen die fuenf
generischen R1..R5-Pfade aus dem Tag-66 Eve-Recipe §5:

### R-W3-A -- Pre-Auditor-Designation-Failure

**Trigger**: P1-HOLD persists past 48-h-window AND AR-Hand-
escalation cannot designate within 24 h.

**Recovery**: defer Welle-3-Day by minimum 72 h. Marathon-Dashboard
flips Welle-3-tile to `DESIGNATION-PENDING`. Welle-4/5/7 stay on
calendar but are pre-conditionally flagged.

**Recovery-Time-Budget**: minimum 72 h (24 h re-escalation + 48 h
new review window).

**Fall-back-Pin**: Welle-3-component default backend stays
`python` (no flip).

### R-W3-B -- Pre-Auditor-REJECTED-Decision

**Trigger**: P3 receives a REJECTED decision file.

**Recovery**: invoke the Welle-3-Henrik-Audit-Loop -- Henrik
(Internal Audit) reviews the Pre-Auditor's rationale and either
endorses or contests the REJECTED decision. If endorsed, Welle-3
substrate is re-engineered per Henrik recommendations and a new
Pre-Auditor-Review-Cycle (P1..P5) re-runs. If contested, AR-Hand-
Entscheidung breaks the tie.

**Recovery-Time-Budget**: 7..14 days (Henrik review + substrate
re-engineering + new review cycle).

**Fall-back-Pin**: Welle-3-component default backend stays
`python`. Welle-4/5/7 either also defer (cascade-block) or proceed
without Welle-3-dependency (per ADR-0066 substrate-coupling-map).

### R-W3-C -- Post-Merge-DEFECT-Cascade

**Trigger**: P5 reports `DEFECT` -- post-merge state shows
audit-trail-integrity drift after Welle-3-merge landed.

**Recovery**: invoke generic R3 (Welle-N-Post-Cutover-Defect)
**plus** the Welle-3-specific cascade-watch on Welle-4/5/7. Henrik
runs the Cross-Welle-Hot-Spot-Re-Probe. Decision to roll-forward
or roll-back rests on the Re-Probe verdict + AR-pair sign-off
**plus** a Pre-Auditor-Cascade-Review (compressed to 12 h).

**Recovery-Time-Budget**: 12..36 h.

**Fall-back-Pin**: rollback Welle-3-merge if Re-Probe + Pre-Auditor
cascade-review both flag red. Welle-4/5/7 stay deferred until
re-validation.

## §6 -- AR-Hand-Touchpoints (Welle-3-spezifisch)

In addition to the six generic AR-Hand-Touchpoints TP1..TP6 from
the Tag-66 Eve-Recipe §6, Welle-3-Day introduces three Welle-3-
specific Touchpoints:

### TP-W3-1 -- Pre-Auditor-Designation-Sign-off (T-48 h)

**Question**: "Confirm the designated external Pre-Auditor and the
48-h review window?"

**Stop-on-Fail**: P1-HOLD -> Welle-3-defer.

**AR-Hand**: Mandatory pair-mode.

### TP-W3-2 -- P3-Decision-Commit-Sanity (T-1 h)

**Question**: "Confirm the Pre-Auditor's APPROVED decision file
schema-valid, ready to commit?"

**Stop-on-Fail**: P3-HOLD -> Welle-3-defer.

**AR-Hand**: Mandatory pair-mode.

### TP-W3-3 -- P5-Post-Merge-Cascade-Sign-off (T+5 h)

**Question**: "Confirm Pre-Auditor's post-merge-review CLEAN,
no cascade-watch needed?"

**Stop-on-Fail**: P5-DRIFT -> cascade-watch on Welle-4/5/7
activated; P5-DEFECT -> R-W3-C invoked.

**AR-Hand**: Mandatory pair-mode.

## §7 -- Helper-Substrat

| Artifact | Path |
|---|---|
| Welle-3-Hot-Spot-Probe Aggregator (Check-4-Owner) | `tooling/ci/welle_3_hot_spot_aggregator.py` |
| Welle-3-Day Recipe-Patch Verifier (Tag-71) | `tooling/ci/verify_welle_3_recipe_patch_doc.py` |
| Welle-3-Day Pre-Auditor-State-File | `state/welle-3-pre-auditor-decision.json` |
| Welle-3-Day Aggregate-Verdict-File | `state/welle-3-day-verdict.json` |
| Welle-3-Day Marathon-Dashboard-Tile | (per marathon-dashboard-substrate) |
| Welle-3-Day Test-Suite | `tests/observability/test_welle_3_recipe_patch_tag71.py` |

## §8 -- Sandbox-Posture

Per ADR-0058 + AR-Direktive Tag-44 + AR-Direktive Tag-66, this
recipe-patch is **doc-form-only** in the hermetic sandbox.
Operator-Hand actions (PR-creates, PR-merges, state-file commits)
happen in the live environment with explicit Mira-Hand-Authorisation
per push. The Tag-71-verifier and the Welle-3-Hot-Spot-Probe-
Aggregator are both stdlib-only Python and run hermetically in
CI; neither produces side-effects outside the artifact tree.

## §9 -- Cross-Substrate-Links

| Link | Path |
|---|---|
| Tag-66 Eve-Recipe Konsolidat | `docs/operations/operator-hand-cutover-eve-final-recipe.md` |
| Tag-69 G1+G2 Last-Mile Checklist | `docs/operations/g1-g2-last-mile-operator-checklist.md` |
| Tag-70 Cross-Validation-Probe | `tooling/ci/cross_validate_eve_recipes.py` |
| Welle-3-Hot-Spot-Probe Runbook | `docs/ci/welle-3-hot-spot-probe-runbook.md` |
| Welle-3-Day-0-Pipeline Runbook | `docs/operations/welle-3-day-0-pipeline-runbook.md` |
| Welle-3-Telemetry Runbook | `docs/operations/welle-3-telemetry-runbook.md` |
| phase-3c-welle-3-runbook | `docs/operations/phase-3c-welle-3-runbook.md` |
| Henrik Tag-44 Pre-Mortem | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-44-pre-mortem-done.md` |
| Henrik Tag-39 Welle-6+7-Pre-Audit-Bundle | (per audit-spec) |

-- Kai
