---
title: "Operator-Hand Production-Bringup Recipe (Tag-76)"
status: "active"
owner: "kai"
audience: "operator,ar,engineering,internal-audit"
created: "2026-05-19"
tag: "tag-76"
predecessors:
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
  - "docs/operations/operator-hand-welle-3-eve-recipe-patch.md"
  - "docs/operations/operator-hand-welle-5-eve-recipe-patch.md"
  - "docs/operations/operator-hand-welle-6-eve-recipe-patch.md"
  - "docs/operations/operator-hand-welle-7-eve-recipe-patch.md"
  - "docs/operations/phase-3c-welle-7-runbook.md"
  - "docs/operations/phase-3c-cutover-runbook.md"
  - "docs/quality-gates/pre-cutover-acceptance-run-order.md"
  - "docs/quality-gates/phase-3-marathon-final-acceptance.md"
related_adrs:
  - "ADR-0065"
  - "ADR-0066"
related_docs:
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
  - "docs/operations/operator-hand-welle-7-eve-recipe-patch.md"
  - "docs/operations/phase-3c-welle-7-runbook.md"
  - "docs/operations/phase-3c-cutover-runbook.md"
  - "docs/quality-gates/pre-cutover-acceptance-run-order.md"
  - "docs/quality-gates/phase-3-marathon-final-acceptance.md"
related_prs:
  - "#477"
related_memory:
  - "Welle-7 ist Final-Sealing-Welle der Phase-3c. Post-Welle-7-Sign-off (Freitag 2026-07-03) folgt das Production-Bringup-Window Day-1..Day-7 (Sa 2026-07-04 -- Fr 2026-07-10). In diesem Window fires der Phase-3-COMPLETE-Marker (Day-1, sofern Global-Acceptance-Verdict APPROVED) ODER der NO-FIRE-Pfad (Day-1, sofern REJECTED). Day-2..Day-7 sind Stability-Window-Days mit Hot-Fix-Permission (Phase-3-close, nicht Phase-4-open) und AR-Vorzeichen 'Halt vor Phase 4' verbatim aktiv (Tag-66 Eve-Recipe §9). Day-7 erlaubt OPEN-J3/OPEN-K3-Closure-Records-Commit + Marathon-Final-Bilanz-Lieferbericht. Kein Phase-4-Substrate-Spawn vor explizitem AR-Hand-PHASE-4-RE-ARMED-Signal."
---

# Operator-Hand Production-Bringup Recipe

**Tag-76 Day-after-Welle-7-Sign-off Companion-Doc** zum Tag-66 Eve-
Recipe-Konsolidat und zum Tag-75 Welle-7-Day-of-Recipe-Patch. Diese
Doc beschreibt die **Production-Bringup-Operator-Aktionen Day-1 bis
Day-7** post-Welle-7-Sign-off (Sign-off-Datum 2026-07-03 Fr per
`docs/quality-gates/pre-cutover-acceptance-run-order.md` §3 Table-
Row Welle-7). Day-1 ist Samstag 2026-07-04; Day-7 ist Freitag
2026-07-10.

Das Tag-66 Eve-Recipe deckte den Marathon-Lauf bis T0+6 ab. Das
Tag-75 Welle-7-Day-of-Recipe-Patch deckte die Final-Sealing-Welle-7
selbst ab. **Diese Doc deckt das Day-after-Sign-off-Window ab** --
die sieben operativen Tage, die das Phase-3-COMPLETE-Marker-Fire,
die Initial-Production-Stability-Probe-Sequenz und die Phase-3-
Close-Out-Items (J3/K3-Closure, Marathon-Final-Bilanz, Phase-3-Post-
Mortem) tragen, **vor** dem expliziten AR-Hand-PHASE-4-RE-ARMED-
Signal.

Diese Doc baut auf der Tag-71/Tag-73/Tag-74/Tag-75 IIA-1130-Welle-
Patch-Cascade auf (Welle-3 Tag-71-Patch, Welle-5 Tag-73-Patch,
Welle-6 Tag-74-Patch, Welle-7 Tag-75-Patch) und setzt deren
Pre-Auditor-Decision-Substrate als Eingang voraus (insbesondere
Tag-75 P5 Final-Sealing-Decision-Commit).

Anders als das Eve-Recipe und das Welle-7-Patch ist diese Doc
**explizit Phase-3-close, nicht Phase-4-open**: jeder Day-N-Step
fuehrt entweder eine Phase-3-Schluss-Aktion aus oder pflegt eine
laufende Stability-Probe -- **keine Day-N-Aktion oeffnet Phase-4-
Substrate**. Das AR-Vorzeichen "Halt vor Phase 4" (Tag-65 AR-Signal,
verbatim in §9 dieser Doc) ist die governance-pin, die durch das
gesamte Day-1..Day-7-Window haelt und durch jeden Day-N-Spawn-
Filter durchgereicht wird.

## Scope und Abgrenzung

Diese Doc ist **kein Ersatz** fuer:

* Das Tag-66 Eve-Recipe (`operator-hand-cutover-eve-final-recipe.md`)
  -- das deckt T0..T0+6 (Welle-Cutover-Sequenz) ab.
