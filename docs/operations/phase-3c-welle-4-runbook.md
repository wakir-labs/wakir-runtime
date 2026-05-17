# Phase-3c Welle-4 Validation Runbook — state_backing

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine state_backing resolver), Tomás Reinhart (Matrix-Lead) |
| ADRs | [0065](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md) (Cutover-Plan), [0066](../../decisions/0066-phase-3c-beschleunigung-option-a-plus.md) (Acceleration) |
| Workflow | [`.github/workflows/phase-3c-welle-4-validation.yml`](../../.github/workflows/phase-3c-welle-4-validation.yml) |
| Tests | [`tests/workflows/test_phase_3c_welle_4_5_6_7_validation.py`](../../tests/workflows/test_phase_3c_welle_4_5_6_7_validation.py) |
| Cadence | Wednesday 06:00 UTC (~08:00 CEST in May) + workflow_dispatch |
| Welle-4 component | `state_backing` (KW 26, parallel to Welle-5) |
| Welle-4 env-var | `WAKIR_STATE_BACKING_BACKEND` (rust value: `rust_inmemory`) |
| KW-26 Doppel-Welle partner | Welle-5 `lifecycle_state_machine` |

## Purpose

This runbook explains the **Welle-4 Validation Workflow**, the wired-
substrate readiness check that the Phase-3c Welle-4 cutover decision
rests on. ADR-0065 + ADR-0066 (Acceleration Option-A+) demand a
Monday-morning Pilot-VM Live-Smoke before the Welle-4 cutover-PR flips
the production default of `WAKIR_STATE_BACKING_BACKEND` from `python`
to `rust_inmemory`. The Live-Smoke is **operator-hand-territory**.
This workflow is the **hermetic readiness check** that runs three
days *before* the Monday smoke and emits the canonical
`cutover-acceptance-decision-welle-4` JSON envelope.

Welle-4 ships in parallel with Welle-5 (`lifecycle_state_machine`) in
KW 26 — the KW-26 Doppel-Welle. The two readiness reports land on the
same wednesday-morning slot so operators triage both in one session.

### Why parallel-execution is safe — and what the Cross-Modul-Stress-Test catches

The state_backing + lifecycle_state_machine pair share state-mutation
semantics: every fsm transition writes through state_backing. Drift
between the two resolvers (e.g. a Python-only path in one and a
rust-default path in the other) can only surface when both substrates
are exercised against the same fixture-pair. ADR-0066 §Mitigations §1
demands a Cross-Modul-Drift-Detection axis for the Doppel-Wellen; PR
#197 wired the three Cross-Modul axes into the
`doppelbetrieb-score-aggregator --mode cross-modul-stress` envelope.
This workflow consumes that envelope as **Step 5** so the
Mo Live-Smoke decision rests on a drift-free signal.

Sibling artifacts:

* [`phase-3c-welle-5-runbook.md`](phase-3c-welle-5-runbook.md) —
  KW-26 Doppel-Welle partner runbook. Read after this one to
  understand the symmetric mitigation.
* [`phase-3c-welle-1-runbook.md`](phase-3c-welle-1-runbook.md) —
  Welle-1 readiness check pattern; the same 5-step shape is the
  base of the Welle-4 6-step extension.
* [`phase-3c-cutover-runbook.md`](phase-3c-cutover-runbook.md) —
  Dry-run usage walkthrough for ad-hoc operator rehearsal.

## Trigger surface

```text
schedule:        Wed 06:00 UTC (= 08:00 CEST in May)
workflow_dispatch: target-binary-count, boots, score-band-floor
```

The wednesday-cron cadence is deliberate: three days before the
ADR-0065 §Mo Live-Smoke target gives Selin, Reza, and Tomás time to
investigate any red signal without sliding the Welle-4/5 timeline.

## Six-step decision flow

