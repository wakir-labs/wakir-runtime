# Welle-4 Hot-Spot Probe -- Runbook

**Status:** active (Tag-48, 2026-05-19)
**Owner:** Tomas (Dev-Engineering, Matrix-Lead)
**Spec source:** Henrik Tag-44 Pre-Mortem + Tag-45 Mitigation-Map
  (`agents-workspaces/mira/inbox/2026-05-18-henrik-tag-44-pre-mortem-done.md`,
  `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-45-mitigation-map-done.md`)
**Workflow:** `.github/workflows/phase-3c-welle-4-hot-spot-probe.yml`
**Aggregator:** `tooling/ci/welle_4_hot_spot_aggregator.py`
**Pattern source:** `docs/ci/welle-3-hot-spot-probe-runbook.md`

## 1. Why this probe exists

Henrik's Tag-44 + Tag-45 Pre-Mortem-Mitigation-Map identifies Welle-4
(`state_backing`) as the **#2 Cross-Welle Hot-Spot** for the
KW-25..KW-27 cutover marathon. The structural risk is
**state_backing Persistence-Drift**:

* The state_backing crate is the substrate behind the durable-state
  contract of every other welle. A silent persistence-drift cascades
  into Welle-5 (FSM durable state) and Welle-7 (recovery-replay).
* The drift can be subtle: serialiser-format-skew, snapshot-replay-
  divergence, fsync-ordering-regression.

The Tag-30 weekly Welle-4-validation workflow
(`phase-3c-welle-4-validation.yml`) tests cutover-readiness once a
week. This workflow is the **Welle-4-deep-dive companion**:
daily-cadence, drilling into the four Welle-4-specific hot-spot
indicators.

## 2. The four checks

### Check 1 -- Self-Reference-Trap-Pre-Detection

**Question:** Does the welle-4 cutover-window code consume its own
emitted state-snapshot as input, opening a self-referencing
persistence-loop?

**How:** grep
`scripts/phase-3c/welle-4-state-backing-cutover-smoke.{py,sh}` and
the `persona-engine-state-backing` crate for the self-loop-signature
patterns:

| Pattern | Meaning |
|---|---|
| `replay_own_snapshot` | Sentinel: writer reads its own output |
| `read_state_snapshot_for_self` | Read-path against own writer-output |
| `self_referential_persistence_loop` | Named anti-pattern |
| `state_backing_self_oracle` | Writer signs off on its own state |

**Tri-state:**
* `green` -- no patterns found in live code.
* `yellow` -- live code clean but cutover-window TODO/FIXME present.
* `red` -- one or more self-loop patterns found.

### Check 2 -- state_backing-Persistence-Drift indicator

**Question:** What is the last-known welle-4 persistence-drift state?

**How:** read `state/welle-4-persistence-drift.json`. Schema:

```json
{
  "persistence_drift": "green|yellow|red",
  "evaluated_at_utc": "2026-05-19T06:00:00Z",
  "source_workflow_run_id": "12345678901"
}
```

**Tri-state:**
* `green` -- file present, `persistence_drift == "green"`.
* `yellow` -- file present but `yellow`, OR file missing.
* `red` -- file present and `persistence_drift == "red"`.

**Propagation:** when both Check-2 and the underlying
`persistence_drift` are red, the verdict envelope includes:

```json
"cross_welle_propagation": {
  "trigger": "welle-4-persistence-drift-red",
  "pre_conditional_blocked": [5, 7],
  "rationale": "..."
}
```

Welle-{5, 7} downstream-validation workflows should consume this flag
and refuse to mark themselves READY while it fires.

### Check 3 -- Independent-Oracle-Probe

**Question:** Does an oracle structurally independent of state_backing
agree with the Welle-4 verdict?

**How:** run `scripts/doppelbetrieb-score-aggregator.py
--mode=cross-modul-stress`. Its three axes
(`cross-lang-pin-coverage`, `cross-modul-fixture-stability`,
`cross-modul-rollup-integrity`) do NOT use `state_backing` as oracle.
Compare against `state/welle-4-validation-last-verdict.json`. Same
asymmetric red-mapping as the Welle-3 pattern.

### Check 4 -- IIA-1130-Pre-Auditor-Decision-Tracking

**Question:** Has the AR-designated external Pre-Auditor signed off
on Welle-4 per IIA-1130?

**How:** verify `state/welle-4-pre-auditor-decision.json` exists,
parses, has required fields, and decision is APPROVED. Schema mirrors
the Welle-3 case (auditor_role, decision, decided_at_utc, welle=4).

**Tri-state:** green = APPROVED, yellow = PENDING / missing,
red = REJECTED / schema-invalid.

## 3. Aggregator decision rule

Truth-table over the four tri-state inputs (matches Welle-3 contract):

* `CLEAR` -- all four green.
* `CAUTION` -- exactly one yellow, three green. No reds.
* `BLOCK` -- any red, OR two-or-more yellows.

Empty / missing env-vars default to `red`.

## 4. Notify-events

Same emission rule as Welle-3:
* `BLOCK` -- every run (forensic trail).
* `CAUTION` -- transition only (prev != CAUTION).

## 5. Operating cadence

* **Daily 06:35 UTC cron** -- 5 min after the Welle-3 hot-spot probe.
* **PR path-filter** -- any PR touching aggregator / workflow / smoke
  / state-files re-runs the probe in dry-run.
* **Manual dispatch** -- operator can invoke with `today` override
  or `persist=true`.

## 6. Pre-Auditor designation workflow

Same operator-hand flow as Welle-3: AR designates external
Pre-Auditor, Pre-Auditor reviews substrate, produces signed decision
file, operator-hand-commits via Mira-Hand-PR.

## 7. Cross-substrate links

| Link | Path |
|---|---|
| Welle-4 weekly validation | `.github/workflows/phase-3c-welle-4-validation.yml` |
| state_backing crate | `wirelang-rust/crates/persona-engine-state-backing` |
| All-seven daily probe | `.github/workflows/phase-3c-pre-cutover-daily-probe.yml` |
| Independent-oracle script | `scripts/doppelbetrieb-score-aggregator.py` |
| Cutover-smoke (py) | `scripts/phase-3c/welle-4-state-backing-cutover-smoke.py` |
| Cutover-smoke (sh) | `scripts/phase-3c/welle-4-state-backing-cutover-smoke.sh` |
| Henrik Pre-Mortem (Tag-44) | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-44-pre-mortem-done.md` |
| Henrik Mitigation-Map (Tag-45) | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-45-mitigation-map-done.md` |

## 8. Hermetic posture

stdlib-only python in the aggregator; no subprocess from inside; no
podman / cosign / live-VM / SSH / network egress; hosted-runner-safe.

## 9. Sandbox-no-push discipline

Per ADR-0058 + AR-Direktive Tag-44 the daily cron does NOT push to
main. Artifacts uploaded, retention 30 days. Operator-hand `persist`
dispatch stages only; actual push is operator-hand.

## 10. Disable / re-tune

To re-tune the propagation list (e.g. future ADR redraws the
welle-dependency graph), edit `DOWNSTREAM_PROPAGATION_WELLEN` in
`tooling/ci/welle_4_hot_spot_aggregator.py` and update
`tests/ci/test_welle_4_hot_spot_probe.py::test_downstream_propagation_wellen_constant`.

-- Tomas
