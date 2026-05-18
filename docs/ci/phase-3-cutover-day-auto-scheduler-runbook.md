<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (c) 2026 Callandor GmbH and contributors -->

# Phase-3 Cutover-Day Auto-Scheduler Runbook

**Workflow:** `.github/workflows/phase-3-cutover-day-auto-scheduler.yml`
**Decision-tree:** `tooling/ci/decide_cutover_day_dispatch.py`
**Tests:** `tests/ci/test_phase_3_cutover_day_auto_scheduler.py`
**Owner:** Tomas (dev-engineering)
**ADR:** ADR-0066 Phase-3c Cutover Plan
**Tag:** Tag-44

## Purpose

Auto-orchestration of the four Cutover-Day Mondays in KW-24..27 of
the Phase-3c persona-engine cutover marathon. The scheduler wakes
every Monday at 07:00 UTC, decides what to dispatch based on the
ISO calendar week, evaluates three pre-trigger gates, and either
fans out the matching Welle-N validation workflows or emits a
dry-run plan envelope.

## When this runbook applies

- Monday 07:00 UTC scheduled run produced anything other than a
  green `TRIGGER` mode (`DRY_RUN`, `BLOCK`, or the workflow itself
  failed at the GitHub Actions level).
- A dress-rehearsal `workflow_dispatch` with `force_iso_week` did
  not produce the expected dispatch plan.
- A `push` to `main` that touches the scheduler workflow or its
  decision-tree module failed the structural-shape unit tests.

## Decision-tree summary

| ISO week | Action            | Welle workflows dispatched         | Marker |
|----------|-------------------|------------------------------------|--------|
| KW-24    | `WELLE_1_PLUS_2`  | welle-1-validation, welle-2-validation | no |
| KW-25    | `WELLE_3`         | welle-3-validation (Henrik caution-path) | no |
| KW-26    | `WELLE_4_PLUS_5`  | welle-4-validation, welle-5-validation | no |
| KW-27    | `WELLE_6_PLUS_7`  | welle-6-validation, welle-7-validation | yes |
| other    | `PROBE_ONLY`      | phase-3c-pre-cutover-sanity         | no |

KW-27 is the only week that also triggers the
`phase-3-complete-marker.yml` workflow, and only when the gate
verdict is `PROCEED` (real cutover, not dry-run).

## Pre-trigger gates

Three inputs, evaluated by
`tooling/ci/decide_cutover_day_dispatch.py::evaluate_gates`:

1. **Reza Tag-44 daily-driver trend** -
   `state/reza-tag-44-trend.json` -> `{"trend": "green|yellow|red"}`.
2. **Tomas Tag-41 pre-cutover-sanity verdict** -
   downloaded from the latest successful run of
   `phase-3c-pre-cutover-sanity.yml` as
   `artifacts/pre-cutover-sanity-verdict.json` ->
   `{"verdict": "READY|CAUTION|BLOCK"}`.
3. **AR-Hand ratification flag** -
   `state/ar-hand-cutover-day-flag.json` ->
   `{"ar_hand_ratified": true}`.

Verdict cascade:

| sanity   | reza    | ar-hand    | verdict        |
|----------|---------|------------|----------------|
| BLOCK    | any     | any        | BLOCK          |
| any      | red     | any        | BLOCK          |
| missing  | any     | any        | BLOCK          |
| any      | missing | any        | BLOCK          |
| CAUTION  | green   | true       | DRY_RUN_ONLY   |
| READY    | yellow  | true       | DRY_RUN_ONLY   |
| READY    | green   | false      | DRY_RUN_ONLY   |
| READY    | green   | true       | PROCEED        |

`BLOCK` is hard - no dispatch, workflow exits non-zero, the
operator-hand decides whether to override.

`DRY_RUN_ONLY` is soft - the plan envelope is rendered and the
notify-cascade fires, but no `gh workflow run` is invoked and no
tracker updates are emitted.

`PROCEED` is the only mode that fans out to the Welle workflows
and (KW-27 only) the Phase-3-COMPLETE marker workflow.

## Trigger surface

- **Schedule:** `cron: "0 7 * * 1"` - Monday 07:00 UTC. One hour
  after the Tomas Tag-41 pre-cutover-sanity 06:00 UTC run, so its
  verdict artifact is fresh.
- **workflow_dispatch:** manual run with two optional inputs:
  - `force_iso_week` - override the calculated ISO week for
    dress-rehearsal / replay.
  - `dry_run_override` - force `DRY_RUN` even if all gates green.
- **push** (path-filtered): on changes to the scheduler workflow
  itself or its decision-tree module, so the structural-shape unit
  tests run on PRs.

## Operator-hand playbook

When the Monday 07:00 UTC scheduled run lands as `BLOCK` or
`DRY_RUN`:

