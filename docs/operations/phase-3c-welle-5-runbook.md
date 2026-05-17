# Phase-3c Welle-5 Validation Runbook — lifecycle_state_machine

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine fsm resolver), Tomás Reinhart (Matrix-Lead) |
| ADRs | [0065](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md) (Cutover-Plan), [0066](../../decisions/0066-phase-3c-beschleunigung-option-a-plus.md) (Acceleration) |
| Workflow | [`.github/workflows/phase-3c-welle-5-validation.yml`](../../.github/workflows/phase-3c-welle-5-validation.yml) |
| Tests | [`tests/workflows/test_phase_3c_welle_4_5_6_7_validation.py`](../../tests/workflows/test_phase_3c_welle_4_5_6_7_validation.py) |
| Cadence | Wednesday 06:00 UTC (~08:00 CEST in May) + workflow_dispatch |
| Welle-5 component (long form) | `lifecycle_state_machine` (KW 26, parallel to Welle-4) |
| Welle-5 component (in-repo short form) | `fsm` |
| Welle-5 env-var | `WAKIR_FSM_BACKEND` (rust value: `rust`) |
| KW-26 Doppel-Welle partner | Welle-4 `state_backing` |

## Purpose

This runbook explains the **Welle-5 Validation Workflow**, the wired-
substrate readiness check that the Phase-3c Welle-5 cutover decision
rests on. ADR-0065 + ADR-0066 (Acceleration Option-A+) demand a
Monday-morning Pilot-VM Live-Smoke before the Welle-5 cutover-PR flips
the production default of `WAKIR_FSM_BACKEND` from `python` to
`rust`. The Live-Smoke is **operator-hand-territory**. This workflow
is the **hermetic readiness check** that runs three days *before* the
Monday smoke and emits the canonical
`cutover-acceptance-decision-welle-5` JSON envelope.

Welle-5 ships in parallel with Welle-4 (`state_backing`) in KW 26 —
the KW-26 Doppel-Welle. The two readiness reports land on the same
wednesday-morning slot.

### Naming — long form vs. short form

ADR-0066 uses the long-form component name `lifecycle_state_machine`
for human-facing labels; the in-repo dry-run + resolver substrate
uses the short form `fsm` (see
`scripts/phase-3c-cutover-dry-run.py` PHASE_3C_COMPONENT_ALIASES and
`wirelang/persona_engine/rust_backend_switch.py`
`resolve_fsm_backend`). The dry-run script accepts both spellings
and normalises to the short form. This workflow uses the short form
for the dry-run and pytest-selector arguments and the long form for
human-facing labels and the decision-envelope `component` field so
the artifact reads clean to operators.

### Why parallel-execution is safe — Cross-Modul-Stress-Test

The lifecycle_state_machine + state_backing pair share state-mutation
semantics: every fsm transition writes through state_backing. Drift
between the two resolvers can only surface against fixture-pairs
that exercise both substrates. ADR-0066 §Mitigations §1 demands a
Cross-Modul-Drift-Detection axis; PR #197 wired the aggregator
substrate. This workflow consumes the
`doppelbetrieb-score-aggregator --mode cross-modul-stress` envelope
as **Step 5**.

Sibling artifacts:

* [`phase-3c-welle-4-runbook.md`](phase-3c-welle-4-runbook.md) —
  KW-26 Doppel-Welle partner runbook. The Step 5 (Cross-Modul-
  Stress-Test) is symmetric between Welle-4 and Welle-5.
* [`phase-3c-welle-1-runbook.md`](phase-3c-welle-1-runbook.md) —
  Welle-1 readiness check pattern.

## Trigger surface

```text
schedule:        Wed 06:00 UTC (= 08:00 CEST in May)
workflow_dispatch: target-binary-count, boots, score-band-floor
```

## Six-step decision flow

| Step | Substrate | Failure semantics |
|------|-----------|-------------------|
| 1. Trigger-gate aggregator | `scripts/phase-3c-trigger-gate-aggregator.py --json` | Exit 0 = green; exit 1 = yellow (tolerated iff Gate-4 sole yellow); exit 2 = red |
| 2. Cutover-dry-run | `scripts/phase-3c-cutover-dry-run.py --component fsm --boots 12` | Exit non-zero fails the decision |
| 3. Test-persona-boot (rust) | `pytest test_rust_backend_switch.py -k fsm` with `WAKIR_FSM_BACKEND=rust` | Pytest exit non-zero fails the decision |
| 4. Bridge-audit-roundtrip | `pytest test_bridge_audit_roundtrip_e2e.py` | Pytest exit 0 (pass or all-skipped) = OK |
| 5. Cross-modul-stress | `scripts/doppelbetrieb-score-aggregator.py --mode cross-modul-stress` | Exit non-zero blocks ready (KW-26 Doppel-Welle drift) |
| 6. Render cutover-acceptance-decision | Inline python | Writes `out/cutover-acceptance-decision.json`; job exits 0 iff `ready_for_live_smoke == true` |