* Das Tag-75 Welle-7-Patch (`operator-hand-welle-7-eve-recipe-
  patch.md`) -- das deckt den Welle-7-Cutover-Tag selbst ab,
  inklusive P5-Final-Sealing-Decision-Commit.
* Den phase-3c-cutover-runbook -- der deckt die Welle-Mechanik ab.

Diese Doc ist die **Post-Sign-off-Patch-Lage** ueber den Tag-66 Eve-
Recipe-Day-after-Section, mit folgendem Inhalt:

* **Day-1 (2026-07-04 Sa) -- Phase-3-COMPLETE-Marker-Fire-Day**: der
  Marker fires (APPROVED-Pfad) oder bleibt NO-FIRE (REJECTED-Pfad).
* **Day-2..Day-5 (2026-07-05 So -- 2026-07-08 Mi) -- Production-
  Stability-Window**: tägliche Probe-Aggregation, Hot-Fix-Permission
  (Phase-3-close only), AR-On-Call.
* **Day-6 (2026-07-09 Do) -- J3/K3-Closure-Window**: OPEN-J3 und
  OPEN-K3 Carry-Forwards koennen als `RESOLVED-INTENTIONAL`
  geschlossen werden (per Tag-64 Substrate).
* **Day-7 (2026-07-10 Fr) -- Marathon-Final-Bilanz-Day**: Marathon-
  Final-Bilanz Lieferbericht, Phase-3-Post-Mortem Anstoss, und
  AR-Hand-Window fuer das PHASE-4-RE-ARMED-Signal (kein Anspruch,
  nur Window-Anker).

Die Patch-Lage besteht aus **fuenf Production-Bringup-Steps B1..B5**
plus **drei AR-Hand-Touchpoints TP-PB-1..TP-PB-3** plus **vier
Rollback-Pfade R-PB-A..R-PB-D**, alle eingebettet in den Day-1..
Day-7-Kalender.

## Zeit-Domain

| Anker | Date | Quelle |
|---|---|---|
| Welle-7-Sign-off-Freitag | 2026-07-03 (Fr) | `docs/quality-gates/pre-cutover-acceptance-run-order.md` §3 Row Welle-7 |
| Day-1 -- Phase-3-COMPLETE-Marker-Fire-Day | 2026-07-04 (Sa) | Tag-76 Brief Day-after-Welle-7-Sign-off |
| Day-2 -- Stability-Window-Start | 2026-07-05 (So) | Tag-76 (T+1) |
| Day-3 | 2026-07-06 (Mo) | Tag-76 (T+2) |
| Day-4 | 2026-07-07 (Di) | Tag-76 (T+3) |
| Day-5 | 2026-07-08 (Mi) | Tag-76 (T+4) |
| Day-6 -- J3/K3-Closure-Window | 2026-07-09 (Do) | Tag-76 (T+5) |
| Day-7 -- Marathon-Final-Bilanz-Day | 2026-07-10 (Fr) | Tag-76 (T+6) |

**Operativer Schluss**: das Production-Bringup-Window ist sieben
Tage lang und endet am Freitag 2026-07-10 mit dem Marathon-Final-
Bilanz-Lieferbericht. Nach Day-7 bleibt der `PHASE-4-HOLD-VOR-RE-
ARM`-pin aktiv, bis das AR ein explizites `PHASE-4-RE-ARMED`-Signal
gibt. Das Window selbst macht **keinen** Anspruch auf einen Re-Arm-
Termin.

## §1 -- Phase-3-COMPLETE-Marker-Fire-Step (Day-1, 2026-07-04 Sa)

Day-1 traegt einen einzigen substanziellen Step: das Phase-3-
COMPLETE-Marker-Fire (oder NO-FIRE). Dieser Step ist die direkte
Konsequenz des Tag-75 P5-Final-Sealing-Decision-Commits. Welle-7-
Patch §3 P5 commitete `state/welle-7-pre-auditor-decision.json`
mit `final_sealing_intent`-Flag und triggerte
`tooling/ci/aggregate_pyramide_run_order_verdict.py`, das den
Global-Acceptance-Verdict in `state/phase-3-marathon-global-
verdict.json` materialisiert. Day-1 lesetauglicht diesen Verdict
und fires (oder unterlaesst) den Phase-3-COMPLETE-Marker.

### B1 -- Phase-3-COMPLETE-Marker-Fire (Day-1, 06:00 -- 10:00 CEST)

**Time-Window**: 06:00 -- 10:00 CEST am Day-1 (Samstag 2026-07-04).

**Action**:

1. Read `state/phase-3-marathon-global-verdict.json` -- the file MUST
   exist and MUST have been written by the Welle-7-Day P5 step
   (Tag-75 Patch §3). The file MUST contain
   `global_verdict: "APPROVED" | "REJECTED" | "DEFER"` AND
   `final_sealing_decision: "FIRE_PHASE_3_COMPLETE_MARKER" |
   "BLOCK_PHASE_3_COMPLETE_MARKER" | "DEFER_FINAL_SEALING"` AND
   `welle_7_p5_decision_commit_sha: <sha>` referencing the P5
   commit.
