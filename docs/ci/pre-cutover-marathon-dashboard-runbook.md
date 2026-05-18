# Phase-3c Pre-Cutover Marathon Dashboard - Operator Runbook

| Field       | Value |
|-------------|-------|
| Workflow    | `.github/workflows/phase-3c-pre-cutover-marathon-dashboard.yml` |
| Aggregator  | `tooling/ci/aggregate_pre_cutover_marathon_dashboard.py` |
| Emitter     | `tooling/ci/emit_marathon_probe_envelope.py` |
| Tests       | `tests/ci/test_pre_cutover_marathon_dashboard.py` (27 hermetic) |
| ADRs        | ADR-0066 (Phase-3c Doppel-Welle calendar), ADR-0065 (Welle-1 v907_verify), ADR-0058 §Nachtrag (Mira-Hand-SSH) |
| Tag         | Tag-42, Author Tomas |
| Status      | Tag-42 dress-rehearsal; goes "must-be-GREEN" on KW-24-Mo-Morning |

## Purpose

The Marathon-Dashboard runs all seven ADR-0066 Welle pre-cutover
probes in parallel, aggregates their verdicts into a single
**Marathon-Readiness** signal (`READY` / `CAUTION` / `BLOCK` /
`NOT-READY`), surfaces cross-Welle drift, and emits a rendered
Markdown step-summary. The dashboard runs every Monday in the
four-week KW-24..KW-27 cutover window, plus on `workflow_dispatch`,
plus on any push that touches a Welle-probe substrate.

