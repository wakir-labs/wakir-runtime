<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Phase-2 Acceptance Gate — Operations Playbook

**Status:** active (Tag-22 Mini-Welle, 2026-05-17).
**Owner:** Tomás (substrate), Henrik (audit), Amara (QA).
**Workflow:** `.github/workflows/phase-2-acceptance-gate.yml`.
**Aggregator:** `scripts/doppelbetrieb-score-aggregator.py`.

## What this gate does

Drives the doppelbetrieb-score-aggregator end-to-end against `main`
and surfaces the eight-axis rollup as a CI artifact plus a step-
summary table. The aggregator scores the five Phase-2 Doppelbetrieb
gate verdicts and three Phase-3a-Foundation acceptance axes, then
sums per-axis weights into a single total. A threshold check turns
the total into a green/red verdict.

The eight axes (stable order):

| # | Axis | Source |
|---|---|---|
| 1 | `gate-2-1-bridge-forward-symmetry`     | `tests/infra/test_phase_2_acceptance_gates.py` |
| 2 | `gate-2-2-konsistenz-score-threshold`  | same |
| 3 | `gate-2-3-v907-hash-stability-marker`  | same |
| 4 | `gate-2-4-recovery-r1-r4-mock-drill`   | same |
| 5 | `gate-2-5-subscribe-loop-lag-mock`     | same |
| 6 | `bridge-audit-e2e-roundtrip-pass`      | `tests/integration/test_bridge_audit_roundtrip_e2e.py` |
| 7 | `cross-lang-pin-coverage`              | wirelang pin-pack contracts (16 pins total) |
| 8 | `wat-anchor-latency-producer-emitting` | `wat/anchor/latency_emitter.py` |

Each axis carries weight `1`; the max total is `8`.

## Distinction from `phase-2-validation-gate`