2. If `global_verdict == "APPROVED"` AND `final_sealing_decision
   == "FIRE_PHASE_3_COMPLETE_MARKER"`: fire the Phase-3-COMPLETE-
   marker by:
   a. Committing `state/phase-3-complete-marker.json` with
      `marker_state: "FIRED"`, `fire_timestamp_utc: <now>`,
      `welle_7_p5_decision_commit_sha: <sha>`,
      `marker_fire_actor: "operator-hand-mira"`,
      `governance_pin_holds: "PHASE-4-HOLD-VOR-RE-ARM"`.
   b. Committing the corresponding row to `activity-log.md` with
      marker-fire-anchor.
   c. Pushing the commit via Mira-Hand (Continuous-Mode authorised
      per memory `feedback_force_push_bundle_merge_ok`).
3. If `global_verdict == "REJECTED"` OR `final_sealing_decision ==
   "BLOCK_PHASE_3_COMPLETE_MARKER"`: enter the NO-FIRE-pfad by:
   a. Committing `state/phase-3-complete-marker.json` with
      `marker_state: "NO-FIRE"`, `no_fire_reason: <verdict-detail>`,
      `block_actor: "welle-7-pre-auditor"`,
      `governance_pin_holds: "PHASE-4-HOLD-VOR-RE-ARM"`.
   b. Eskalierung an AR-pair-mode via `inbox/`-Bericht.
4. If `final_sealing_decision == "DEFER_FINAL_SEALING"`: enter the
   DEFER-pfad by:
   a. Committing `state/phase-3-complete-marker.json` with
      `marker_state: "DEFERRED"`, `defer_until_utc:
      <deferred_until_utc-from-decision-file>`,
      `governance_pin_holds: "PHASE-4-HOLD-VOR-RE-ARM"`.
   b. Day-2..Day-7 continue under DEFER-state; Day-7 Marathon-
      Final-Bilanz documents the defer-state explicitly.

**Owner**: Operator-Hand (Mira), AR-pair-mode standby.

**Stop-on-Fail**: `B1-HOLD` -- if `state/phase-3-marathon-global-
verdict.json` is missing or malformed at Day-1 06:00 CEST, the
marker-fire-step does NOT execute; Day-1 enters `B1-HOLD-STATE`
and AR-pair-mode is engaged for Welle-7-Day-P5-re-execution. The
`PHASE-4-HOLD-VOR-RE-ARM` pin remains active.

**Verdict-Marker**:
* `PB-B1-MARKER-FIRED` (green, APPROVED-pfad, marker fired).
* `PB-B1-MARKER-NO-FIRE` (yellow, REJECTED-pfad, marker explicitly
  blocked, NO-FIRE-state committed).
* `PB-B1-MARKER-DEFERRED` (yellow, DEFER-pfad, marker deferred).
* `PB-B1-HOLD` (red, global-verdict-file missing or malformed).

**Sandbox-OK**: no (commit-mutating action; in dry-run, the commit
is staged but not pushed).

## §2 -- Production-Stability-Window-Days (Day-2..Day-5)

Day-2 bis Day-5 (So 2026-07-05 -- Mi 2026-07-08) sind tägliche
Stability-Window-Days. Jeder Day-N traegt einen einzigen Step (B2),
der die tägliche Stability-Probe-Aggregation ausfuehrt. Hot-Fix-
Permission ist eingeschraenkt auf Phase-3-Close-Items (siehe §9.3).

### B2 -- Daily-Stability-Probe-Aggregation (Day-2..Day-5, je 09:00 CEST)

**Time-Window**: 09:00 CEST am Day-2, Day-3, Day-4, Day-5.

**Action**:

1. Run the daily stability-probe-aggregator
   (`tooling/ci/aggregate_production_stability_probe.py` -- this
   helper lives alongside the Tag-76 substrate). The aggregator
   inputs are:
   a. `state/production-stability-day-<N>.json` (today's probe
      window output, written by the live-smoke-window job during
      00:00 -- 08:00 CEST).
   b. The Phase-3-COMPLETE-marker state file (must be FIRED,
      NO-FIRE, or DEFERRED -- the day MUST proceed regardless of
      marker-state, because Day-2..Day-5 are stability-probes for
      the Phase-3-close-window, not for the marker-fire itself).
2. The aggregator emits
   `state/production-stability-day-<N>-verdict.json` with one of:
   `STABLE`, `DEGRADED-NON-BLOCKING`, `DEGRADED-BLOCKING`.
3. `STABLE` -- commit + push, Day-N closes.
4. `DEGRADED-NON-BLOCKING` -- commit + push, AR-On-Call advised,
   Day-N closes.
5. `DEGRADED-BLOCKING` -- AR-pair-mode escalation; potential Hot-
   Fix-spawn (Phase-3-close only, see §9.3 for permitted-scope).

**Owner**: Operator-Hand (Mira), AR-On-Call mode (not pair-mode
unless escalated).

**Stop-on-Fail**: `B2-HOLD` -- if the day's probe-window output is
missing or the aggregator errors, the Day-N stability-verdict is
`UNKNOWN`. Re-attempt at next 09:00. If two consecutive days are
`UNKNOWN`, AR-pair-mode escalation.

**Verdict-Marker**:
* `PB-B2-DAY-N-STABLE` (green).
* `PB-B2-DAY-N-DEGRADED-NON-BLOCKING` (yellow).
* `PB-B2-DAY-N-DEGRADED-BLOCKING` (red, hot-fix triggered).
* `PB-B2-DAY-N-UNKNOWN` (red, probe-window missing or aggregator
  error).

