---
titel: "Phase-3-COMPLETE Marker Workflow Runbook"
owner: "Tomas Reinhart (Dev-Engineering)"
review: "Henrik Voss (Internal Audit) - AC-Mapping; Priya Nakamura (CTO) - CI surface"
erstellt: 2026-05-18
sprint_tag: 40
workflow: ".github/workflows/phase-3-complete-marker.yml"
adr_ref: "ADR-0066"
audit_spec_ref: "docs/audit/phase-3-cutover-schluss-audit-spec.md"
---

# Phase-3-COMPLETE Marker Workflow Runbook

Operator-Runbook for the post-Welle-7-Sign-Off marker workflow that
verifies the five conjunctive Acceptance-Criteria from Henrik's
Tag-39 audit-spec and - only if all five pass - emits the
`state/phase-3-complete-marker.json` file.

This runbook is the operational counterpart to the audit-spec; the
audit-spec defines *what* must be true, this runbook defines *how
to drive* the workflow that verifies it.

## 1. What the workflow does

The workflow is wired as **five independent verifier jobs plus one
emit job** that `needs:` all five. The emit job materialises the
marker only when every verifier reports `ac{N}_pass=true`.

| Job | Probes | Verdict-Source |
|---|---|---|
| `verify-ac-1-welle-sign-offs` | `state/welle-{1..7}-sign-off.json` | `sign_off_status in {green, yellow_henrik_hand_approval}` |
| `verify-ac-2-aggregate-consistency` | GH API: most recent `phase-3c-welle-{1..7}-validation.yml` run on `main` | every run `conclusion == "success"` |
| `verify-ac-3-predecessor-closure` | `state/phase-3{a,b,c}-closure.json` | `completed_count == total_count` for each phase (3a=15, 3b=9, 3c=7) |
| `verify-ac-4-henrik-ratification` | `state/henrik-phase-3-complete-ratification.json` | `verdict == "ratified"` AND R-A1..R-A6 all `verified` |
| `verify-ac-5-ar-hand-ratification` | `state/ar-hand-phase-3-complete-stamp.json` | `ar_hand_ratification: true` AND non-empty `ar_hand_quote` |
| `emit-phase-3-complete-marker` | aggregate of above + `inputs.dry_run` | emits `state/phase-3-complete-marker.json` and always uploads `artifacts/phase-3-marathon-bilanz.json` |

The bilanz artifact is uploaded on **every** run regardless of
outcome - it is the AR-visible Phase-3-Marathon scorecard.

## 2. Trigger surfaces

### 2.1 Manual (Mira-Hand) - `workflow_dispatch`

```bash
gh workflow run phase-3-complete-marker.yml --ref main \
  -f dry_run=false \
  -f override_schedule_window=true
```

Inputs:

* `dry_run=true` - runs every verifier and emits the bilanz
  artifact, but does **not** write `state/phase-3-complete-marker.json`.
  Use this for AR-Hand dress-rehearsal before the real cutover-day
  trigger.
* `override_schedule_window=true` - allows manual emission outside
  the Monday 12:00 UTC window. Cosmetic; the schedule cron is
  decorative and the verifiers are pure-state, but the field is
  retained so operator intent is recorded in the run log.

### 2.2 Scheduled - Monday 12:00 UTC

```yaml
schedule:
  - cron: "0 12 * * 1"
```

KW-27 Welle-6+7 cutover is Monday 2026-06-29 per ADR-0066. The
scheduled probe is **idempotent**: if AC-1..AC-5 are not yet all
satisfied (typical state until Welle-7 sign-off lands), the
verifiers report `false`, the emit step is skipped, the marker
file is **not** written, the aggregator step fails the job
(red workflow run) and the bilanz artifact records
`verdict: phase-3-incomplete`.

The "scheduled red until complete" posture is deliberate: it
surfaces "Phase-3 is not yet complete" as a tracked CI signal,
not a silent green.

## 3. AR-Hand ratification workflow

AR-Hand ratification is AC-5 - **without it, the marker cannot
be emitted regardless of every other criterion**.

### 3.1 Pre-conditions

1. AC-1..AC-4 verifiers report `true` on a dry-run pass.
2. Henrik (Internal Audit) has delivered the
   `state/henrik-phase-3-complete-ratification.json` file
   (AC-4) with `verdict: "ratified"` and R-A1..R-A6 all marked
   `verified`.

### 3.2 AR-Hand commit sequence

The AR-Hand stamp is a JSON file checked into `main` by the
Aufsichtsrat (via Mira-Hand under explicit AR instruction):

