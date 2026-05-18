# Welle-6 Hot-Spot Probe -- Runbook

**Status:** active (Tag-48, 2026-05-19)
**Owner:** Tomas (Dev-Engineering, Matrix-Lead)
**Spec source:** Henrik Tag-44 Pre-Mortem + Tag-45 Mitigation-Map
**Workflow:** `.github/workflows/phase-3c-welle-6-hot-spot-probe.yml`
**Aggregator:** `tooling/ci/welle_6_hot_spot_aggregator.py`
**Pattern source:** `docs/ci/welle-3-hot-spot-probe-runbook.md`

## 1. Why this probe exists

Henrik's Tag-44 + Tag-45 Pre-Mortem-Mitigation-Map identifies Welle-6
(`subscribe_loop` / `persona-engine-subscribe-loop`) as a
**propagation-target Hot-Spot**. The structural risk is
**NATS-Subscribe-Mode-Live-Check**:

* Henrik Tag-46 A8 finding (NATS-JetStream-Loss-Recovery) identified
  subscribe-mode mismatches as a silent message-loss class.
* Static A8 coverage landed Tag-46; the cutover-window introduces a
  *live-mode-verification* variant probing the production
  JetStream-cluster state.
* A subscribe-mode mismatch in Welle-6 cascades into Welle-7
  (recovery-replay-divergence).

## 2. The four checks

### Check 1 -- Self-Reference-Trap-Pre-Detection

Patterns: `replay_own_consumed`, `read_subscribe_emit_for_self`,
`self_referential_subscribe_loop`, `subscribe_self_oracle`.

### Check 2 -- NATS-Subscribe-Mode-Live-Check indicator

Read `state/welle-6-subscribe-mode-live.json`:

```json
{
  "subscribe_mode_status": "green|yellow|red",
  "consumer_durable_name": "...",
  "ack_policy": "explicit|all|none",
  "evaluated_at_utc": "2026-05-19T06:00:00Z"
}
```

**Propagation:** when both Check-2 and `subscribe_mode_status` are
red, envelope includes Welle-{7} in `pre_conditional_blocked`.

### Check 3 -- Independent-Oracle-Probe

Same pattern as Welle-3 -- cross-modul-stress aggregator does NOT
use NATS subscribe-loop as oracle.

### Check 4 -- IIA-1130-Pre-Auditor-Decision-Tracking

Verify `state/welle-6-pre-auditor-decision.json` (welle=6, decision
APPROVED). Welle-6 is on Henrik's IIA-1130 list because the NATS
substrate has the same self-audit-conflict pattern as Welle-3.

## 3. Aggregator decision rule

Same truth-table as Welle-3.

## 4. Notify-events

BLOCK every run, CAUTION transition only.

## 5. Operating cadence

* **Daily 06:45 UTC cron** -- 5 min after the Welle-5 hot-spot probe.

## 6. Pre-Auditor designation workflow

Same flow as Welle-3.

## 7. Cross-substrate links

| Link | Path |
|---|---|
| Welle-6 weekly validation | `.github/workflows/phase-3c-welle-6-validation.yml` |
| subscribe_loop crate | `wirelang-rust/crates/persona-engine-subscribe-loop` |
| All-seven daily probe | `.github/workflows/phase-3c-pre-cutover-daily-probe.yml` |
| Independent-oracle script | `scripts/doppelbetrieb-score-aggregator.py` |
| Cutover-smoke (py) | `scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py` |
| Cutover-smoke (sh) | `scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.sh` |
| Henrik Pre-Mortem (Tag-44) | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-44-pre-mortem-done.md` |
| Henrik Mitigation-Map (Tag-45) | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-45-mitigation-map-done.md` |
| A8 NATS-JetStream-Loss-Recovery (Tag-46) | persona-engine NATS tests |

## 8. Hermetic posture

stdlib-only python; no live NATS connection from this probe (the
upstream weekly-validation produces the state-file). Hosted-runner-
safe.

## 9. Sandbox-no-push discipline

ADR-0058 + AR-Direktive Tag-44 -- daily cron does NOT push to main.

## 10. Disable / re-tune

Edit `DOWNSTREAM_PROPAGATION_WELLEN` in
`tooling/ci/welle_6_hot_spot_aggregator.py`.

-- Tomas
