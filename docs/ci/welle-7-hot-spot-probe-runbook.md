# Welle-7 Hot-Spot Probe -- Runbook

**Status:** active (Tag-48, 2026-05-19)
**Owner:** Tomas (Dev-Engineering, Matrix-Lead)
**Spec source:** Henrik Tag-44 Pre-Mortem + Tag-45 Mitigation-Map +
  Tag-39 Welle-6+7-Pre-Audit-Bundle (IIA-1130 anchor)
**Workflow:** `.github/workflows/phase-3c-welle-7-hot-spot-probe.yml`
**Aggregator:** `tooling/ci/welle_7_hot_spot_aggregator.py`
**Pattern source:** `docs/ci/welle-3-hot-spot-probe-runbook.md`

## 1. Why this probe exists

Henrik's Tag-44 + Tag-45 Pre-Mortem-Mitigation-Map identifies Welle-7
(`recovery_workflow`) as the **terminal propagation-target Hot-Spot**:
the receiving end of propagation from Welle-3 / -4 / -5 / -6.
Welle-7 is also the ORIGINAL IIA-1130 case (Tag-39 Henrik-Bundle).

The structural risk has two dimensions:

1. **Recovery-Drill-Live**: live R1..R4 replay against production
   state-backing snapshots. The static R1..R4 hermetic suite landed
   in Tag-20+21; the cutover-window introduces a *live-drill* variant
   beyond the static one.

2. **IIA-1130 Pre-Auditor**: the audit-stream-contract author cannot
   self-certify the recovery story; an AR-designated external
   Pre-Auditor is mandatory.

## 2. The four checks

### Check 1 -- Self-Reference-Trap-Pre-Detection

Patterns: `replay_own_recovery_trace`, `read_recovery_emit_for_self`,
`self_referential_recovery_loop`, `recovery_self_oracle`. Scans both
`persona-engine-recovery` and `persona-engine-recovery-replay`
crates.

### Check 2 -- Recovery-Drill-Live indicator

Read `state/welle-7-recovery-drill-live.json`:

```json
{
  "recovery_drill_status": "green|yellow|red",
  "r1_pass": true, "r2_pass": true, "r3_pass": true, "r4_pass": true,
  "evaluated_at_utc": "2026-05-19T06:00:00Z"
}
```

**Propagation: none.** Welle-7 is the **terminal welle** -- no
downstream propagation. A red Check-2 blocks Welle-7 itself but
cascades nowhere else. The
`DOWNSTREAM_PROPAGATION_WELLEN` constant is empty for this
aggregator (schema symmetry with Welle-3 retained: the
`cross_welle_propagation` field is always `null`).

### Check 3 -- Independent-Oracle-Probe

Same pattern as Welle-3 -- cross-modul-stress aggregator does NOT
use recovery-workflow as oracle.

### Check 4 -- IIA-1130-Pre-Auditor-Decision-Tracking

Verify `state/welle-7-pre-auditor-decision.json` (welle=7, decision
APPROVED). Welle-7 is the ORIGINAL IIA-1130 case (Tag-39
Henrik-Bundle); until the AR designates the external Pre-Auditor,
this check is yellow (PENDING) by design.

## 3. Aggregator decision rule

Same truth-table as Welle-3:
* `CLEAR` -- all four green.
* `CAUTION` -- exactly one yellow.
* `BLOCK` -- any red, OR two-or-more yellows.

## 4. Notify-events

BLOCK every run, CAUTION transition only.

## 5. Operating cadence

* **Daily 06:50 UTC cron** -- 5 min after the Welle-6 hot-spot probe;
  last in the seven-welle daily-probe-cascade.

## 6. Pre-Auditor designation workflow

Same flow as Welle-3. Welle-7 was the first welle to need the
IIA-1130 external Pre-Auditor (Tag-39 Henrik-Bundle); the operator-
hand designation process is documented there.

## 7. Cross-substrate links

| Link | Path |
|---|---|
| Welle-7 weekly validation | `.github/workflows/phase-3c-welle-7-validation.yml` |
| Recovery crate | `wirelang-rust/crates/persona-engine-recovery` |
| Recovery-replay crate | `wirelang-rust/crates/persona-engine-recovery-replay` |
| All-seven daily probe | `.github/workflows/phase-3c-pre-cutover-daily-probe.yml` |
| Independent-oracle script | `scripts/doppelbetrieb-score-aggregator.py` |
| Cutover-smoke (py) | `scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.py` |
| Cutover-smoke (sh) | `scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.sh` |
| Henrik Pre-Mortem (Tag-44) | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-44-pre-mortem-done.md` |
| Henrik Mitigation-Map (Tag-45) | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-45-mitigation-map-done.md` |
| R1..R4 hermetic suite (Tag-20+21) | persona-engine recovery tests |

## 8. Hermetic posture

stdlib-only python; no live recovery-drill from this probe (the
upstream weekly-validation produces the state-file via its own
controlled R1..R4 replay step). Hosted-runner-safe.

## 9. Sandbox-no-push discipline

ADR-0058 + AR-Direktive Tag-44 -- daily cron does NOT push to main.

## 10. Disable / re-tune

`DOWNSTREAM_PROPAGATION_WELLEN` is intentionally empty here -- if a
future ADR adds a downstream-welle of recovery_workflow (unlikely
without a new welle being added), update this constant + the test
`test_terminal_welle_propagation_constant_empty` accordingly.

-- Tomas
