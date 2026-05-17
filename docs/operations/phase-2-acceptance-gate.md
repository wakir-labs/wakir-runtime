<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Phase-2 Acceptance Gate — Operations Playbook

**Status:** active (Tag-22 Mini-Welle, extended Tag-29 / ADR-0066,
2026-05-17).
**Owner:** Tomás (substrate), Henrik (audit), Amara (QA).
**Workflow:** `.github/workflows/phase-2-acceptance-gate.yml`.
**Aggregator:** `scripts/doppelbetrieb-score-aggregator.py`.

## What this gate does

Drives the doppelbetrieb-score-aggregator end-to-end against `main`
and surfaces the 11-axis rollup as a CI artifact plus a step-summary
table. The aggregator scores the five Phase-2 Doppelbetrieb gate
verdicts, three Phase-3a-Foundation acceptance axes, and three Tag-29
Cross-Modul-Stress-Test axes (ADR-0066 KW-26-Mitigation), then sums
per-axis weights into a single total. A threshold check turns the
total into a green/red verdict.

The 11 axes (stable order):

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
| 9 | `cross-modul-state-backing-lifecycle-state-machine` | state-backing × lifecycle-state-machine (Welle-4+5 KW 26) |
| 10 | `cross-modul-subscribe-loop-recovery-workflow`     | subscribe-loop × recovery-workflow (Welle-6+7 KW 27) |
| 11 | `cross-modul-v907-verify-svid-workload-identity`   | V907 × SVID-workload-identity (Welle-1+2 KW 24) |

Each axis carries weight `1`; the max total is `11`.

## Distinction from `phase-2-validation-gate`

| Gate | Lane | Trigger | Purpose |
|---|---|---|---|
| `phase-2-validation-gate` (PR #110) | per-PR / required check | pull_request + push to main | Hermetic per-gate suite, fail-fast, branch-protection-enforced |
| `phase-2-acceptance-gate` (this doc) | ops-readiness / informational | daily schedule + push to main + workflow_dispatch | 11-axis rollup, threshold-checked, NOT a required check |

The acceptance gate is intentionally *not* wired into branch-
protection at this time. Operator-Hand-Decision per Mira (per
`feedback_branch_protection_check_names.md`); the gate first proves
stable on `main` before any required-check promotion.

## Trigger surface

* `schedule`: daily at **02:00 UTC** (~04:00 CEST in May / ~03:00
  CET in winter). Fresh rollup at the start of each ops day.
* `workflow_dispatch`: manual run from the GitHub UI; optional
  `threshold` input (default 9) and `mode` input (default `full`;
  alternatives `cross-modul-stress`, `cross-lang-only`).
* `push: branches: [main]`: re-runs on every merge that touches
  aggregator, wirelang, the cross-lang fixture files, or the test
  sources the axes depend on.

The workflow does NOT trigger on `pull_request` — that lane is
already covered by `phase-2-validation-gate.yml`.

## Threshold semantics (Tag-29)

* **Aggregator default:** `--threshold = sum(weights) = 11` (strict).
* **CI gate default (mode=full):** `--threshold 9` (nine of eleven axes required).
* **CI gate default (mode=cross-modul-stress):** `--threshold 3` (all three Cross-Modul axes).
* **CI gate default (mode=cross-lang-only):** `--threshold 1`.
* **Strict run via dispatch:** set `threshold=11` from the UI.

The 9/11 floor gives Henrik room to land an axis-fix without a red
main-branch, while three concurrent misses surface as a hard
regression that blocks the gate. Two non-fatal misses are tolerated.

The threshold lives in the *workflow*, not the aggregator default,
so ad-hoc operator runs of the aggregator keep the strict 11/11 floor.

### Cross-Modul-Stress mode (pre-cutover smoke)

ADR-0066 schedules three parallel Doppel-Wellen (KW 24, KW 26, KW
27). Before each Doppel-Welle cutover Mittwoch the operator can
dispatch this workflow with `mode=cross-modul-stress` to evaluate
**only** the three Cross-Modul axes. The eight non-Cross-Modul axes
are flagged `axis-missing` in the rollup. Threshold defaults to `3`
(all three axes green); the operator may override.

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
   11 axes with per-axis pass/fail markers and the total/threshold
   header. Most days this is enough.

2. **Detailed triage — rollup artifact.** Download the
   `phase-2-acceptance-rollup` artifact (retention 30 days). It is a
   single JSON file matching the `wakir.doppelbetrieb.aggregator/2`
   schema (bumped Tag-29 for the three Cross-Modul axes). The `axes`
   object carries per-axis details (e.g.
   `cross-lang-pin-coverage.details.total` shows the actual pin count
   if it drifted from the expected 16;
   `cross-modul-state-backing-lifecycle-state-machine.details.both_envs_rust`
   shows whether the operator flipped both Doppel-Welle ENV-flags).

3. **Cross-reference with `phase-2-validation-gate`.** If a Phase-2
   axis (gate-2-1 through gate-2-5) is red here but green in the
   per-PR validation gate, the regression landed *after* the PR
   merged — check `main` since the last green acceptance-gate run.

## What to do on FAIL

The threshold is 9/11 (Tag-29); a fail means at least three axes
regressed simultaneously. Order of investigation:

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
     accepting an axis-miss inside the 9/11 floor.)
   * **Axis 9-11 fail (Cross-Modul-Stress, Tag-29):** one of the
     two per-axis ENV-flags is not set, or one of the cross-lang
     fixture files drifted from its pinned shape. The `details`
     block reports `both_envs_rust`, the per-fixture-file count,
     and (for the state-backing axis) any
     `*_schema_drift` marker. For the daily CI gate the workflow
     does not set the Welle-* ENV-flags, so these three axes are
     expected to be `pass=false` on the daily run — same posture as
     axis 8. The pre-cutover smoke (`mode=cross-modul-stress`) is
     the substantive use-case; see the dispatch instructions in
     §"Cross-Modul-Stress mode" above.