This complements the Tag-41 `phase-3c-pre-cutover-sanity.yml`
workflow (PR #266): sanity verifies the orchestration *substrate*
is intact; dashboard verifies the seven *probes themselves* pass.
Both must be GREEN/READY before KW-24 Cutover-Execution starts.

## Probe-script ownership

| Welle | Component | Probe script | Owner |
|------:|-----------|--------------|-------|
| 1 | `v907_verify` | `scripts/phase-3c/welle-1-pre-cutover-probe.sh` | Kai PR #267 (on main as of Tag-41) |
| 2 | `svid_workload_identity` | `scripts/phase-3c/welle-2-pre-cutover-probe.sh` | Selin Tag-42 |
| 3 | `bridge_audit_writer` | `scripts/phase-3c/welle-3-pre-cutover-probe.sh` | Selin Tag-42 |
| 4 | `state_backing` | `scripts/phase-3c/welle-4-pre-cutover-probe.sh` | Kai Tag-42 |
| 5 | `lifecycle_state_machine` | `scripts/phase-3c/welle-5-pre-cutover-probe.sh` | Kai Tag-42 |
| 6 | `subscribe_loop` | `scripts/phase-3c/welle-6-pre-cutover-probe.sh` | Amara Tag-42 |
| 7 | `recovery_workflow` | `scripts/phase-3c/welle-7-pre-cutover-probe.sh` | Amara Tag-42 |

When a probe script is not yet on `main`, the dashboard records
the Welle's verdict as `NOT-EXEC` and does not block the matrix-leg.
This is by design: the Tag-42 dashboard ships before all seven
probes land, and AR-Direktive Tag-41 explicitly mandates non-
blocking behaviour on missing/unreachable probes.

## Sandbox-Stub-Mode (CI)

CI cannot SSH to the wakir-pilot live VM. The dashboard runs every
per-Welle probe in `--dry-run` mode with `WAKIR_SSH_BIN=true`:

* The GNU `true` binary silently consumes arguments and exits 0,
  so the probe never opens a real socket.
* A fresh ephemeral `HOME` is allocated per matrix-leg with a
  synthetic `~/.ssh/wakir-pilot-vm-diagnose` file. The stub `ssh`
  never reads it; this satisfies the probe's precondition check.
* The probe still exercises all axis-functions, verdict-aggregation,
  and exit-code mapping. Probes that pass `--dry-run` in CI prove
  their structure is correct.

Live-VM verification is operator-hand on Cutover-Day-Morning (per
ADR-0058 §Nachtrag). The dashboard is **not** a substitute for
that step; it gates the calendar window, not the live execution.

## Marathon-Readiness rule

The aggregator maps per-Welle verdicts to a marathon verdict:

* `READY`     - all seven Welle-verdicts `GREEN`.
* `CAUTION`   - 1..2 `CAUTION`/`NOT-EXEC`, zero `BLOCK`.
* `BLOCK`     - any `BLOCK`, OR 3+ `CAUTION`/`NOT-EXEC`.
* `NOT-READY` - all seven `NOT-EXEC` (sandbox-default before
                any probe scripts have landed).

Workflow exit semantics:

| Verdict     | Marathon-Aggregate exit | Operator action |
|-------------|------------------------:|-----------------|
| `READY`     | 0 | Cutover-Execution may start KW-24 Mo 10:00 CEST. |
| `CAUTION`   | 0 (warning) | Inspect failed Welle; AR-Hand decides. |
| `BLOCK`     | 1 (error) | Cutover-Execution does NOT start. Drift analysis required. |
| `NOT-READY` | 0 (warning) | Probes haven't been written yet; wait for Tag-42 closeout. |

## ADR-0066 calendar plan (pinned)

| KW | Welles | Mode | Cutover-Day-Window (CEST) |
|---|---|---|---|
| KW-24 | Welle-1 + Welle-2 | parallel | Mon 2026-06-08 08:00..10:00 |
| KW-25 | Welle-3 | solo | Mon 2026-06-15 08:00..10:00 |
| KW-26 | Welle-4 + Welle-5 | parallel | Mon 2026-06-22 08:00..10:00 |
| KW-27 | Welle-6 + Welle-7 | parallel | Mon 2026-06-29 08:00..10:00 |

Deviation from this plan breaks
`test_adr_0066_plan_pins_all_seven_welles` and
`test_cross_coupling_pairs_match_adr_0066`. The plan constants
are stored in `ADR_0066_PLAN` and `CROSS_COUPLING_PAIRS` inside
the aggregator module.

## Cross-Welle coupling

ADR-0066 pins three doppel-welle pairs that must move together:

* **KW-24** Welle-1 (`v907_verify`) + Welle-2 (`svid_workload_identity`)
* **KW-26** Welle-4 (`state_backing`) + Welle-5 (`lifecycle_state_machine`)
* **KW-27** Welle-6 (`subscribe_loop`) + Welle-7 (`recovery_workflow`)

A pair "drifts" when one half is `GREEN` and the other is `BLOCK`,
or when one is `GREEN` and the other is `NOT-EXEC`, or when one
is `GREEN` and the other is `CAUTION`. The dashboard surfaces
drifts in the step-summary; the operator decides whether to delay
the pair.

## Operator playbook

### Reading the dashboard

The aggregator emits two artifacts on every run:

1. `pre-cutover-marathon-dashboard-verdict.json` - the marathon
   envelope (verdict + per-Welle + cross-coupling + windows).
2. `pre-cutover-marathon-dashboard-summary.md` - the rendered
   Markdown table (also appended to the GitHub Actions
   step-summary panel).

Open the step-summary panel for the Mon 06:00 UTC scheduled run
to see the marathon verdict at a glance.

### On `READY` (all seven GREEN)

* Proceed to Cutover-Day-Morning operator-hand checklist.
* No action required from the dashboard side.

### On `CAUTION` (1..2 soft-fails, zero BLOCK)

1. Open the per-Welle artifact for each soft-fail (`marathon-probe-welle-N`).
2. Read the `details` field on the envelope; cross-reference with
   the owning Welle's probe-script docstring.
3. **AR-Hand ratification:** a `CAUTION` verdict does NOT block
   Cutover-Execution by itself. AR-Hand decides whether to proceed
   or delay the affected Welle to the next KW.

### On `BLOCK` (any BLOCK, or 3+ soft-fails)

1. Re-read the marathon envelope's `welle_verdicts` array; identify
   which Welles are `BLOCK`.
2. For each `BLOCK` Welle:
   - If `probe_present: false` -> the probe script is missing;
     escalate to the owning persona per the ownership table above.
   - If `probe_present: true` -> reproduce locally with::
     ```bash
     HOME=$(mktemp -d) && mkdir -p "$HOME/.ssh" \
       && touch "$HOME/.ssh/wakir-pilot-vm-diagnose"
     WAKIR_SSH_BIN=true bash scripts/phase-3c/welle-N-pre-cutover-probe.sh --dry-run
     echo "exit=$?"
     ```
   - Exit `2` = BLOCK; exit `3` = preconditon failure; exit `4` =
     SSH unreachable (will not occur with `WAKIR_SSH_BIN=true`).
3. Check the cross-coupling block. If a doppel-welle pair drifts
   (one GREEN, one BLOCK), the operator must decide whether to:
   - Delay the entire pair to the next KW, OR
   - Promote the GREEN half solo and revisit the partner in the
     following KW (requires explicit AR-Hand approval; changes
     the ADR-0066 calendar plan).
4. Coordinate with Kai (live-VM-drill), Amara (E2E-regression),
   Reza (cross-welle-generalprobe) on whether their substrates
   report a parallel red. If yes, Cutover-Execution moves to KW-25
   regardless.

### On `NOT-READY` (all seven NOT-EXEC)

This is the sandbox-default before any probe scripts have landed.
Wait for the Tag-42 closeout report to confirm probes 2..7 are on
`main`. Re-run the dashboard via `workflow_dispatch` after the
last probe lands.

## Cross-substrate links

* Tag-41 Pre-Cutover-Sanity: `.github/workflows/phase-3c-pre-cutover-sanity.yml` (PR #266)
* Welle-1 Pre-Cutover-Probe (Kai): `scripts/phase-3c/welle-1-pre-cutover-probe.sh` (PR #267)
* Cross-Welle Generalprobe (Reza): `scripts/phase-3c/cross-welle-cutover-generalprobe.py` (PR #263)
* Marathon-Aggregat-Tracker (Selin): `scripts/phase-3c/marathon-aggregat-tracker.py` (PR #261)
* Phase-3-COMPLETE-Marker (Tomas): `.github/workflows/phase-3-complete-marker.yml` (PR #258)
* Live-VM Cutover-Drill (Kai): `scripts/phase-3c/live-vm-cutover-drill.sh` (PR #259)
* Cutover-Day Live-Stream-Aggregator (Noa): `.github/workflows/cutover-day-live-stream.yml` (PR #268)

## Not a required status check

Per `feedback_branch_protection_check_names.md`, this workflow
gates a calendar-window (KW-24 marathon-start), not individual
PRs. It is NOT listed as a required status check on PRs. Branch-
protection check-names remain on the Phase-A 6-name set
(reconciled by PR #264, Tag-41).

## Re-baseline procedure

When ADR-0066 calendar drifts (e.g. KW-24 slips to KW-25), update:

1. `ADR_0066_PLAN` in `tooling/ci/aggregate_pre_cutover_marathon_dashboard.py`
2. `CROSS_COUPLING_PAIRS` if pairings change
3. This runbook's "calendar plan" table
4. The test fixtures in
   `tests/ci/test_pre_cutover_marathon_dashboard.py`
   (specifically `test_adr_0066_plan_pins_all_seven_welles` and
   `test_cross_coupling_pairs_match_adr_0066`)

Submit as a single PR; do not split. A drifted plan that doesn't
match a corresponding test update creates a CI false-positive
that masks the calendar slip.
