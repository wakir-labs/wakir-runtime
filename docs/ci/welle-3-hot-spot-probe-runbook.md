# Welle-3 Hot-Spot Probe -- Runbook

**Status:** active (Tag-45, 2026-05-18)
**Owner:** Tomas (Dev-Engineering, Matrix-Lead)
**Spec source:** Henrik Tag-44 Pre-Mortem (`agents-workspaces/mira/inbox/2026-05-18-henrik-tag-44-pre-mortem-done.md`),
  Henrik Tag-39 Welle-6+7-Pre-Audit-Bundle (IIA-1130 anchor)
**Workflow:** `.github/workflows/phase-3c-welle-3-hot-spot-probe.yml`
**Aggregator:** `tooling/ci/welle_3_hot_spot_aggregator.py`

## 1. Why this probe exists

Henrik's Tag-44 Pre-Mortem identifies Welle-3 (`bridge_audit_writer`
in its role as audit-stream-emitting oracle) as the #1 Cross-Welle
Hot-Spot in the pre-cutover marathon window (2026-05-19 ->
2026-06-07). The hot-spot is structural, not transient:

* The Welle-3 component **is** the substrate behind the canonical
  cross-lang bridge-audit oracle. Asking it to certify its own
  cutover is a self-reference trap.
* Welle-3 audit-trail-integrity propagates **downstream** into
  Welle-4 (`state_backing`), Welle-5 (`lifecycle_state_machine`),
  and Welle-7 (`recovery_workflow`). A red Welle-3 must
  pre-conditionally block the readiness of those three Wellen.
* The worst-case cascade Henrik flagged begins with the trio
  **A5 + B3 + A1** triggered inside Welle-3 (audit-loop +
  audit-trail-integrity drift + Pre-Auditor gap).

The Tag-30 weekly Welle-3-validation workflow
(`phase-3c-welle-3-validation.yml`) tests cutover-readiness once a
week. The Tag-44 all-seven daily probe
(`phase-3c-pre-cutover-daily-probe.yml`) tracks trend across all
seven Wellen. Neither of those drills into the four Welle-3-specific
hot-spot indicators below; this workflow does.

## 2. The four checks

### Check 1 -- Self-Reference-Trap-Pre-Detection

**Question:** Does the welle-3 cutover-window code consume its own
emitted audit-stream as input, opening a self-referencing audit-loop?

**How:** grep the welle-3 cutover-smoke scripts
(`scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.{py,sh}`)
and the persona-engine-bridge-audit-writer crate
(`wirelang-rust/crates/persona-engine-bridge-audit-writer/src`) for
the self-loop-signature patterns:

| Pattern | Meaning |
|---|---|
| `replay_own_emit` | Sentinel: writer reads its own output |
| `read_audit_stream_for_self` | Read-path against own writer-output |
| `self_referential_audit_loop` | Named anti-pattern |
| `audit_self_oracle` | Writer signs off on its own correctness |

**Tri-state:**
* `green` -- no patterns found in live code.
* `yellow` -- live code clean but cutover-window TODO/FIXME present.
* `red` -- one or more self-loop patterns found in live code.

### Check 2 -- Cross-Welle-Propagation-Risk-Indikator

**Question:** What is the last-known Welle-3 audit-trail-integrity
state, and does it propagate downstream?

**How:** read `state/welle-3-audit-trail-integrity.json`
(produced by the weekly Welle-3-validation workflow). The expected
schema is:

```json
{
  "audit_trail_integrity": "green|yellow|red",
  "evaluated_at_utc": "2026-05-18T06:00:00Z",
  "source_workflow_run_id": "12345678901"
}
```

