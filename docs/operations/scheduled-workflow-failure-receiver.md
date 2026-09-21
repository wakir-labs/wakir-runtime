<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors -->

# Runbook — receiver for workflows that fail off the pull-request surface

**Owner:** Kai Hoffmann (DevOps / Container-Orchestration)
**Substrate:** `.github/actions/report-scheduled-failure` (composite action)
**Introduced:** 2026-09-21
**Anchor:** Zone-C cross-review Tomás Reinhart 2026-09-21, auflage C1
(`agents-workspaces/dev-engineering/outbox/2026-09-21-tomas-zone-c-review-trigger-schnitt.md`)

---

## 1. The finding this substrate answers

Measured on `main` @ `67a62fc`, 2026-09-21, and re-measured
independently three times (Tomás, Mira, Kai):

| Measurement | Result |
|---|---|
| Workflow files in `.github/workflows/` | 40 |
| `gh issue create` steps | 0 |
| `actions/github-script` steps | 0 |
| `if: failure()` handlers | 0 |
| `ntfy` calls | 0 — the two hits in `sbom-verification-daily.yml` are comment lines describing an intention |
| Workflows with a `schedule:` trigger | 6 |
| Scheduled runs those six have had | 73–74 each, most recent on the day of measurement |
| Conclusion of the last 30 scheduled runs of each | 30/30 `success`, all six |

The crons fire. That was the open question and it resolved in the
substrate's favour. The problem is the other half: **there was no
executable path on which a failure reached a human.** And because
nothing has ever failed on that surface, the repository held no
evidence either way — a green history is not evidence that red would
be noticed.

That is why "move a check to `schedule` so it fails loudly" was, until
this substrate existed, a contradiction: moving a check to `schedule`
did not make it loud, it made it unobserved.

## 2. What the receiver does

One composite action, two modes, wired as one extra job per consumer
workflow.

* **`mode: fail`** — ensures exactly **one open issue** per workflow,
  under a **fixed title** (`[scheduled-failure] <workflow name>`).
  The first failure creates it; every later failure appends a comment
  to the same issue. The fixed title *is* the dedupe key: a daily
  probe that failed for 74 days must produce one issue with 74
  comments, never 74 issues.
* **`mode: resolve`** — on the next successful non-PR run, the issue
  is closed with a recovery comment. So an **open receiver issue
  always means "this lane is red right now"**, which is the property
  that makes the issue list readable at a glance.

Neither mode runs on `pull_request`: a PR failure already has a
receiver, namely the PR.

## 3. Consumers (receiver catalog)

Per the Receiver-Catalog duty, every consumer is listed here. A new
`schedule`-triggered workflow without an entry in this table is an
incomplete PR.

| Consumer workflow | Watched job | Cron |
|---|---|---|
| `.github/workflows/cosign-keyless-oidc-drift-probe.yml` | `drift-probe` | `30 6 * * *` |
| `.github/workflows/15-binary-sbom-daily.yml` | `generate-sbom` | daily |
| `.github/workflows/sbom-verification-daily.yml` | `verify-sbom` | daily |
| `.github/workflows/build-reproducibility-daily.yml` | `audit-reproducibility` | daily |
| `.github/workflows/image-build-reproducibility-daily.yml` | `audit-image-build-reproducibility` | daily |
| `.github/workflows/cosign-strict-mode-readiness-check.yml` | `readiness-check` | `30 7 * * *` |

## 4. Wiring a new consumer

Append to the workflow, replacing `<job>` with the id of the job to
watch:

```yaml
  scheduled-failure-receiver:
    name: Scheduled-failure receiver
    needs: [<job>]
    if: ${{ always() && github.event_name != 'pull_request' }}
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      contents: read
      issues: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 1
      - if: ${{ needs.<job>.result == 'failure' }}
        uses: ./.github/actions/report-scheduled-failure
        with:
          mode: fail
          github-token: ${{ secrets.GITHUB_TOKEN }}
      - if: ${{ needs.<job>.result == 'success' }}
        uses: ./.github/actions/report-scheduled-failure
        with:
          mode: resolve
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

Rules that are not style preferences:

1. **`issues: write` goes on the receiver job, never at workflow
   level.** The job under test keeps `contents: read`.
2. **`always()` at job level, `needs.<job>.result` at step level.**
   Without `always()` the receiver is skipped exactly when it is
   needed. `cancelled` and `skipped` deliberately trigger neither
   mode.
3. **Never template a run id, date or SHA into the title.** The title
   is the dedupe key; a variable title turns the receiver into the
   issue spam it exists to prevent.
4. **Add the row to the table in §3 in the same PR.**

## 5. How to re-prove it (do not trust the code, run it)

The receiver was proven by a deliberately failing run, not by review.
The method is reproducible and should be repeated whenever the action
changes:

1. Add a temporary workflow on a feature branch with `on: push:
   branches: [<branch>]`, a job that runs `exit 1`, and the receiver
   job above.
2. Push. Expect: the run fails, and **one** issue appears.
3. Push again. Expect: the run fails again, the issue count is
   **unchanged**, and a comment is appended.
4. Change the control job to succeed and push. Expect: the issue is
   closed with a recovery comment.
5. Delete the temporary workflow, and link the run URLs in the PR
   body.

### Evidence for the introducing PR (#547), 2026-09-21

Run on a temporary workflow `zz-receiver-negative-control.yml`, deleted
in the same PR after the runs:

| Leg | Run | Control job | Receiver effect |
|---|---|---|---|
| 1 | [35636970612](https://github.com/wakir-labs/wakir-runtime/actions/runs/35636970612) | failure (deliberate) | issue **#548 created**, label `scheduled-failure` auto-created |
| 2 | [35637433487](https://github.com/wakir-labs/wakir-runtime/actions/runs/35637433487) | failure (deliberate) | **no second issue** — comment appended to #548 (open issues: 1) |
| 3 | [35637525484](https://github.com/wakir-labs/wakir-runtime/actions/runs/35637525484) | success | #548 **closed** with a recovery comment |

Issue [#548](https://github.com/wakir-labs/wakir-runtime/issues/548) is
the artefact of the proof and is deliberately left in the repository's
issue history rather than deleted.

## 6. Limits, stated rather than discovered later

* **The receiver is not a pager.** It produces a GitHub issue. Nobody
  is woken up. It converts "invisible" into "visible to whoever reads
  the issue list", which is the step that was missing — not the last
  step.
* **A race exists in theory:** two concurrent runs of the *same*
  workflow failing simultaneously could both see no open issue. All
  six consumers declare a `concurrency:` group, so it is unreachable
  for them today. A future consumer without one must add one.
* **The receiver depends on the failing workflow's runner reaching the
  GitHub API.** A GitHub-wide outage takes the receiver with it. It
  covers job failure, not platform absence — the case "the cron did
  not fire at all" is *not* covered by this substrate and needs a
  different instrument (an external dead-man's-switch).
* **`gh` is used deliberately** instead of a third-party action: it is
  preinstalled on the runners, so the receiver adds no dependency that
  could itself be the outage.

— Kai