| Step | Substrate | Failure semantics |
|------|-----------|-------------------|
| 1. Trigger-gate aggregator | `scripts/phase-3c-trigger-gate-aggregator.py --json` | Exit 0 = green; exit 1 = yellow (tolerated iff Gate-4 sole yellow); exit 2 = red |
| 2. Cutover-dry-run | `scripts/phase-3c-cutover-dry-run.py --component state_backing --boots 12` | Exit non-zero fails the decision |
| 3. Test-persona-boot (rust) | `pytest test_rust_backend_switch.py -k state_backing` with `WAKIR_STATE_BACKING_BACKEND=rust_inmemory` | Pytest exit non-zero fails the decision |
| 4. Bridge-audit-roundtrip | `pytest test_bridge_audit_roundtrip_e2e.py` | Pytest exit 0 (pass or all-skipped) = OK; exit 5 tolerated |
| 5. Cross-modul-stress | `scripts/doppelbetrieb-score-aggregator.py --mode cross-modul-stress` | Exit non-zero blocks ready (KW-26 Doppel-Welle drift) |
| 6. Render cutover-acceptance-decision | Inline python | Writes `out/cutover-acceptance-decision.json`; job exits 0 iff `ready_for_live_smoke == true` |

### Decision policy (Step 6)

`ready_for_live_smoke == true` requires **all** of:

* Step 1: `gate-aggregator-rc in {0, 1-tolerated}` (Gate-4 yellow
  alone tolerated per ADR-0065 §Trigger-Bedingung-4).
* Step 2: dry-run exited 0 AND the feasibility-band meets or exceeds
  the configured floor (default `GREEN`).
* Step 3: persona-boot pytest exited 0 with
  `WAKIR_STATE_BACKING_BACKEND=rust_inmemory`.
* Step 4: bridge-audit-roundtrip pytest exited 0 (pass or all-SKIP).
* Step 5: cross-modul-stress aggregator exited 0 (all three Cross-
  Modul axes green).

Any other state surfaces as `ready_for_live_smoke == false` and the
workflow job exits 1. The artifact still ships (always-upload).

## Artifact: `cutover-acceptance-decision-welle-4`

Each run uploads a single artifact bundle (`retention: 30 days`):

```text
cutover-acceptance-decision.json   # canonical decision envelope
trigger-gate-report.json           # raw Step 1 output (5 gates)
dry-run-envelope.json              # raw Step 2 output (feasibility)
persona-boot.log                   # Step 3 pytest stdout
persona-boot-junit.xml             # Step 3 junit
bridge-audit.log                   # Step 4 pytest stdout
bridge-audit-junit.xml             # Step 4 junit
cross-modul-stress.json            # Step 5 cross-modul-axes envelope
```

### `cutover-acceptance-decision.json` shape (welle-4 specific)

```json
{
  "schema": "wakir.phase-3c.welle-4-validation/1",
  "welle": 4,
  "component": "state_backing",
  "env_var": "WAKIR_STATE_BACKING_BACKEND",
  "doppel_welle_partner": "lifecycle_state_machine",
  "ready_for_live_smoke": true,
  "score_band_floor": "GREEN",
  "observed_band": "GREEN",
  "steps": {
    "step_1_trigger_gates": {"exit_code": 1, "status": "yellow_tolerated"},
    "step_2_cutover_dry_run": {"exit_code": 0, "ok": true},
    "step_3_persona_boot_rust": {"exit_code": 0, "ok": true},
    "step_4_bridge_audit_roundtrip": {"exit_code": 0, "ok": true},
    "step_5_cross_modul_stress": {"exit_code": 0, "ok": true}
  },
  "cross_modul_summary": {"axes": 3, "passed": true}
}
```

Field stability: the `schema` field is versioned (`/1`). A future
breaking change to the envelope shape bumps to `/2`.

## Operator walkthrough — wednesday morning (KW-26)