**Tri-state:**
* `green` -- file present, `audit_trail_integrity == "green"`.
* `yellow` -- file present but `yellow`, OR file missing
  (PENDING-FIRST-RUN; Welle-3-validation hasn't produced state yet).
* `red` -- file present and `audit_trail_integrity == "red"`.

**Propagation:** when Check-2 is `red` AND the underlying
`audit_trail_integrity` is `red`, the aggregator's verdict envelope
includes:

```json
"cross_welle_propagation": {
  "trigger": "welle-3-audit-trail-integrity-red",
  "pre_conditional_blocked": [4, 5, 7],
  "rationale": "..."
}
```

Downstream Welle-{4,5,7} validation workflows should consume this
flag and refuse to mark themselves READY while it fires.

### Check 3 -- Independent-Oracle-Probe

**Question:** Does an oracle structurally independent of
`bridge_audit_writer` agree with the Welle-3 verdict?

**How:** run `scripts/doppelbetrieb-score-aggregator.py
--mode=cross-modul-stress`. Its three axes
(`cross-lang-pin-coverage`, `cross-modul-fixture-stability`,
`cross-modul-rollup-integrity`) do NOT use `bridge_audit_writer`
as oracle, so they provide a structurally-independent signal.

Compare the independent-oracle result against
`state/welle-3-validation-last-verdict.json`:

| Independent | Welle-3 | Verdict |
|---|---|---|
| pass | READY/PROCEED/GREEN | green |
| pass | not-ready | red (mis-attribution: welle-3 wrong) |
| fail | READY/PROCEED/GREEN | red (mis-attribution: welle-3 wrong) |
| fail | not-ready | green (oracles agree) |
| missing either | n/a | yellow |

The asymmetric red mapping captures the **mis-attribution risk**:
if the two oracles disagree, the welle-3 oracle is the suspect
because it has the structural conflict-of-interest.

### Check 4 -- IIA-1130-Pre-Auditor-Decision-Tracking

**Question:** Has the AR-designated external Pre-Auditor signed off
on Welle-3 per IIA-1130?

**How:** verify `state/welle-3-pre-auditor-decision.json` exists,
parses, has required fields, and the decision is APPROVED.

Expected schema (analog to the Welle-7 pattern from Tag-39):

```json
{
  "welle": 3,
  "auditor_role": "external-pre-auditor",
  "auditor_designation_source": "AR-Hand-Entscheidung",
  "decision": "APPROVED|PENDING|REJECTED",
  "decided_at_utc": "2026-06-15T10:00:00Z",
  "rationale": "..."
}
```

**Tri-state:**
* `green` -- file present, decision APPROVED, schema valid.
* `yellow` -- file missing (PENDING-AR-DESIGNATION; expected before
  KW-25 Welle-3 cutover-window opens), OR decision PENDING.
* `red` -- decision REJECTED, OR file present but schema invalid /
  wrong welle / unknown decision value.

## 3. Aggregator decision rule

Truth-table over the four tri-state inputs:

* `CLEAR` -- all four green.
* `CAUTION` -- exactly one yellow, three green. No reds.
* `BLOCK` -- any red, OR two-or-more yellows.

Empty / missing env-vars default to `red` (loud-failure mode -- we
assume the upstream check job did not run at all).

## 4. Notify-events

The aggregator appends one JSON-line event into
`state/notify-events.jsonl` when:

* verdict is `BLOCK` (every run -- forensic trail).
* verdict is `CAUTION` AND previous verdict was not `CAUTION`
  (transition only -- prevents spam on stable yellow).

Operator-hand-Sichtung consumes the feed; no external notify
(ntfy.sh / email) is wired here -- the feed is the artifact.

## 5. Operating cadence

* **Daily 06:30 UTC cron** -- automatic. 30 min after the Reza
  Tag-44 all-seven daily probe (06:00 UTC) so an operator looking
  at the daily Mira-Hand-Sichtung sees the all-seven trend first,
  then the Welle-3 hot-spot deep-dive.
* **PR path-filter** -- any PR touching the substrate
  (aggregator, workflow, smoke-scripts, doppelbetrieb-aggregator,
  audit-trail-integrity state file) re-runs the probe in dry-run.
* **Manual dispatch** -- operator can invoke via the GitHub Actions
  UI with `today` override (back-fill) or `persist=true` (stage
  state for commit; actual push is operator-hand).

## 6. Pre-Auditor designation workflow

The file `state/welle-3-pre-auditor-decision.json` is produced by
operator-hand once the AR designates the external Pre-Auditor:

1. AR-Hand-Entscheidung names the external Pre-Auditor (per
   Henrik Tag-44 Pre-Mortem §AR-Hand-Entscheidung).
2. Pre-Auditor reviews Welle-3 cutover-readiness substrate.
3. Pre-Auditor produces a signed decision file (initially PENDING
   while review in progress).
4. On sign-off (APPROVED or REJECTED), Pre-Auditor or operator
   commits the file to the repo via a Mira-Hand-PR.
5. This workflow's Check-4 picks up the new state on the next run.

Until step 4 lands, Check-4 reports `yellow` (PENDING-AR-DESIGNATION).
That's the expected steady state for the marathon window until
KW-25 approaches.

## 7. Cross-substrate links

| Link | Path |
|---|---|
| Welle-3 weekly validation | `.github/workflows/phase-3c-welle-3-validation.yml` |
| Welle-3 bridge-audit-writer runbook | `docs/phase-3c/welle-3-bridge-audit-writer-runbook.md` |
| All-seven daily probe | `.github/workflows/phase-3c-pre-cutover-daily-probe.yml` |
| Independent-oracle script | `scripts/doppelbetrieb-score-aggregator.py` |
| Cutover-smoke (py) | `scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py` |
| Cutover-smoke (sh) | `scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.sh` |
| Henrik Pre-Mortem (Tag-44) | `agents-workspaces/mira/inbox/2026-05-18-henrik-tag-44-pre-mortem-done.md` |
| Henrik Welle-6+7-Pre-Audit-Bundle (Tag-39 IIA-1130) | (per audit-spec) |

## 8. Hermetic posture

* stdlib-only Python in the aggregator. No third-party deps.
* No subprocess from inside the aggregator; the four checks run in
  separate workflow jobs and pipe their tri-state via env-vars.
* No podman, no live-VM, no cosign, no SSH from within the workflow.
* No network egress.
* Hosted-runner-safe (Ubuntu-latest, Python 3.13).

## 9. Sandbox-no-push discipline

Per ADR-0058 + AR-Direktive Tag-44, the daily cron does NOT push to
main. Daily envelopes are uploaded as artifacts (retention 30 days).
Operator-hand `workflow_dispatch` with `persist=true` stages the
state file but does not push (runner has `contents: read` only).
Actual commits are operator-hand via a separate Mira-Hand-PR.

## 10. Disable / re-tune

To temporarily silence Check-4 yellow (e.g. if the AR-Hand-Entscheidung
is intentionally deferred past KW-25), set
`state/welle-3-pre-auditor-decision.json` to a `PENDING` decision
with `auditor_designation_source = "deferred-by-AR"` and a
`deferred_until_utc` field. This keeps Check-4 yellow but documents
the deferral; the CAUTION verdict signal stays visible.

To re-tune the propagation list (e.g. if a future ADR redraws the
welle-dependency graph), edit `DOWNSTREAM_PROPAGATION_WELLEN` in
`tooling/ci/welle_3_hot_spot_aggregator.py` and update the test
suite's `test_propagation_block_*` cases.

-- Tomas