| Gate | Lane | Trigger | Purpose |
|---|---|---|---|
| `phase-2-validation-gate` (PR #110) | per-PR / required check | pull_request + push to main | Hermetic per-gate suite, fail-fast, branch-protection-enforced |
| `phase-2-acceptance-gate` (this doc) | ops-readiness / informational | daily schedule + push to main + workflow_dispatch | Eight-axis rollup, threshold-checked, NOT a required check |

The acceptance gate is intentionally *not* wired into branch-
protection at this time. Operator-Hand-Decision per Mira (per
`feedback_branch_protection_check_names.md`); the gate first proves
stable on `main` before any required-check promotion.

## Trigger surface

* `schedule`: daily at **02:00 UTC** (~04:00 CEST in May / ~03:00
  CET in winter). Fresh rollup at the start of each ops day.
* `workflow_dispatch`: manual run from the GitHub UI; optional
  `threshold` input (default 6).
* `push: branches: [main]`: re-runs on every merge that touches
  aggregator, wirelang, or the test sources the axes depend on.

The workflow does NOT trigger on `pull_request` — that lane is
already covered by `phase-2-validation-gate.yml`.

## Threshold semantics

* **Aggregator default:** `--threshold = sum(weights) = 8` (strict).
* **CI gate default:** `--threshold 6` (six of eight axes required).
* **Strict run via dispatch:** set `threshold=8` from the UI.

The 6/8 floor gives Henrik room to land an axis-fix without a red
main-branch, while three concurrent misses surface as a hard
regression that blocks the gate. Two non-fatal misses are tolerated.

The threshold lives in the *workflow*, not the aggregator default,
so ad-hoc operator runs of the aggregator keep the strict 8/8 floor.

## Exit codes

| Exit | Meaning | Job status |
|---|---|---|
| `0` | total_score >= threshold | green |
| `1` | total_score < threshold | red |
| `2` | I/O / usage error (aggregator could not write artifact, etc.) | red |

The CI job re-asserts the aggregator exit code in a final step so
the GitHub run reflects pass/fail correctly even with
`continue-on-error: true` on the aggregator step (we want the
artifact and step-summary to render on fail).

## How the operator reads the result

1. **Quick triage — step-summary tab.** Open the failed/passed run in
   the Actions tab; the step-summary table at the bottom lists the
   eight axes with per-axis pass/fail markers and the total/threshold
   header. Most days this is enough.

2. **Detailed triage — rollup artifact.** Download the
   `phase-2-acceptance-rollup` artifact (retention 30 days). It is a
   single JSON file matching the `wakir.doppelbetrieb.aggregator/1`
   schema. The `axes` object carries per-axis details (e.g.
   `cross-lang-pin-coverage.details.total` shows the actual pin count
   if it drifted from the expected 16).

3. **Cross-reference with `phase-2-validation-gate`.** If a Phase-2
   axis (gate-2-1 through gate-2-5) is red here but green in the
   per-PR validation gate, the regression landed *after* the PR
   merged — check `main` since the last green acceptance-gate run.

## What to do on FAIL

The threshold is 6/8; a fail means at least three axes regressed
simultaneously. Order of investigation:

1. **Check the rollup JSON for which axes failed.** The aggregator
   never silently drops an axis: a missing axis is reported as
   `{"pass": false, "details": {"reason": "axis-missing"}}`.

2. **Open the failed axis source.** Each axis maps to a specific
   in-tree test or module (see the table above). The failure mode is
   usually one of:
   * **Axis 1-5 fail:** the underlying Phase-2 gate test is red.
     Open the corresponding `test_gate_2_*` function and follow the
     normal per-gate debugging flow.
   * **Axis 6 fail (`bridge-audit-e2e-roundtrip-pass`):** the
     bridge-audit roundtrip is failing; check
     `tests/integration/test_bridge_audit_roundtrip_e2e.py` and the
     Python emit / Rust replay stream-level hash.
   * **Axis 7 fail (`cross-lang-pin-coverage`):** pin counts drifted.
     The `details` block shows per-contract counts; compare against
     `EXPECTED_PIN_COUNTS` in the aggregator (federation_frame: 5,
     nats_subjects: 8, bridge_audit_stream_hash: 3).
   * **Axis 8 fail (`wat-anchor-latency-producer-emitting`):** the
     `WAKIR_ANCHOR_LATENCY_JSONL` env-var was not set in the CI
     environment. Default-off is the *runtime* contract — for the
     daily CI gate the workflow does not set it, so axis 8 is
     expected to be `pass=false` on the daily run. (It is the gate
     accepting an axis-miss inside the 6/8 floor.)

3. **Escalation path.** Three concurrent regressions is unusual;
   notify Henrik (audit) and Amara (QA) before opening fix-PRs. If
   the regression looks systemic (e.g. a wirelang refactor took out
   gate-2-2 and gate-2-3 together), escalate to Priya (CTO).

## Re-running the gate

* **Re-run from the failed run page:** "Re-run failed jobs" button.
  Useful only if the failure is transient (rare for hermetic gates).
* **Re-run via dispatch with strict threshold:** Actions tab →
  `phase-2-acceptance-gate` → "Run workflow" → set `threshold=8`.
  Use this to confirm a fix moves the gate to clean 8/8.
* **Local run:**
  ```
  python scripts/doppelbetrieb-score-aggregator.py \
    --mode=full --threshold 6 --out /tmp/rollup.json
  ```

## Anchors

* ADR-0058 §"Phase 2 — Doppelbetrieb (Wochen 1-4)"
* `docs/quality-gates/phase-2-doppelbetrieb.md` (Amara, PR #80)
* `scripts/doppelbetrieb-score-aggregator.py` (PR #160, Tag-15)
* `tests/scripts/test_phase_2_acceptance_gate.py` (this PR)
* `.github/workflows/phase-2-validation-gate.yml` (per-PR lane)
* `.github/workflows/phase-2-acceptance-gate.yml` (this gate)