### Decision policy (Step 6)

Identical to Welle-4. `ready_for_live_smoke == true` requires all
five upstream steps green, gate-status in {green, gate-4-yellow-
tolerated}, band-floor met.

## Artifact: `cutover-acceptance-decision-welle-5`

```text
cutover-acceptance-decision.json   # canonical decision envelope
trigger-gate-report.json
dry-run-envelope.json
persona-boot.log
persona-boot-junit.xml
bridge-audit.log
bridge-audit-junit.xml
cross-modul-stress.json
```

### Decision envelope (welle-5 specific)

```json
{
  "schema": "wakir.phase-3c.welle-5-validation/1",
  "welle": 5,
  "component": "lifecycle_state_machine",
  "component_short": "fsm",
  "env_var": "WAKIR_FSM_BACKEND",
  "doppel_welle_partner": "state_backing",
  "ready_for_live_smoke": true,
  "steps": {
    "step_5_cross_modul_stress": {"exit_code": 0, "ok": true}
  }
}
```

The `component` field carries the long-form name for the operator-
facing artifact; `component_short` carries the in-repo short form so
the artifact can be cross-referenced against the resolver code
without an alias lookup.

## Operator walkthrough — wednesday morning (KW-26)

1. Open the Welle-5 [Actions tab](https://github.com/wakir-labs/wakir-runtime/actions/workflows/phase-3c-welle-5-validation.yml)
   and find the most recent scheduled run.
2. Open the Welle-4 run in a second tab — both must be green and the
   cross-modul-stress step must be green for the KW-26 Mo Live-Smoke
   to proceed.
3. If the verdict is `YES` on both: proceed with the KW-26 Doppel-
   Welle cutover-PR planning per ADR-0066.
4. If either workflow says `NO`: download the artifact and follow
   the failure-routing table below.

### Failure routing

| Failing step | Owner | First diagnostic |
|--------------|-------|------------------|
| 1 (trigger-gates RED) | Kai, Reza | `trigger-gate-report.json` |
| 2 (dry-run RED) | Selin | `dry-run-envelope.json`; the fsm resolver's `chosen_backend_counts` should be `{rust: 12}` on a healthy run |
| 3 (persona-boot RED) | Selin | `persona-boot-junit.xml`; the fsm subprocess-bridge tests live at the rust_backend_switch test file lines ~959-1144 |
| 4 (bridge-audit RED) | Selin | `bridge-audit.log` |
| 5 (cross-modul RED) | Selin + Reza | `cross-modul-stress.json`; the state_backing × lifecycle_state_machine axis is the one that matters for KW-26 |

## Manual dispatch — ad-hoc readiness check

```bash
gh workflow run phase-3c-welle-5-validation.yml \
    -f target-binary-count=7 \
    -f boots=12 \
    -f score-band-floor=GREEN
```

## Relationship to other Phase-3c artifacts

```text
ADR-0066 §KW-26 Doppel-Welle
   |
   +---> Welle-4 (state_backing)        <- THIS welle's partner
   +---> Welle-5 (lifecycle_state_machine) <- THIS welle
   |
   +---> Step 5 of both: cross-modul-stress
            |
            v
       doppelbetrieb-score-aggregator
       --mode cross-modul-stress
```

## Bandwidth notes

* Wednesday-cron run completes in ~5-7 minutes on the GitHub-hosted
  runner. The 6-step workflow is ~5 seconds slower than the
  5-step Welle-1/2 workflow due to the extra Step 5.

## Drift sentinels

See [`test_phase_3c_welle_4_5_6_7_validation.py`](../../tests/workflows/test_phase_3c_welle_4_5_6_7_validation.py)
— the Bundle-test file pins the Welle-5 contract symmetrically with
Welle-4 plus the per-welle deltas (component_long, fsm short-form,
WAKIR_FSM_BACKEND).

## Anchors

* ADR-0065 — Phase-3c Cutover-Plan.
* ADR-0066 — Phase-3c Acceleration Option-A+ (KW-26 Doppel-Welle).
* PR #197 — Cross-Modul-Stress-Test substrate.
* `feedback_sandbox_host_trennung.md`.
* `feedback_branch_protection_check_names.md`.

— Tomás Reinhart (Matrix-Lead), Sprint-Tag-32 Mini-Welle, 2026-05-17.