3. **Escalation path.** Three concurrent regressions is unusual;
   notify Henrik (audit) and Amara (QA) before opening fix-PRs. If
   the regression looks systemic (e.g. a wirelang refactor took out
   gate-2-2 and gate-2-3 together), escalate to Priya (CTO).

## Re-running the gate

* **Re-run from the failed run page:** "Re-run failed jobs" button.
  Useful only if the failure is transient (rare for hermetic gates).
* **Re-run via dispatch with strict threshold:** Actions tab →
  `phase-2-acceptance-gate` → "Run workflow" → set `threshold=11`.
  Use this to confirm a fix moves the gate to clean 11/11.
* **Pre-cutover Cross-Modul-Stress smoke:** Actions tab →
  `phase-2-acceptance-gate` → "Run workflow" → set
  `mode=cross-modul-stress`. Evaluates only the three Cross-Modul
  axes; threshold defaults to `3`.
* **Local run:**
  ```
  python scripts/doppelbetrieb-score-aggregator.py \
    --mode=full --threshold 9 --out /tmp/rollup.json
  ```

## Anchors

* ADR-0058 §"Phase 2 — Doppelbetrieb (Wochen 1-4)"
* ADR-0066 §"Cross-Modul-Drift-Detection für Doppel-Wellen" (Tag-29)
* `docs/quality-gates/phase-2-doppelbetrieb.md` (Amara, PR #80)
* `scripts/doppelbetrieb-score-aggregator.py` (PR #160, Tag-15; Tag-29 extension)
* `tests/scripts/test_phase_2_acceptance_gate.py`
* `tests/scripts/test_cross_modul_stress.py` (Tag-29)
* `.github/workflows/phase-2-validation-gate.yml` (per-PR lane)
* `.github/workflows/phase-2-acceptance-gate.yml` (this gate)
