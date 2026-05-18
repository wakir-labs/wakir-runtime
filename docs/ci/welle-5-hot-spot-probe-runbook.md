# Welle-5 Hot-Spot Probe -- Runbook

**Status:** active (Tag-48, 2026-05-19)
**Owner:** Tomas (Dev-Engineering, Matrix-Lead)
**Spec source:** Henrik Tag-44 Pre-Mortem + Tag-45 Mitigation-Map
**Workflow:** `.github/workflows/phase-3c-welle-5-hot-spot-probe.yml`
**Aggregator:** `tooling/ci/welle_5_hot_spot_aggregator.py`
**Pattern source:** `docs/ci/welle-3-hot-spot-probe-runbook.md`

## 1. Why this probe exists

Henrik's Tag-44 + Tag-45 Pre-Mortem-Mitigation-Map identifies Welle-5
(`lifecycle_state_machine` / `persona-engine-fsm`) as a
**propagation-target Hot-Spot**: downstream from Welle-3 (audit-trail)
and Welle-4 (state-backing). The structural risk is
**FSM-Phantom-Detection live**:

* Henrik Tag-22 A2 finding identified the phantom-transition class
  (transition in canonical trace, no matching FSM edge in live engine).
* Static A2 coverage landed in Tag-22; the cutover-window introduces
  a *live-replay variant* that needs daily detection.
* A phantom in Welle-5 cascades into Welle-7 (recovery-workflow
  replays the FSM trace).

The Tag-30 weekly Welle-5-validation workflow tests static cutover-
readiness. This workflow is the **live-phantom-detection deep-dive**.

## 2. The four checks

### Check 1 -- Self-Reference-Trap-Pre-Detection

Patterns scanned in the FSM cutover-smoke + crate:
`replay_own_trace`, `read_fsm_trace_for_self`,
`self_referential_fsm_loop`, `fsm_self_oracle`.

### Check 2 -- FSM-Phantom-Detection live indicator

Read `state/welle-5-fsm-phantom-detection.json`. Schema:

```json
{
  "phantom_detection_status": "green|yellow|red",
  "phantom_transition_count": 0,
  "evaluated_at_utc": "2026-05-19T06:00:00Z"
}
```

**Propagation:** when both Check-2 and `phantom_detection_status` are
red, envelope includes `cross_welle_propagation` block listing
Welle-{7} as `pre_conditional_blocked`.

### Check 3 -- Independent-Oracle-Probe

Cross-validate FSM output against `doppelbetrieb-score-aggregator
--mode=cross-modul-stress`. Same asymmetric red-mapping.

### Check 4 -- IIA-1130-Pre-Auditor-Decision-Tracking

Verify `state/welle-5-pre-auditor-decision.json` (welle=5, decision
APPROVED). Same flow as Welle-3.

## 3. Aggregator decision rule

Truth-table matches Welle-3 contract:
* `CLEAR` -- all four green.
* `CAUTION` -- exactly one yellow, three green.
* `BLOCK` -- any red, OR two-or-more yellows.

## 4. Notify-events

Same emission rule as Welle-3: BLOCK every run, CAUTION transition
only.

## 5. Operating cadence

* **Daily 06:40 UTC cron** -- 5 min after the Welle-4 hot-spot probe.
* PR path-filter, manual dispatch -- same as Welle-3 pattern.

## 6. Pre-Auditor designation workflow

Same operator-hand flow as Welle-3.

## 7. Cross-substrate links

| Link | Path |
|---|---|
| Welle-5 weekly validation | `.github/workflows/phase-3c-welle-5-validation.yml` |
| FSM crate | `wirelang-rust/crates/persona-engine-fsm` |
| All-seven daily probe | `.github/workflows/phase-3c-pre-cutover-daily-probe.yml` |
| Independent-oracle script | `scripts/doppelbetrieb-score-aggregator.py` |
| Cutover-smoke (py) | `scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py` |
| Cutover-smoke (sh) | `scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.sh` |
| Henrik Pre-Mortem (Tag-44) | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-44-pre-mortem-done.md` |
| Henrik Mitigation-Map (Tag-45) | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-45-mitigation-map-done.md` |
| A2 phantom coverage (Tag-22 closeout) | persona-engine FSM tests |

## 8. Hermetic posture

stdlib-only python; no subprocess; no podman / cosign / live-VM /
network; hosted-runner-safe.

## 9. Sandbox-no-push discipline

ADR-0058 + AR-Direktive Tag-44 -- daily cron does NOT push to main.

## 10. Disable / re-tune

Edit `DOWNSTREAM_PROPAGATION_WELLEN` in
`tooling/ci/welle_5_hot_spot_aggregator.py` to re-tune the propagation
list; update test `test_downstream_propagation_wellen_constant`.

-- Tomas
