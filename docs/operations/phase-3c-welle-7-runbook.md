# Phase-3c Welle-7 Validation Runbook — recovery_workflow

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine recovery resolver), Tomás Reinhart (Matrix-Lead) |
| ADRs | [0065](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md) (Cutover-Plan), [0066](../../decisions/0066-phase-3c-beschleunigung-option-a-plus.md) (Acceleration) |
| Workflow | [`.github/workflows/phase-3c-welle-7-validation.yml`](../../.github/workflows/phase-3c-welle-7-validation.yml) |
| Tests | [`tests/workflows/test_phase_3c_welle_4_5_6_7_validation.py`](../../tests/workflows/test_phase_3c_welle_4_5_6_7_validation.py) |
| Cadence | Wednesday 06:00 UTC (~08:00 CEST in May) + workflow_dispatch |
| Welle-7 component (long form) | `recovery_workflow` (KW 27, parallel to Welle-6) |
| Welle-7 component (in-repo short form) | `recovery` |
| Welle-7 env-var | `WAKIR_RECOVERY_BACKEND` (rust value: `rust`) |
| KW-27 Doppel-Welle partner | Welle-6 `subscribe_loop` |

## Purpose

This runbook explains the **Welle-7 Validation Workflow**, the wired-
substrate readiness check that the Phase-3c Welle-7 (the final
welle) cutover decision rests on. ADR-0065 + ADR-0066 (Acceleration
Option-A+) demand a Monday-morning Pilot-VM Live-Smoke before the
Welle-7 cutover-PR flips the production default of
`WAKIR_RECOVERY_BACKEND` from `python` to `rust`. The Live-Smoke is
**operator-hand-territory**. This workflow is the **hermetic
readiness check** that runs three days *before* the Monday smoke and
emits the canonical `cutover-acceptance-decision-welle-7` JSON
envelope.

Welle-7 ships in parallel with Welle-6 (`subscribe_loop`) in KW 27 —
the KW-27 Doppel-Welle. Welle-7 is also the **final welle of
Phase-3c**; a green readiness report here is the last hermetic gate
before Phase-3c-Ende (~2026-06-21).

### Naming — long form vs. short form

ADR-0066 uses the long-form component name `recovery_workflow` for
human-facing labels; the in-repo dry-run + resolver substrate uses
the short form `recovery` (see
`scripts/phase-3c-cutover-dry-run.py` PHASE_3C_COMPONENT_ALIASES and
`wirelang/persona_engine/rust_backend_switch.py`
`resolve_recovery_backend`). The dry-run script accepts both
spellings and normalises to the short form. This workflow uses the
short form for the dry-run and pytest-selector arguments and the
long form for human-facing labels and the decision-envelope
`component` field.

### KW-27 Doppel-Welle posture — Cross-Modul-Drift handled out-of-band