**Sandbox-OK**: yes (commit + push are Mira-Hand-authorised per
Continuous-Mode memory; dry-run stages without pushing).

## §3 -- J3/K3-Closure-Window (Day-6, 2026-07-09 Do)

Day-6 ist das designierte Window fuer OPEN-J3 und OPEN-K3 Carry-
Forward-Closure als `RESOLVED-INTENTIONAL` per Tag-64 Substrate.
Diese sind **Phase-3-close-Items**, nicht Phase-4-open. Sie sind
explizit unter dem `PHASE-4-HOLD-VOR-RE-ARM`-pin erlaubt (Tag-66
Eve-Recipe §9.3 Item 3).

### B3 -- J3/K3-Closure-Records-Commit (Day-6, 09:00 -- 14:00 CEST)

**Time-Window**: 09:00 -- 14:00 CEST am Day-6 (Donnerstag
2026-07-10... korrigiert: 2026-07-09).

**Action**:

1. Verify OPEN-J3 status:
   * The Tag-66 Eve-Recipe T0+1 J3-Patch-Sequenz must have
     committed `state/open-j3-patch-applied.json` with
     `patch_state: "APPLIED"`.
   * J3-D image-rebuild + re-sign must have succeeded (no `J3-D-
     RED` carry-forward).
2. Verify OPEN-K3 status:
   * The Welle-Marathon must have completed with K3 sealed
     through T0+6 (no `K3-RED` flag).
3. Commit `state/open-j3-closure-record.json` with
   `j3_state: "RESOLVED-INTENTIONAL"`, `resolution_date:
   "2026-07-09"`, `resolution_actor: "operator-hand-mira"`,
   `phase_3_close_item: true`.
4. Commit `state/open-k3-closure-record.json` with
   `k3_state: "RESOLVED-INTENTIONAL"`, `resolution_date:
   "2026-07-09"`, `resolution_actor: "operator-hand-mira"`,
   `phase_3_close_item: true`.
5. Push via Mira-Hand (Continuous-Mode).

**Owner**: Operator-Hand (Mira), AR-On-Call.

**Stop-on-Fail**: `B3-HOLD` -- if either J3 or K3 status is not
clean (J3-D-RED carry-forward, K3-RED flag), closure does NOT
execute. The carry-forward continues into Day-7 and beyond and is
documented in Marathon-Final-Bilanz as carry-forward-into-Phase-3-
close-extension.

**Verdict-Marker**:
* `PB-B3-J3-K3-CLOSED` (green, both records committed).
* `PB-B3-J3-CLOSED-K3-CARRIED` (yellow, J3 closed, K3 carried).
* `PB-B3-K3-CLOSED-J3-CARRIED` (yellow, K3 closed, J3 carried).
* `PB-B3-J3-K3-CARRIED` (yellow, both carried).
* `PB-B3-HOLD` (red, status-check error).

**Sandbox-OK**: yes.

## §4 -- Marathon-Final-Bilanz-Day (Day-7, 2026-07-10 Fr)

Day-7 ist der designierte Day fuer Marathon-Final-Bilanz-
Lieferbericht und Phase-3-Post-Mortem-Anstoss. Diese sind
**Phase-3-close-Items** per Tag-66 Eve-Recipe §9.3 Items 1+2.

### B4 -- Marathon-Final-Bilanz-Lieferbericht (Day-7, 09:00 -- 14:00 CEST)

**Time-Window**: 09:00 -- 14:00 CEST am Day-7 (Freitag 2026-07-10).

**Action**:

1. Compose the Marathon-Final-Bilanz Lieferbericht
   (`agents-workspaces/mira/inbox/2026-07-10-marathon-final-bilanz.md`)
   referencing:
   * Welle-1..Welle-7 cutover-day-verdicts.
   * Phase-3-COMPLETE-marker-state (FIRED, NO-FIRE, or DEFERRED per
     Day-1 B1).
   * Day-2..Day-5 daily-stability-probe-verdicts.
   * Day-6 J3/K3-closure-records-state.
   * `state/phase-3-marathon-global-verdict.json` excerpt.
   * Per-Welle pre-auditor-decision-files (Welle-3, Welle-5,
     Welle-6, Welle-7) with axis-verdict-summary.
2. The Lieferbericht MUST include the verbatim AR-Vorzeichen "Halt
   vor Phase 4" anchor from §9 of this doc and MUST state
   "`PHASE-4-HOLD-VOR-RE-ARM` pin haelt; kein Phase-4-Substrate-
   Spawn vor explizitem AR-Hand-PHASE-4-RE-ARMED-Signal."
3. Commit + push.

**Owner**: Operator-Hand (Mira), AR-pair-mode for the final-bilanz-
sign-off (last AR-pair touch-point of the Marathon).

**Stop-on-Fail**: `B4-HOLD` -- if any required input is missing
(Day-1 marker-state, any Day-2..Day-5 verdict, Day-6 J3/K3 record),
the Lieferbericht enters DRAFT-state with missing-items
explicitly flagged. AR-pair-mode decides whether to publish DRAFT
or hold.

