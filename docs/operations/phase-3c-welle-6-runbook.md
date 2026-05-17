# Phase-3c Welle-6 Validation Runbook — subscribe_loop

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine subscribe_loop resolver), Tomás Reinhart (Matrix-Lead) |
| ADRs | [0065](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md) (Cutover-Plan), [0066](../../decisions/0066-phase-3c-beschleunigung-option-a-plus.md) (Acceleration) |
| Workflow | [`.github/workflows/phase-3c-welle-6-validation.yml`](../../.github/workflows/phase-3c-welle-6-validation.yml) |
| Tests | [`tests/workflows/test_phase_3c_welle_4_5_6_7_validation.py`](../../tests/workflows/test_phase_3c_welle_4_5_6_7_validation.py) |
| Cadence | Wednesday 06:00 UTC (~08:00 CEST in May) + workflow_dispatch |
| Welle-6 component | `subscribe_loop` (KW 27, parallel to Welle-7) |
| Welle-6 env-var | `WAKIR_SUBSCRIBE_LOOP_BACKEND` (rust value: `rust`) |
| KW-27 Doppel-Welle partner | Welle-7 `recovery_workflow` |

## Purpose

This runbook explains the **Welle-6 Validation Workflow**, the wired-
substrate readiness check that the Phase-3c Welle-6 cutover decision
rests on. ADR-0065 + ADR-0066 (Acceleration Option-A+) demand a
Monday-morning Pilot-VM Live-Smoke before the Welle-6 cutover-PR flips
the production default of `WAKIR_SUBSCRIBE_LOOP_BACKEND` from `python`
to `rust`. The Live-Smoke is **operator-hand-territory**. This
workflow is the **hermetic readiness check** that runs three days
*before* the Monday smoke and emits the canonical
`cutover-acceptance-decision-welle-6` JSON envelope.

Welle-6 ships in parallel with Welle-7 (`recovery_workflow`) in
KW 27 — the KW-27 Doppel-Welle.

### KW-27 Doppel-Welle posture — Cross-Modul-Drift handled out-of-band