Identical posture to Welle-6: the KW-27 Doppel-Welle relies on the
regular Phase-2-Acceptance-Gate daily rollup (PR #160) which carries
the `cross-modul-subscribe-loop-recovery-workflow` axis. The Welle-6
+ Welle-7 workflows are therefore the standard 5-step pattern (no
inline cross-modul step). The Bundle-Auftrag (Tag-32) is explicit
about this asymmetry vs. the KW-26 Doppel-Welle (Welle-4 + Welle-5)
which **does** carry an inline cross-modul step.

Sibling artifacts:

* [`phase-3c-welle-6-runbook.md`](phase-3c-welle-6-runbook.md) —
  KW-27 Doppel-Welle partner runbook.
* [`phase-3c-welle-4-runbook.md`](phase-3c-welle-4-runbook.md) /
  [`welle-5`](phase-3c-welle-5-runbook.md) — KW-26 Doppel-Welle
  workflows which carry the inline cross-modul step.

## Trigger surface

```text
schedule:        Wed 06:00 UTC (= 08:00 CEST in May)
workflow_dispatch: target-binary-count, boots, score-band-floor
```

## Five-step decision flow

| Step | Substrate | Failure semantics |
|------|-----------|-------------------|
| 1. Trigger-gate aggregator | `scripts/phase-3c-trigger-gate-aggregator.py --json` | Exit 0 = green; exit 1 = yellow (Gate-4 tolerated); exit 2 = red |
| 2. Cutover-dry-run | `scripts/phase-3c-cutover-dry-run.py --component recovery --boots 12` | Exit non-zero fails the decision |
| 3. Test-persona-boot (rust) | `pytest test_rust_backend_switch.py -k recovery` with `WAKIR_RECOVERY_BACKEND=rust` | Pytest exit non-zero fails the decision |
| 4. Bridge-audit-roundtrip | `pytest test_bridge_audit_roundtrip_e2e.py` | Exit 0 OK; exit 5 tolerated |
| 5. Render cutover-acceptance-decision | Inline python | Writes `out/cutover-acceptance-decision.json`; job exits 0 iff `ready_for_live_smoke == true` |

### Decision policy (Step 5)

`ready_for_live_smoke == true` requires all four upstream steps
green, gate-status in {green, gate-4-yellow-tolerated}, band-floor
met. Identical to Welle-1/2/3/6.

## Artifact: `cutover-acceptance-decision-welle-7`

```text
cutover-acceptance-decision.json   # canonical decision envelope
trigger-gate-report.json
dry-run-envelope.json
persona-boot.log
persona-boot-junit.xml
bridge-audit.log
bridge-audit-junit.xml
```

### Decision envelope (welle-7 specific)

```json
{
  "schema": "wakir.phase-3c.welle-7-validation/1",
  "welle": 7,
  "component": "recovery_workflow",
  "component_short": "recovery",
  "env_var": "WAKIR_RECOVERY_BACKEND",
  "doppel_welle_partner": "subscribe_loop",
  "ready_for_live_smoke": true
}
```

## Operator walkthrough — wednesday morning (KW-27, last week)

1. Open the Welle-7 [Actions tab](https://github.com/wakir-labs/wakir-runtime/actions/workflows/phase-3c-welle-7-validation.yml)
   and find the most recent scheduled run.
2. Open the Welle-6 run in a second tab — both must be green for the
   KW-27 Mo Live-Smoke to proceed.
3. Cross-check the daily Phase-2-Acceptance-Gate rollup for the
   `cross-modul-subscribe-loop-recovery-workflow` axis.
4. If the verdict is `YES` on both Welle-6 and Welle-7 and the daily
   acceptance-gate cross-modul axis is green: proceed with the
   KW-27 Doppel-Welle cutover-PR planning per ADR-0066. After this
   cutover lands, Phase-3c is complete (`Python-Default zu Rust-
   Default` migration finished).

### Failure routing

| Failing step | Owner | First diagnostic |
|--------------|-------|------------------|
| 1 (trigger-gates RED) | Kai, Reza | `trigger-gate-report.json` |
| 2 (dry-run RED) | Selin (recovery resolver) | `dry-run-envelope.json` |
| 3 (persona-boot RED) | Selin | `persona-boot-junit.xml`; recovery test vectors live at rust_backend_switch test file starting line 209 (recovery_unset_defaults_to_python and onwards) |
| 4 (bridge-audit RED) | Selin | `bridge-audit.log` |

## Manual dispatch — ad-hoc readiness check

```bash
gh workflow run phase-3c-welle-7-validation.yml \
    -f target-binary-count=7 \
    -f boots=12 \
    -f score-band-floor=GREEN
```

## Bandwidth notes

* Wednesday-cron run completes in ~4-6 minutes on the GitHub-hosted
  runner. Identical bandwidth profile to Welle-1/2/6.

## Phase-3c-Ende — what happens after a green Welle-7

Once the Welle-7 cutover-PR lands (target ~2026-06-21 per ADR-0066),
all seven Phase-3c components carry `rust` as the production default.
The post-Phase-3c follow-ups are:

* Retire the `python` backend code-paths (separate roadmap item,
  ADR yet to draft).
* Promote the Phase-2-Acceptance-Gate cross-modul axes to required
  status checks (separate operator-hand-PR per
  `feedback_branch_protection_check_names.md`).
* Archive the seven `phase-3c-welle-*-validation.yml` workflows
  after the 8-week post-cutover observation window per ADR-0058.

## Drift sentinels

See [`test_phase_3c_welle_4_5_6_7_validation.py`](../../tests/workflows/test_phase_3c_welle_4_5_6_7_validation.py)
— the Bundle-test file pins the Welle-7 contract symmetrically with
Welle-6 plus the per-welle deltas (component_long, recovery short-
form, WAKIR_RECOVERY_BACKEND).

## Anchors

* ADR-0065 — Phase-3c Cutover-Plan.
* ADR-0066 — Phase-3c Acceleration Option-A+ (KW-27 Doppel-Welle).
* PR #160 — Phase-2-Acceptance-Gate daily rollup.
* `feedback_sandbox_host_trennung.md`.
* `feedback_branch_protection_check_names.md`.

— Tomás Reinhart (Matrix-Lead), Sprint-Tag-32 Mini-Welle, 2026-05-17.