**Verdict-Marker**:
* `PB-B4-FINAL-BILANZ-DELIVERED` (green).
* `PB-B4-FINAL-BILANZ-DRAFT` (yellow, missing inputs, published
  with flags).
* `PB-B4-HOLD` (red, AR-pair decides hold).

**Sandbox-OK**: yes (Lieferbericht commit + push are Mira-Hand-
authorised).

### B5 -- Phase-3-Post-Mortem-Anstoss (Day-7, 14:00 -- 16:00 CEST)

**Time-Window**: 14:00 -- 16:00 CEST am Day-7.

**Action**:

1. Spawn-brief at audit-scope (Amara/Henrik) for Phase-3-Post-Mortem
   composition. The brief MUST include the `PHASE-4-HOLD-VOR-RE-
   ARM` substrate-marker (per Tag-66 Eve-Recipe §9.4 Mira-Hand-
   Spawn-Filter) and MUST not carry Phase-4 task-content.
2. The Post-Mortem itself is audit-scope and is NOT executed by
   Kai/Mira -- this step is only the spawn-anstoss.
3. After the Anstoss-Spawn, Day-7 closes the production-bringup-
   window. The `PHASE-4-HOLD-VOR-RE-ARM` pin remains active. No
   further day-by-day operator-hand recipe extends beyond Day-7
   under this Tag-76 doc -- the AR-Hand re-arm signal triggers a
   future Phase-4-Eve-Recipe (Kai-scope, but not authored here).

**Owner**: Operator-Hand (Mira).

**Stop-on-Fail**: `B5-HOLD` -- if the spawn-brief fails substrate-
marker-filter-check (Phase-4-content slips in), AR-pair-mode
escalation. Spawn does NOT execute until the brief is clean.

**Verdict-Marker**:
* `PB-B5-POST-MORTEM-ANGESTOSSEN` (green).
* `PB-B5-HOLD` (red, spawn-filter-fail).

**Sandbox-OK**: yes (spawn-anstoss is sandbox-safe; the spawn
itself is operator-hand-mira).

## §5 -- Rollback-Pfade R-PB-A..R-PB-D

Vier Rollback-Pfade decken die wesentlichen Failure-Modes des
Production-Bringup-Windows ab.

### R-PB-A -- Day-1-Marker-Fire-Defect

**Trigger**: B1-HOLD -- `state/phase-3-marathon-global-verdict.json`
is missing or malformed at Day-1 06:00 CEST. The Welle-7-Day P5
step did not produce its expected output, or the file was corrupted
between Day-0 and Day-1.

**Action**: AR-pair-mode escalation. Welle-7-Day P5 re-execution
attempt by the designated Pre-Auditor in coordination with AR-pair.
The B1-step retries at Day-1 14:00 CEST. If still HOLD, the marker-
fire defers to Day-2 06:00 CEST.

**Fall-back-pin**: If marker-fire-step is HOLD past Day-2 06:00
CEST, the Phase-3-COMPLETE-marker is treated as `NO-FIRE-DEFAULT`
and the Tag-76-Window proceeds with `PHASE-3-COMPLETE-NO-FIRE-
WELLE-7-P5-DEFECT` as the canonical marker-state. **The marker-
fire is then irreversible-blocked** until a formal Phase-3-RE-
OPEN-ADR explicitly re-opens the question.

**Phase-3-COMPLETE-state**: NO-FIRE.

### R-PB-B -- Stability-Window-Day-N-Blocking-Degradation

**Trigger**: B2-DEGRADED-BLOCKING on any Day-2..Day-5. A production-
stability-probe identifies a blocking degradation that the daily
window cannot absorb without operator-hand intervention.

**Action**: AR-pair-mode escalation. Hot-Fix-spawn permitted **only
for Phase-3-close items** (per §9.3): substrate that closes Phase-
3 substrate, not substrate that opens Phase-4 substrate. The Hot-
Fix-PR must carry the `PHASE-4-HOLD-VOR-RE-ARM` substrate-marker
and must not introduce 0.5.4+ persona-engine bumps.

**Fall-back-pin**: If the degradation cannot be resolved by a
Phase-3-close Hot-Fix, AR-pair-mode declares `PB-WINDOW-DEGRADED-
EXTENDED`. The Marathon-Final-Bilanz documents the extended
degradation. The `PHASE-4-HOLD-VOR-RE-ARM` pin holds; no Phase-4-
open work is permitted, including by way of "Phase-4 will fix
this".

**Phase-3-COMPLETE-state**: unaffected (marker-state was set on
Day-1 and is not revised by stability-window outcomes).

### R-PB-C -- J3-K3-Carry-Forward-into-Phase-3-Close-Extension

**Trigger**: B3-HOLD or B3-J3-K3-CARRIED on Day-6. One or both
Carry-Forwards cannot be closed as `RESOLVED-INTENTIONAL` because
the underlying substrate state is not clean.

**Action**: Carry-Forward continues. Day-7 Marathon-Final-Bilanz
documents the carry-forward as `PHASE-3-CLOSE-EXTENSION-J3-OR-K3`.
The carry-forward is NOT a Phase-4 item -- it remains Phase-3-
close-scope and may be resolved by future Phase-3-close Hot-Fixes
under continuing `PHASE-4-HOLD-VOR-RE-ARM` pin.