Unlike the KW-26 Doppel-Welle (Welle-4 + Welle-5) which inlines the
Cross-Modul-Stress-Test as a sixth step, the KW-27 Doppel-Welle
relies on the regular Phase-2-Acceptance-Gate daily rollup (PR #160)
which carries the `cross-modul-subscribe-loop-recovery-workflow`
axis. The Welle-6/7 workflows are therefore the standard 5-step
pattern (no inline cross-modul step). The Bundle-Auftrag (Tag-32) is
explicit about this asymmetry; the daily-acceptance-gate path is the
KW-27-equivalent mitigation surface.

If the KW-27 cross-modul axis ever needs **ad-hoc** verification
during a Welle-6/7 readiness investigation, run the aggregator
manually:

```bash
python scripts/doppelbetrieb-score-aggregator.py \
    --mode cross-modul-stress \
    --out /tmp/kw27-cross-modul.json
jq '.axes[] | select(.label=="cross-modul-subscribe-loop-recovery-workflow")' \
    /tmp/kw27-cross-modul.json
```

Sibling artifacts:

* [`phase-3c-welle-7-runbook.md`](phase-3c-welle-7-runbook.md) —
  KW-27 Doppel-Welle partner runbook.
* [`phase-3c-welle-4-runbook.md`](phase-3c-welle-4-runbook.md) —
  Welle-4 carries the inline cross-modul step; cross-reference to
  understand the asymmetry rationale.
* [`phase-3c-cutover-runbook.md`](phase-3c-cutover-runbook.md) —
  Dry-run usage walkthrough.

## Trigger surface

```text
schedule:        Wed 06:00 UTC (= 08:00 CEST in May)
workflow_dispatch: target-binary-count, boots, score-band-floor
```

## Five-step decision flow

| Step | Substrate | Failure semantics |
|------|-----------|-------------------|
| 1. Trigger-gate aggregator | `scripts/phase-3c-trigger-gate-aggregator.py --json` | Exit 0 = green; exit 1 = yellow (Gate-4 tolerated); exit 2 = red |
| 2. Cutover-dry-run | `scripts/phase-3c-cutover-dry-run.py --component subscribe_loop --boots 12` | Exit non-zero fails the decision |
| 3. Test-persona-boot (rust) | `pytest test_rust_backend_switch.py -k subscribe_loop` with `WAKIR_SUBSCRIBE_LOOP_BACKEND=rust` | Pytest exit non-zero fails the decision |
| 4. Bridge-audit-roundtrip | `pytest test_bridge_audit_roundtrip_e2e.py` | Exit 0 OK; exit 5 tolerated |
| 5. Render cutover-acceptance-decision | Inline python | Writes `out/cutover-acceptance-decision.json`; job exits 0 iff `ready_for_live_smoke == true` |

### Decision policy (Step 5)

`ready_for_live_smoke == true` requires all four upstream steps
green, gate-status in {green, gate-4-yellow-tolerated}, band-floor
met.

## Artifact: `cutover-acceptance-decision-welle-6`

```text
cutover-acceptance-decision.json   # canonical decision envelope
trigger-gate-report.json
dry-run-envelope.json
persona-boot.log
persona-boot-junit.xml
bridge-audit.log
bridge-audit-junit.xml
```

### Decision envelope (welle-6 specific)

```json
{
  "schema": "wakir.phase-3c.welle-6-validation/1",
  "welle": 6,
  "component": "subscribe_loop",
  "env_var": "WAKIR_SUBSCRIBE_LOOP_BACKEND",
  "doppel_welle_partner": "recovery_workflow",
  "ready_for_live_smoke": true
}
```

## Operator walkthrough — wednesday morning (KW-27)

1. Open the Welle-6 [Actions tab](https://github.com/wakir-labs/wakir-runtime/actions/workflows/phase-3c-welle-6-validation.yml)
   and find the most recent scheduled run.
2. Open the Welle-7 run in a second tab — both must be green for the
   KW-27 Mo Live-Smoke to proceed.
3. Cross-check the daily Phase-2-Acceptance-Gate rollup
   ([`phase-2-acceptance-gate.yml`](../../.github/workflows/phase-2-acceptance-gate.yml))
   for the `cross-modul-subscribe-loop-recovery-workflow` axis. A red
   axis there blocks the KW-27 Doppel-Welle independently of the two
   per-welle readiness reports.
4. If the verdict is `YES` on both Welle-6 and Welle-7 and the daily
   acceptance-gate cross-modul axis is green: proceed with the
   KW-27 Doppel-Welle cutover-PR planning per ADR-0066.

### Failure routing

| Failing step | Owner | First diagnostic |
|--------------|-------|------------------|
| 1 (trigger-gates RED) | Kai, Reza | `trigger-gate-report.json` |
| 2 (dry-run RED) | Selin (subscribe_loop resolver) | `dry-run-envelope.json` |
| 3 (persona-boot RED) | Selin | `persona-boot-junit.xml`; subscribe_loop test vectors live at rust_backend_switch test file lines ~2364-2750 |
| 4 (bridge-audit RED) | Selin | `bridge-audit.log` |

## Manual dispatch — ad-hoc readiness check

```bash
gh workflow run phase-3c-welle-6-validation.yml \
    -f target-binary-count=7 \
    -f boots=12 \
    -f score-band-floor=GREEN
```

## Bandwidth notes

* Wednesday-cron run completes in ~4-6 minutes on the GitHub-hosted
  runner. Identical bandwidth profile to Welle-1/2 (no cross-modul
  step added).

## Drift sentinels

See [`test_phase_3c_welle_4_5_6_7_validation.py`](../../tests/workflows/test_phase_3c_welle_4_5_6_7_validation.py)
— the Bundle-test file asserts that Welle-6 (and Welle-7) do **not**
carry the cross-modul-stress step (`test_cross_modul_stress_step_
only_on_welle_4_and_5`). The asymmetry between KW-26 (inline cross-
modul) and KW-27 (out-of-band via daily acceptance-gate) is therefore
pinned.

## Anchors

* ADR-0065 — Phase-3c Cutover-Plan.
* ADR-0066 — Phase-3c Acceleration Option-A+ (KW-27 Doppel-Welle).
* PR #160 — Phase-2-Acceptance-Gate daily rollup.
* `feedback_sandbox_host_trennung.md`.
* `feedback_branch_protection_check_names.md`.

— Tomás Reinhart (Matrix-Lead), Sprint-Tag-32 Mini-Welle, 2026-05-17.