```json
{
  "ar_hand_ratification": true,
  "ar_hand_quote": "Phase-3-Cutover-Marathon ratifiziert. Marker setzen.",
  "timestamp_utc": "2026-06-29T13:00:00Z",
  "ar_member": "Fred",
  "henrik_ratification_ref": "state/henrik-phase-3-complete-ratification.json",
  "commit_sha_ratified": "<the HEAD commit at AR-Hand decision time>"
}
```

Path: `state/ar-hand-phase-3-complete-stamp.json`.

The `ar_hand_quote` field is the IIA-1130 anchor (Henrik-Spec
§3 Pt-5): Internal Audit cannot self-ratify, AR must speak the
words.

### 3.3 Marker emission

Once the AR-Hand stamp is on `main`:

```bash
gh workflow run phase-3-complete-marker.yml --ref main \
  -f dry_run=false
```

Run completes green. The marker is committed by the **subsequent
Mira-Hand follow-up commit** that copies the workflow-emitted
file into a real commit on `main`:

```bash
# Inside a fresh worktree on main, after the workflow has run green:
gh run download <run-id> -n phase-3-marathon-bilanz -D artifacts/
# Re-run locally to materialise state/phase-3-complete-marker.json
# in the working tree (the workflow itself runs on a runner; the
# file is regenerable from the workflow logs by replaying the
# emit step's Python block, or by re-running the workflow with
# dry_run=false and downloading the result via a follow-up artifact
# upload step in a hotfix PR).
```

(Mira-Hand follow-up commit because GitHub Actions cannot push to
`main` under this repo's branch-protection without dedicated
credentials, and we deliberately do not grant those - the marker
is *evidenced* by the green workflow run + bilanz artifact, but
*authoritatively* recorded by the human-driven commit.)

## 4. Rollback at false-positive marker

If a marker has been emitted in error - e.g. one of the
`state/welle-N-sign-off.json` files was committed with `green`
status before the audit was actually green - the rollback path is:

### 4.1 Detect

* Henrik or AR notices: a Welle sign-off was prematurely flipped
  to green, or an R-A risk-vector mitigation is in fact unverified,
  or the AR-Hand stamp file was committed without authorised AR-Hand
  instruction.
* `state/phase-3-complete-marker.json` exists on `main` but does not
  reflect substance.

### 4.2 Rollback steps

1. **Open a revert PR** that:
   - removes `state/phase-3-complete-marker.json`,
   - corrects the offending sign-off / ratification / stamp file
     (set status back to `open` or `rollback` per Henrik-Spec §1
     terminology, or delete the file entirely if it was committed
     in error),
   - includes a short note in `activity-log.md` referencing this
     runbook §4 and the substance error.

2. **Re-run the workflow** with `dry_run=true` to confirm
   AC-1..AC-5 now report the substance state (typically one or
   more `false`).

3. **Trigger ntfy.sh + Resend mail** to AR (Henrik-Spec §4
   Eskalations-Aktionen Pt-2/3) - false-positive marker is a
   critical schluss-finding by definition.

4. **Audit-trail entry** in `activity-log.md` (Henrik-Spec §4 Pt-4)
   with revert-PR ref.

5. **Do not re-emit** the marker until the substance error is
   substantively resolved AND AR-Hand has issued a fresh
   ratification stamp explicitly acknowledging the rollback.

### 4.3 Why rollback is rare

The five-AC conjunction plus the AR-Hand `ar_hand_quote`
requirement make accidental false-positive emission improbable.
The realistic false-positive vector is **operator error in
committing the AC-1 sign-off files prematurely** - which is why
the Welle sign-off commits should themselves go through a Henrik
pre-audit cycle before landing on `main`.

## 5. Verification - workflow shape

Local sanity check against the hermetic test-suite:

```bash
pytest tests/ci/test_phase_3_complete_marker_workflow.py -q
```

The test-suite walks the 32-row truth-table for AC-1..AC-5 plus
structural assertions on trigger surface, job topology, and
permission hygiene.

## 6. Cross-references

* Henrik audit-spec: `docs/audit/phase-3-cutover-schluss-audit-spec.md`
* ADR-0066 Phase-3c Beschleunigung Option A+
* Welle sign-off template (to be added by Henrik): `audit/phase-3c-welle-audit-template.md`
* `feedback_branch_protection_check_names.md` - this workflow is
  intentionally NOT a required status check
* `feedback_continuous_mode_keine_push_frage.md` - scheduled cron
  posture rather than push-based posture per Continuous-Mode
  conventions