**Fall-back-pin**: AR-Hand may elect to re-arm Phase-4 with the
J3/K3 carry-forward outstanding, in which case the carry-forward
transitions to a Phase-4 closing-item. **This transition requires
explicit AR-Hand signal**; it does not happen by default at Day-7
close.

**Phase-3-COMPLETE-state**: unaffected (marker-state was set on
Day-1).

### R-PB-D -- Final-Bilanz-Spawn-Filter-Violation

**Trigger**: B5-HOLD -- the Phase-3-Post-Mortem-Anstoss spawn-brief
fails substrate-marker-filter-check because Phase-4 content slipped
in.

**Action**: AR-pair-mode escalation. The spawn-brief is reviewed
line-by-line for Phase-4-substrate-leak (per §9.4 Mira-Hand-Spawn-
Filter). The brief is revised, re-filtered, and only then
executed.

**Fall-back-pin**: If Phase-4-substrate-leak is systemic (multiple
filter-violations on revisions), AR-pair-mode declares `PB-SPAWN-
FILTER-INTEGRITY-BREACH` and pauses all Mira-Hand-spawns until the
filter is reinforced. The Phase-3-Post-Mortem-Anstoss is deferred
until the filter is clean.

**Phase-3-COMPLETE-state**: unaffected.

## §6 -- AR-Hand-Touchpoints TP-PB-1..TP-PB-3

Drei explizite AR-Hand-Touchpoints im Production-Bringup-Window.

### TP-PB-1 -- Day-1 Phase-3-COMPLETE-Marker-Fire-Sanity (2026-07-04, 10:00 CEST)

**AR-Hand**: pair-mode (Mira moderates, AR-pair confirms marker-
fire-action).

**Purpose**: Sanity-check on the Phase-3-COMPLETE-marker-fire (or
NO-FIRE) action by Operator-Hand at Day-1 09:00. The AR-pair
confirms that the marker-state-commit matches the Welle-7-Day P5
final_sealing_decision. **This is the single most consequential
touchpoint of the post-Welle-7 window**: it commits the marker-
state irreversibly (per §9 Halt-vor-Phase-4 governance).

**Sign-off-marker**: `PB-TP1-MARKER-SANITY-PASS` (green) or
`PB-TP1-MARKER-SANITY-FAIL` (red, triggers R-PB-A).

### TP-PB-2 -- Day-5 Stability-Window-Mid-Review (2026-07-08 Mi, 14:00 CEST)

**AR-Hand**: on-call (single AR, not pair).

**Purpose**: Mid-window review of Day-2..Day-5 stability-probe-
verdicts. The AR confirms that no DEGRADED-BLOCKING verdict went
unaddressed and that Hot-Fix-PRs (if any) carry the `PHASE-4-HOLD-
VOR-RE-ARM` substrate-marker.

**Sign-off-marker**: `PB-TP2-STABILITY-MID-PASS` (green),
`PB-TP2-STABILITY-MID-DEGRADED` (yellow, advisable), or
`PB-TP2-STABILITY-MID-ESCALATE` (red, AR-pair-mode trigger).

### TP-PB-3 -- Day-7 Marathon-Final-Bilanz-Sign-off (2026-07-10 Fr, 14:00 CEST)

**AR-Hand**: pair-mode (last AR-pair touchpoint of the entire
Phase-3-Marathon-Close-Window).

**Purpose**: Sign-off on the Marathon-Final-Bilanz Lieferbericht
(B4 output) and on the Phase-3-Post-Mortem-Anstoss (B5 output).
The AR-pair confirms that the Lieferbericht references the
verbatim AR-Vorzeichen "Halt vor Phase 4" anchor and that no
spawn from B5 carries Phase-4 task-content.

**Sign-off-marker**: `PB-TP3-FINAL-BILANZ-PASS` (green) or
`PB-TP3-FINAL-BILANZ-HOLD` (red, AR decides whether to publish
DRAFT-state Lieferbericht).

After TP-PB-3, the production-bringup-window closes. The next
AR-Hand-Touchpoint is the (future, undated) `PHASE-4-RE-ARMED`
signal per §9.4.

## §7 -- Aggregate-Verdict-Roll-up

Day-7-close emits the aggregate production-bringup-verdict by
rolling up B1..B5 outcomes per the following table:

| Verdict-Marker | Conditions |
|---|---|
| `PB-VERDICT-PHASE-3-CLOSED-CLEAN` -> green | B1=MARKER-FIRED, all B2 Day-N STABLE or DEGRADED-NON-BLOCKING, B3=J3-K3-CLOSED, B4=DELIVERED, B5=ANGESTOSSEN. All three TP-PB sign-offs PASS. |
| `PB-VERDICT-PHASE-3-CLOSED-WITH-CARRY` -> yellow | B1=MARKER-FIRED, but one or more of: B3=*-CARRIED, B4=DRAFT. TP-PB sign-offs may include MID-DEGRADED. |
| `PB-VERDICT-PHASE-3-NO-FIRE` -> yellow-red | B1=MARKER-NO-FIRE (REJECTED-pfad). Day-2..Day-7 continue under NO-FIRE-state; marker-state is irreversible without Phase-3-RE-OPEN-ADR. |
| `PB-VERDICT-PHASE-3-DEFERRED` -> yellow | B1=MARKER-DEFERRED. Day-2..Day-7 continue under DEFER-state; marker-state revisable only via re-aggregation post-defer-window. |
| `PB-VERDICT-PHASE-3-CLOSED-DEGRADED` -> yellow-red | B1=MARKER-FIRED, but B2 has one or more DEGRADED-BLOCKING Day-N. Hot-Fix-PRs landed during Day-2..Day-5. |
| `PB-VERDICT-PHASE-3-DEFECT-WINDOW` -> red | B1=HOLD past Day-2 06:00 CEST (R-PB-A fall-back-pin triggered). Marker-state is NO-FIRE-DEFAULT. |
| `PB-VERDICT-SPAWN-FILTER-BREACH` -> red | B5=HOLD systemic (R-PB-D fall-back-pin triggered). Phase-3-Post-Mortem-Anstoss deferred indefinitely. |