1. Open the [Actions tab](https://github.com/wakir-labs/wakir-runtime/actions/workflows/phase-3c-welle-4-validation.yml)
   and find the most recent scheduled run. Open the Welle-5 run in a
   second tab — both should be green for the Mo Live-Smoke to land.
2. Inspect the **run-tab summary**: a markdown table renders the
   five step-exit-codes (including cross-modul-stress) and the
   cutover-decision verdict.
3. If the verdict is `YES` on both Welle-4 and Welle-5 and the
   cross-modul-stress step is green: proceed with the KW-26 Doppel-
   Welle cutover-PR planning per ADR-0066.
4. If either workflow says `NO`: download the
   `cutover-acceptance-decision-welle-4` artifact and read the six
   sub-bundles to find the failing step.

### Failure routing

| Failing step | Owner | First diagnostic |
|--------------|-------|------------------|
| 1 (trigger-gates RED) | Kai (inventories), Reza (resolvers) | Inspect `trigger-gate-report.json` |
| 2 (dry-run RED) | Selin (resolver substance) | Inspect `dry-run-envelope.json` |
| 3 (persona-boot RED) | Selin | `persona-boot-junit.xml` + `persona-boot.log` |
| 4 (bridge-audit RED) | Selin (cross-lang substrate) | `bridge-audit.log` |
| 5 (cross-modul RED) | Selin + Reza (joint) | `cross-modul-stress.json`; which axis failed |

Tomás (Matrix-Lead) is the cross-step moderator if two or more steps
fail in the same run.

## Manual dispatch — ad-hoc readiness check

```bash
gh workflow run phase-3c-welle-4-validation.yml \
    -f target-binary-count=7 \
    -f boots=12 \
    -f score-band-floor=GREEN
```

A `boots` count higher than 12 gives the latency-percentile sub-score
a wider sample; 24 is a useful diagnostic value when the GREEN-band
verdict is borderline.

## Relationship to other Phase-3c artifacts

```text
+------------------------------------+
| ADR-0066 (Acceleration, KW-26 Doppel-Welle) |
+--------------+---------------------+
               |
   +-----------+-----------+
   |                       |
   v                       v
phase-3c-welle-4-      phase-3c-welle-5-
validation.yml         validation.yml
(state_backing)        (lifecycle_state_machine)
   |                       |
   |   shared step 5       |
   +---------+-------------+
             |
             v
   doppelbetrieb-score-aggregator
   --mode cross-modul-stress
   (drift-detection axis)
             |
             v
   ADR-0066 §Mo Live-Smoke (KW-26)
   Operator-Hand, real Pilot-VM
```

## Bandwidth notes

* Wednesday-cron run completes in ~5-7 minutes on the GitHub-hosted
  runner (checkout 15 s, install 60 s, Step 1-2 ~6 s each, Step 3
  ~30 s, Step 4 ~10 s with all-skip, Step 5 ~5 s, Step 6 ~5 s,
  upload 5 s). The extra Step 5 adds ~5 s vs. the 5-step Welle-1/2
  workflow.

## Drift sentinels — tests/workflows/test_phase_3c_welle_4_5_6_7_validation.py

The shared Bundle-test file asserts the workflow contract so a future
edit that drops a step, swaps the env-var, or skips the cross-modul-
stress step on Welle-4/5 regresses with a clear hermetic-test
failure. The file is parametrised over the four wellen plus dedicated
Bundle-specific tests (cross-modul presence assertion, decision
schema per welle, runbook existence per welle).

## Anchors

* ADR-0065 — Phase-3c Cutover-Plan (Python-Default → Rust-Default).
* ADR-0066 — Phase-3c Acceleration Option-A+ (KW-26 Doppel-Welle).
* `feedback_sandbox_host_trennung.md` — Sandbox vs. operator-hand
  boundary; this workflow lives strictly on the sandbox side.
* `feedback_branch_protection_check_names.md` — this workflow is
  deliberately NOT wired as a required status check.

— Tomás Reinhart (Matrix-Lead), Sprint-Tag-32 Mini-Welle, 2026-05-17.
