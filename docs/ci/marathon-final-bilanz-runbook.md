<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Marathon-Final-Bilanz Runbook (Tag-50 / Tomas)

## Purpose

`phase-3-marathon-final-bilanz` is the cross-persona daily + post-
Welle-7 snapshot workflow. It complements Tag-43 Noa's
`phase-3-final-bilanz-generator` (which produces the full end-of-
Marathon-Bilanz post-COMPLETE-marker). This workflow renders a
one-page rollup across all five marathon-relevant personas:

| Persona | Inputs read                                                                  |
|---------|-------------------------------------------------------------------------------|
| Tomas   | `state/phase-3-complete-marker.json`, `out/cross-welle-hot-spot-verdict.json` |
| Noa     | `state/aggregator-failure-rate-history.json`, `state/cross-welle-drift-histograms.json` |
| Amara   | `state/phase-3-marathon-state.json` (welle-coverage signal)                   |
| Selin   | `state/phase-3-marathon-state.json` (Rust-vs-Python ratios)                   |
| Henrik  | `state/welle-{1..7}-sign-off.json`                                            |

## Triggers

- Schedule `0 8 * * *` daily 08:00 UTC (1h after cross-welle hot-spot aggregator).
- `workflow_run` post `phase-3c-welle-7-validation` completion.
- `workflow_dispatch` (operator-hand) with `mode=daily|post-welle-7` + `strict=true|false`.
- `push` / `pull_request` path-filtered on the substrate.

## Verdict ladder

- `MARATHON_READY` — all five persona slots READY, all seven Welle-sign-offs present, COMPLETE-marker COMPLETE.
- `MARATHON_IN_FLIGHT` — partial / pending slots, no broken. Normal mid-marathon.
- `MARATHON_BROKEN` — any malformed artefact, or `PENDING` in `post-welle-7` mode (loud-failure).

## Outputs

- `reports/marathon-final-bilanz.md` — Markdown bilanz; inlined into GITHUB_STEP_SUMMARY.
- `reports/marathon-final-bilanz.json` — machine-readable envelope (schema_version 1.0.0).
- Upload artifact `marathon-final-bilanz-<snapshot-ts>` (30 day retention).

## Operator-hand checklist

Post-Welle-7 sign-off:

1. Verify all seven `state/welle-N-sign-off.json` are present and `signed_off_by == henrik`.
2. Run `gh workflow run phase-3-marathon-final-bilanz --field mode=post-welle-7 --field strict=true`.
3. Inspect the Job-Summary for `MARATHON_READY`.
4. Hand the JSON artefact to Henrik for the Phase-3-Schluss-Audit-Bundle.

Daily during marathon window (KW-21..KW-27): no operator action needed; cron writes daily bilanz to artifacts. Inspect on demand via Actions → workflow → run → artifacts.

## Sandbox posture

stdlib-only Python, no subprocess, no network, no host filesystem writes outside the workspace. Hosted-runner-safe. Not a required PR status check.

## Companion workflows

- `cross-welle-hot-spot-aggregator.yml` (Tag-49 #317) — feeds `out/cross-welle-hot-spot-verdict.json`.
- `phase-3-final-bilanz-generator.yml` (Tag-43 #276, Noa) — produces full end-of-Marathon bilanz post-COMPLETE-marker.
- `phase-3c-welle-{1..7}-validation.yml` — feed the per-welle sign-off envelopes (via Henrik-hand).