The verdict is committed to `state/production-bringup-window-
verdict.json` at Day-7 16:30 CEST by Operator-Hand, with AR-pair-
sanity at TP-PB-3.

## §8 -- Helper-Substrat

The Tag-76 Production-Bringup-Recipe has the following Helper-
Substrat (per the Tag-71/73/74/75 doc-to-substrate-closure
convention):

* **Verifier (this doc structurally clean)**:
  `tooling/ci/verify_production_bringup_recipe_doc.py`. Hermetic
  verifier asserting B1..B5 + R-PB-A..R-PB-D + TP-PB-1..TP-PB-3
  + Day-1..Day-7 anchors + AR-Vorzeichen-verbatim-presence + §7
  verdict table. Sources from
  `docs/operations/operator-hand-production-bringup-recipe.md`.

* **Tests (hermetic Tag-76 substrate-tests)**:
  `tests/observability/test_production_bringup_recipe_tag76.py`.
  Includes per-doc A-tests + per-verifier B-tests in the Tag-75
  pattern.

* **Aggregator (Day-7 verdict roll-up)**:
  `tooling/ci/aggregate_production_bringup_verdict.py` (planned
  Tag-77 substrate; this doc is the spec-source). The aggregator
  reads B1..B5 verdict-marker-state-files and emits
  `state/production-bringup-window-verdict.json` per §7 table.

* **Cross-link to Welle-7-Day P5 substrate (Tag-75 substrate)**:
  `state/phase-3-marathon-global-verdict.json` is the input to B1.
  `tooling/ci/aggregate_pyramide_run_order_verdict.py` is the
  Tag-75-side producer of the Day-1-input.

The Verifier + Tests substrate is the Tag-76 deliverable. The
Aggregator is Tag-77 follow-on substrate (not in this PR).

## §9 -- AR-Vorzeichen "Halt vor Phase 4" Governance-Pin

This section is the **explicit Phase-4 freeze-pin** per the
Tag-65 AR-Vorzeichen "Halt vor Phase 4" signal. **Phase-4 work
does not begin until the AR explicitly re-arms.** The pin holds
through Day-7-close (2026-07-10) and beyond, and is governance-
canonical for the Tag-76 Production-Bringup-Window in the same
way the Tag-66 Eve-Recipe §9 made it canonical for the Marathon-
Cutover-Window.

### §9.1 -- AR-Vorzeichen "Halt vor Phase 4" -- Verbatim-Anker

The Tag-65 AR-Vorzeichen reads, in operative form:

> "Phase-3-Marathon ends at Welle-7 cutover and Marathon-Final-
> Bilanz READY. The transition to Phase-4 (post-cutover
> stabilisation, production-readiness review, brand-publication
> pulse) requires an explicit AR-Hand re-arm signal. Until that
> signal is issued, no Phase-4 substrate enters the planning
> backlog and no Phase-4-prep work spawns from the Marathon-
> closing sessions."

This is pinned as `PHASE-4-HOLD-VOR-RE-ARM` and is the canonical
state at Day-1 06:00 CEST AND at Day-7 16:30 CEST close-of-window.

**The verbatim text above is reproduced from Tag-66 Eve-Recipe
§9.1 unchanged.** This Tag-76 doc neither weakens nor extends the
Vorzeichen; it merely operates under it throughout the Day-1..
Day-7 window.

### §9.2 -- What "Halt vor Phase 4" Means Operationally (Day-1..Day-7)

- **Spawn-Filter**: No persona-spawn between Day-1 06:00 CEST and
  the AR-re-arm signal may carry a Phase-4 brief. Any Mira-Hand
  auto-spawn that drifts into Phase-4 scope is a violation of
  this pin. The Day-7 B5 Post-Mortem-Anstoss is explicitly
  scoped to Phase-3-close substrate, not Phase-4-open.
- **Roadmap-Freeze**: `projects/roadmap.md` Phase-4 section
  stays at its T0+6 state through Day-7. No additions, no re-
  ordering, no status-bump on Phase-4 items.
- **ADR-Freeze**: No new ADRs that establish Phase-4 substrate.
  ADRs that **close** Phase-3 substrate (final-bilanz, lessons-
  learned, post-mortem) are permitted within Day-7-window. The
  Phase-3-COMPLETE-marker-fire on Day-1 is a Phase-3-close action,
  not a Phase-4-open action.
