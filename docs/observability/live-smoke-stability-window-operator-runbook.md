<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors -->

# Live-Smoke Stability-Window Probe -- Operator Runbook (Tag-71)

**Owner:** Noa Bergstroem (SRE).
**Status:** Active 2026-05-19 -- 2026-06-07 (pre-cutover window).
**Anchors:** ADR-0065 Phase-3c cutover-plan, ADR-0066 Doppel-Welle
ordering, Tag-67 Watch-Day Pre-Cutover Live-Smoke (PR #425),
Tag-69 Live-Smoke Stability-Window-Probe workflow (PR #437),
Tag-50 Welle-N-Specific Alert-Rules
(`dashboards/phase-3-marathon-alerts.yaml`).

## 1. Purpose

This runbook is the **Day-1 operator-side companion** to the
Tag-69 `live-smoke-stability-window-probe.yml` workflow. It tells
the on-shift operator -- on the morning of a Pre-Cutover Watch-Day
or a Phase-3c Cutover-Day -- exactly how to:

1. **Trigger** the probe (`workflow_dispatch`).
2. **Read** its trinary verdict
   (`STABILITY-WINDOW-CONFIRMED` / `-NOT-YET` / `-DEFECT`).
3. **Decide** whether the Tag-67 Watch-Day Pre-Cutover Live-Smoke
   is a defensible Required-Status-Check anchor for the next
   Pool-8 promotion attempt.
4. **Hand off** verdicts and rationale to the AR-Hand audit-log.

The probe is **informational, not gating**. The Required-Status-
Check pin remains operator-hand (Tag-64 Sandbox-Boundary). This
runbook codifies the operator workflow so the decision is
reproducible across shifts and across operators.

Tag-71 extends the Tag-69 probe surface by wiring a Welle-3-
specific Pre-Auditor-Alert into the marathon alert tree (see
Section 6). That alert closes the routing gap identified during
Henrik's Tag-44 Pre-Mortem Class-B3 review: the system must
emit an explicit acknowledgement when the AR-Hand designates an
external Pre-Auditor for Welle-3 (KW-25 SOLO).

## 2. Day-1 Operator Action -- Pre-Shift Checklist

Before the operator triggers the Tag-69 probe, the following
five gates must be green. The probe runs even if a gate is red,
but the verdict-rationale becomes meaningless if upstream
inputs are not in a known-good state.

| Gate | Source | Green criterion |
|---|---|---|
| G1 last-N Watch-Day | Reza Tag-44 Daily-Trend-Analyzer | last 3 daily envelopes aggregate=READY |
| G2 Pre-Cutover-Sanity | Amara Tag-65 E2E-Smoke Stability-Window | verdict=STABILITY-WINDOW-CONFIRMED |
| G3 Pyramide Cross-Run | tooling/ci/verify_pyramide_cross_run_stability.py | exit-code 0 |
| G4 REUSE-Wrap | Tomas Tag-63 stability-window probe | verdict=STABILITY-WINDOW-CONFIRMED |
| G5 OTS-Anchor | meta/timestamps current-week | last 3 OTS confirmations green |

If any gate is yellow or red, the operator records the gate
status in the Day-1 shift-log entry but does **not** abort the
probe. The probe's purpose is to surface the *aggregate*
posture; gating logic belongs to the Selin Tag-64 Auto-Scheduler
verdict tile, not to this runbook.

## 3. Trigger Procedure

The probe is `workflow_dispatch`-only.

1. Open `https://github.com/wakir-labs/wakir-runtime/actions/`
   and locate `Live-Smoke Stability-Window Probe`
   (workflow file:
   `.github/workflows/live-smoke-stability-window-probe.yml`).
2. Click `Run workflow` on the `main` branch.
3. Do **not** override any input. The probe runs three back-to-
   back invocations of the Tag-67 Live-Smoke aggregator helper
   on the runner's workspace; there are no operator-tunable
   parameters.
4. Wait for the run to complete (typical wall-clock: 2-4
   minutes; hermetic, stdlib-only).
5. Capture the run-URL into the shift-log.

If the workflow does not appear in the Actions list, the
operator escalates to the SRE on-call before any further
Cutover-Day decision is made. A missing workflow during a
Watch-Day is itself a Class-A failure-mode (substrate drift).

## 4. Reading the Verdict

The probe emits exactly one of three verdicts (Tag-59 OTS
N-Run-Pattern, shared shape with Tag-63 / Tag-65 / Tag-69):

### 4.1 STABILITY-WINDOW-CONFIRMED

All three back-to-back runs returned `LIVE-SMOKE-INTACT`.

**Operator action:**
* Record `verdict=STABILITY-WINDOW-CONFIRMED` in shift-log.
* Proceed with the Pool-8 erweiterter Slot promotion **only**
  if the AR-Hand has independently confirmed the promotion
  authorisation for the current Watch-Day. This runbook does
  not grant promotion authority; it only verifies the
  substrate-stability precondition.

### 4.2 STABILITY-WINDOW-NOT-YET

At least one of the three runs returned `LIVE-SMOKE-DRIFT` or
`LIVE-SMOKE-DEFECT`, but the aggregator helper itself did not
crash.

**Operator action:**
* Record `verdict=STABILITY-WINDOW-NOT-YET` in shift-log.
* Capture the per-run JSON envelopes from the workflow
  artefacts (`stability-window-probe-runs/`).
* Inspect the first non-green run to identify the failing
  Stage 1..6 input. The Tag-67 Live-Smoke aggregator labels
  each stage with a `stage_label` and a `posture` field.
* Open a follow-up activity-log entry citing the failing
  stage and the run-URL. **Do not** retry the probe; the
  next legitimate opportunity is the next Watch-Day cycle.

### 4.3 STABILITY-WINDOW-DEFECT

At least one aggregator invocation exited non-zero. The probe
itself is broken.

**Operator action:**
* Record `verdict=STABILITY-WINDOW-DEFECT` in shift-log.
* Page the SRE on-call (`pagerduty:sre-oncall`).
* Open a defect ticket against the probe workflow; attach
  the failing run-URL and the aggregator stderr.
* **Do not** infer anything about substrate health from a
  DEFECT verdict; the substrate may be fine, the probe may
  be broken, or both -- a DEFECT verdict simply means the
  signal is unreadable.

## 5. Verdict Hand-Off to AR-Hand

Independent of which verdict was emitted, the operator records
the following five fields into the shift-log entry:

1. `verdict` (one of CONFIRMED / NOT-YET / DEFECT).
2. `workflow_run_url`.
3. `pre_shift_gates` (the 5-tuple from Section 2).
4. `operator_initials` and `shift_id` (per scheduling rota).
5. `notes_freetext` (any context the next shift should see).

The shift-log entry is appended to
`reports/observability/shift-log-yyyy-mm-dd.md` and committed
to `main` by the operator-tooling pipeline. The Tag-46 Mira-
Notify chain mirrors the verdict line to the AR-Hand ntfy
topic for cross-channel audit-trail completeness.

## 6. Welle-3 Pre-Auditor Routing Element (Tag-71 Extension)

ADR-0066 §Welle-3 designates KW-25 (Welle-3 bridge-audit-writer)
as the SOLO Phase-3c cutover. Henrik Tag-44 Pre-Mortem Class-B3
identified an IIA-Standard-1130 independence-impairment risk
when Welle-3 Schluss-Audit-Signoff arrives from `auditor=henrik`
(default-path) rather than from an AR-designated external
Pre-Auditor.

The Tag-50 alert group `welle-3-alerts` already carries the
Self-Reference-Trap-Fire and the Hot-Spot-Welle-3-4 coupling
signals. Tag-71 adds **one informational alert** to the
`phase-3-marathon-failure-mode-b3-iia-1130-default` group: a
positive-acknowledgement signal that fires when the external
Pre-Auditor designation has been recorded.

| Field | Value |
|---|---|
| Alert name | `WakirPhase3Welle3PreAuditorDesignated` |
| Severity | `info` |
| Routing class | `welle-3-pre-auditor-info` |
| Notify path | `ntfy:ar-hand-info + activity-log:append` |
| Recording rule | `wakir_welle_schluss_audit_signoff{welle="welle-3",auditor="external-pre-auditor"} == 1` |

The alert closes Henrik's Class-B3 routing gap by giving the
operator a single, named signal: when the AR-Hand designates
the external Pre-Auditor (per `welle-3-iia-1130-pre-decision-
spec-2026-05-18.md`), the routing system emits an explicit
INFO alert. This is the *positive-confirmation counterpart* to
the existing `WakirPhase3FailureModeB3Iia1130DefaultPath` alert
(which fires only when the default-path is taken).

The two alerts are mutually exclusive when the recording-rule
inputs are well-formed:

* `external-pre-auditor=1` AND `henrik=0` --
  emit `WakirPhase3Welle3PreAuditorDesignated` (Tag-71, INFO).
* `external-pre-auditor=0` AND `henrik=1` --
  emit `WakirPhase3FailureModeB3Iia1130DefaultPath` (Tag-45,
  WARNING).
* both = 0 -- pre-decision state, nothing fires.
* both = 1 -- contradiction; the recording-rule pipeline must
  reject the double-signoff before alert evaluation.

The Day-1 operator does not act on the
`WakirPhase3Welle3PreAuditorDesignated` alert; it is a
cross-channel audit-trail marker. The AR-Hand sees the ntfy
ping and the activity-log entry, which is the canonical
record of the Welle-3 Pre-Auditor designation having been
made.

## 7. Failure-Mode Escalation Table

| Symptom | First action | Escalation |
|---|---|---|
| Workflow missing in Actions | Page SRE on-call | AR-Hand if not resolved in 30 min |
| `STABILITY-WINDOW-DEFECT` | Page SRE on-call | AR-Hand on second DEFECT in 24h |
| `STABILITY-WINDOW-NOT-YET` 3x in a row | SRE on-call review | AR-Hand for Pool-8 promotion freeze |
| Pre-shift gate G1..G5 red | Open ticket | Do not abort probe; verdict recorded as context |
| Welle-3 Pre-Auditor designation missing on KW-25 morning | AR-Hand notification | Mira-Hand-Hold-Marker; T0 held |

## 8. References

* Tag-67 Watch-Day Pre-Cutover Live-Smoke -- PR #425.
* Tag-69 Live-Smoke Stability-Window-Probe -- PR #437,
  `.github/workflows/live-smoke-stability-window-probe.yml`.
* Tag-50 Welle-N-Specific Alert-Rules --
  `dashboards/phase-3-marathon-alerts.yaml`.
* Henrik Tag-44 Pre-Mortem (Class-B3) --
  `reports/audit/phase-3-marathon-pre-mortem-2026-05-18.md`.
* ADR-0065 Phase-3c Cutover-Plan.
* ADR-0066 Doppel-Welle Ordering.

-- Noa