### Step 1 - read the verdict envelope

Download the `cutover-day-dispatch-plan` build artifact and inspect
`gate_verdict.kind` plus `gate_verdict.missing_inputs`.

### Step 2 - identify which gate failed

- `sanity_verdict: "BLOCK"` -> the Tag-41 pre-cutover-sanity
  workflow detected a substrate regression. Open its run from
  06:00 UTC, download `pre-cutover-sanity-verdict.json`, follow the
  remediation links in
  `docs/ci/phase-3c-pre-cutover-sanity-runbook` (if present) or in
  the sanity-workflow file header.
- `reza_trend: "red"` -> Reza Tag-44 daily-driver substrate
  reported a trend-regression. Open
  `state/reza-tag-44-trend.json` and inspect the `notes` field;
  escalate to Reza if the cause is not obvious.
- `sanity_verdict: "missing"` -> the sanity-workflow has never
  produced a successful run, or its artifact was not downloadable.
  Re-run the workflow manually
  (`gh workflow run phase-3c-pre-cutover-sanity.yml --ref main`)
  and re-trigger this scheduler.
- `reza_trend: "missing"` -> the daily-driver trend file is not
  on the main branch. File a follow-up issue with Reza; the
  scheduler will not dispatch until the file exists.
- `ar_hand_ratified: false` (with everything else green) ->
  `DRY_RUN_ONLY`. The scheduler is operating correctly; the
  AR-Hand has simply not ratified the cutover-day yet. Create
  `state/ar-hand-cutover-day-flag.json` with
  `{"ar_hand_ratified": true, "ratified_at": "...", "quote": "..."}`
  on the day-of, and the next scheduler-run (or a
  `workflow_dispatch`) will fan out.

### Step 3 - manual fan-out if needed

If the gates are degraded but the operator-hand wants to fan out
manually:

```
gh workflow run phase-3c-welle-1-validation.yml --ref main
gh workflow run phase-3c-welle-2-validation.yml --ref main
# ... etc for the wellen of the current cutover-week
```

For KW-27, additionally:

```
gh workflow run phase-3-complete-marker.yml --ref main
```

### Step 4 - tracker state-update

The auto-scheduler does NOT directly write to
`state/phase-3-marathon-state.json`. It logs the intended
transitions to the step-summary and the notify-stream artifact.
The operator-hand (or Selin's tracker substrate) applies the
state-updates explicitly:

```
python3 scripts/phase-3c/marathon-aggregat-tracker.py \\
    --update-welle 1 --state cutover-running \\
    --note "auto-scheduler KW-24"
```

This separation is intentional - the marathon-state file is a
source-of-truth artifact that the operator-hand commits to the
repo; we keep that audit trail in operator hands rather than
behind a CI ratchet.

## Sandbox boundary

- The decision-tree (`tooling/ci/decide_cutover_day_dispatch.py`)
  is stdlib-only and has no side effects beyond writing the
  envelope file.
- The workflow YAML uses `gh workflow run` only in `TRIGGER` and
  `PROBE` modes; `DRY_RUN` and `BLOCK` modes never cross into
  GitHub-API territory.
- The notify-cascade is an append-only log to a build artifact;
  there is no real Slack webhook (operator-hand publishes the
  notify-stream contents manually if needed).
- No podman, no NATS, no live-VM, no Anthropic API.

## Not a required status check

Per `feedback_branch_protection_check_names.md` this workflow is
NOT listed as a required status check on PRs - it gates a
calendar-window (the four cutover Mondays), not individual PRs.
The structural-shape unit tests in
`tests/ci/test_phase_3_cutover_day_auto_scheduler.py` are the
PR-gating substrate; they live behind the existing `tests` CI
job's standard pytest collection.

## Cross-substrate links

- Tomas Tag-41 pre-cutover-sanity (PR #266):
  `.github/workflows/phase-3c-pre-cutover-sanity.yml`
- Selin Tag-40 marathon-tracker (PR #261):
  `scripts/phase-3c/marathon-aggregat-tracker.py`
- Tomas Tag-40 complete-marker (PR #258):
  `.github/workflows/phase-3-complete-marker.yml`
- Tomas Tag-43 marathon-coordination-CLI (PR #276):
  `scripts/phase-3c/marathon-coordination-cli.py`
- ADR-0065 + ADR-0066 in `decisions/`.

## Tag-44 close-out checklist

- [x] Workflow YAML pushed and parseable.
- [x] Decision-tree module stdlib-only and CLI-runnable.
- [x] Hermetic tests >=14 (structural + decision + gate-permutation
  + parser + CLI).
- [x] Runbook present at `docs/ci/phase-3-cutover-day-auto-scheduler-runbook.md`.
- [ ] PR opened against `main`.
- [ ] Six-plus required status checks green.
- [ ] PR merged.

- Tomas