- **Brand-/Publication-Freeze**: No `wakir-labs/site` push for
  Phase-4 launch-prep content. The Phase-3-Marathon-completion
  announce is itself a Phase-3-close artefact and is permitted
  per Tomás scope. Production-Bringup-Window stability-probes
  do NOT trigger publication-pulse work.
- **Engineering-Freeze**: No 0.5.4 / 0.6.0 / 0.6.x persona-engine
  bumps. Hot-fix patches for production stability (B2 DEGRADED-
  BLOCKING outcomes) are permitted -- they close Phase-3, do
  not open Phase-4. Hot-fix scope is strictly read-only for
  Phase-4-substrate even in adjacent files.

### §9.3 -- Phase-3-Close Items Permitted Under the Pin (Tag-76 Window)

Five substantive items **are** permitted between Day-1 and Day-7-
close because they close Phase-3, not open Phase-4:

1. **Phase-3-COMPLETE-Marker-Fire (or NO-FIRE) at Day-1** -- B1-
   step per §1.
2. **Daily-Stability-Probe-Aggregation at Day-2..Day-5** -- B2-
   step per §2.
3. **OPEN-J3 / OPEN-K3 Closure-Records at Day-6** -- B3-step per
   §3 (per Tag-66 Eve-Recipe §9.3 Item 3).
4. **Marathon-Final-Bilanz Lieferbericht at Day-7** -- B4-step
   per §4 (per Tag-66 Eve-Recipe §9.3 Item 1).
5. **Phase-3-Post-Mortem-Anstoss at Day-7** -- B5-step per §4
   (per Tag-66 Eve-Recipe §9.3 Item 2; the Post-Mortem itself
   is audit-scope and Day-7 only triggers the spawn).

These five items are the **complete** list of permitted Phase-3-
close work in the Day-1..Day-7 window. Any other work request
that arrives in this window must be filtered against this list;
if not on this list, it is presumptively Phase-4-open and is
blocked by the `PHASE-4-HOLD-VOR-RE-ARM` pin.

### §9.4 -- AR-Re-Arm Trigger (Post-Day-7)

The AR re-arms Phase-4 work via an explicit AR-Hand signal in
the AR-pair log carrying the marker `PHASE-4-RE-ARMED`. Until
that marker appears, **no agent -- Kai, Reza, Tomás, Amara,
Selin, Noa, Mira -- initiates Phase-4 substrate**.

Mira-Hand-Spawn-Filter (Day-1..Day-7-and-beyond-until-re-arm):
any spawn-brief between Day-1 06:00 CEST and the re-arm signal
**must** include `PHASE-4-HOLD-VOR-RE-ARM` as a substrate-marker
and **must not** carry Phase-4 task-content. The B5 Day-7 spawn
is explicitly scoped to satisfy this filter.

The Tag-76 doc makes **no claim** about when the AR-Hand re-arm
signal will be issued. It may be issued at Day-7-close, or after
the Post-Mortem completes, or weeks later. The window itself is
sized for Phase-3-close hygiene, not for Phase-4-prep.

### §9.5 -- Phase-4-Prep Anchor (Inert, Tag-66-canonical)

For the AR's convenience, the following Phase-4 substrate
topics are **inert anchors** (named, not actioned). This list
is reproduced from Tag-66 Eve-Recipe §9.5 unchanged:

- Production-Readiness-Review (audit-scope, Amara/Henrik).
- Brand-Publication-Pulse (Tomás-scope, site/quartz).
- Persona-Engine 0.6.x roadmap (Selin-scope).
- Inter-Agent-Protocol Phase-3-Lessons feedback (Reza-scope).
- Container-Orchestrator Phase-4 Substrate-Bridge (Kai-scope).
- Federation-Substrate Operations Phase-4 (Kai-scope).

These topics are **named here so they are not forgotten** at
Day-7-close, but they remain **untouched** until AR-re-arm.

### §9.6 -- Sandbox-Boundary Reaffirmation

The Phase-4-freeze does not change the sandbox-boundary in the
Tag-66 Eve-Recipe §8. Operations that are Sandbox-OK before the
pin remain Sandbox-OK after. Operations that are Operator-Hand-
Sandbox-Gap before the pin remain Operator-Hand-Sandbox-Gap
after. The pin governs **substrate-scope**, not **sandbox-scope**.

Specifically for the Tag-76 window:

- B1 (marker-fire commit + push) is Operator-Hand under
  Continuous-Mode authorisation per memory
  `feedback_force_push_bundle_merge_ok`.
- B2 (daily-stability-probe aggregation commit + push) is
  Sandbox-OK; the underlying live-smoke-window job that produces
  the day's probe-output is operator-hand-live-VM per memory
  `feedback_sandbox_host_trennung`.
- B3 (J3/K3-closure-records commit + push) is Sandbox-OK.
- B4 (Marathon-Final-Bilanz Lieferbericht) is Sandbox-OK.
- B5 (Phase-3-Post-Mortem-Anstoss spawn) is Sandbox-OK at the
  spawn-brief level; the spawn itself is operator-hand-mira per
  the Sandbox-vs.-Host-trennung directive.

Memory `feedback_live_bringup_sandbox_gap` directives apply in
full and override any apparent shortcut in this Tag-76 doc.

---

-- Kai (Tag-76, 2026-05-19)
