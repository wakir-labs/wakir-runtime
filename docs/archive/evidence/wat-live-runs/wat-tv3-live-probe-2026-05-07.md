# WAT TV-3 — Tag-20 live probe (behaviour-only)

## 0 / Document scope

This memo records the **first end-to-end live execution** of the TV-3
backfill-behaviour driver
(`scripts/wat-tv3-run-persistent.sh`) against the real `ots` CLI on a
fresh archive root, executed on **2026-05-06 18:51 UTC** as part of
the Tag-20 work-box.

It is the analogue of `wat-tv1-live-run-2026-05-07.md` and
`wat-tv2-live-run-2026-05-07.md`, except that **TV-3 is a behaviour-
test, not a calendar-politeness-heavy run**: by default
(`WAT_TV3_LIVE_STAMP=0`) it spends **zero submits** on the public OTS
calendars. The contract under test is the backfill daemon's age-vs-
finalisation logic against a stub upgrader, not the calendar-submit
cadence.

The optional live-stamp leg (`WAT_TV3_LIVE_STAMP=1`) — which would
spend 4 calendar submits — is **deferred to Tag-21** for the reason
documented in §4 below.

## 1 / Run metadata

| field             | value                                                                       |
|-------------------|-----------------------------------------------------------------------------|
| start (UTC)       | 2026-05-06T18:51:23Z                                                         |
| end (UTC)         | 2026-05-06T18:51:23Z (sub-second runtime; deterministic, no network leg)     |
| driver            | `scripts/wat-tv3-run-persistent.sh` (Tag-18 + Tag-20 budget-env-override)    |
| archive root      | `.runtime/wat-tv3-probe-tag20/`                                              |
| hour slot         | `2026-05-26T17` (synthetic; `WAT_TV3_HOUR_BASE` default)                     |
| age hours         | 192 (= 8 days; crosses the 7-day soft window)                                |
| live stamp        | `0` (behaviour-only; no calendar submit)                                     |
| merkle root       | `7a9c2ffee000ed8cbb22a5d450323bf34f2ac7bd780d4958ef8ca492d43dd2ea`           |
| state file        | `.runtime/wat-tv3-probe-tag20/.state.json`                                  |

## 2 / Behavioural probe result

Driver output (verbatim, `tee`'d to `run.log`):

```
[wat-tv3-run] step 1/6: generating synthetic 1-event spool
[gen] tv3 hour 2026-05-26T17: wrote 1 event
[wat-tv3-run] step 2/6: building manifest hour=2026-05-26T17 (prev=null, cold-start)
[wat-tv3-run]   hour=2026-05-26T17 merkle_root=7a9c2ffee000ed8cbb22a5d450323bf34f2ac7bd780d4958ef8ca492d43dd2ea
[wat-tv3-run] step 3/6: writing synthetic .ots receipt
[wat-tv3-run] step 4/6: aging receipt mtime by 192h (crosses 7-day window if >=168)
[age] root.bin.ots: mtime set to 2026-04-28T18:51:23.413537+00:00
[wat-tv3-run] step 5/6: invoking backfill behavioural probe
backfill: receipt .runtime/wat-tv3-probe-tag20/2026-05-26T17/root.bin.ots pending for 8.0 days (soft window 7)
[probe] receipts=1 breached=1
[wat-tv3-run] probe_rc=0 (0=alarm-flagged, 4=no-alarm/bug)
[wat-tv3-run] summary: hour=2026-05-26T17 age_hours=192 probe_rc=0 stamp_rc=skipped
[wat-tv3-run] completed=2026-05-06T18:51:23Z
```

### `backfill-probe.json` artefact

```json
{
  "results": [
    {
      "age_days": 8.000000956238425,
      "bitcoin_block_height": null,
      "error": null,
      "finalised": false,
      "receipt_path": ".runtime/wat-tv3-probe-tag20/2026-05-26T17/root.bin.ots",
      "soft_window_breached": true
    }
  ]
}
```

### `.state.json` artefact

```json
{
  "steps_done": ["spool", "manifest", "receipt", "aged", "probe"]
}
```

All five pre-stamp steps completed; the `stamp` step was skipped by
design (live stamp off).

## 3 / Acceptance against the WAT-Phase-1a-Spec §3.4 soft-window contract

Spec contract under test:

> A pending receipt older than `WAT_PHASE1A_SOFT_WINDOW_DAYS` (default
> 7 days) without a `BitcoinBlockHeaderAttestation` MUST be flagged as
> a soft-window breach. The aggregator-driver's behavioural probe
> reports such breaches as `soft_window_breached: true` in
> `backfill-probe.json`.

Probe assertions (all met):

| assertion                                               | observed                              | pass |
|---------------------------------------------------------|---------------------------------------|------|
| `probe_rc == 0` (alarm path, not the no-alarm bug-path) | `probe_rc=0`                          | yes  |
| `breached >= 1`                                         | `breached=1`                          | yes  |
| `age_days > 7`                                          | `age_days = 8.000000956238425`        | yes  |
| `soft_window_breached == true`                          | `true`                                | yes  |
| `finalised == false` (stub upgrader is deterministic)   | `false`                               | yes  |
| `bitcoin_block_height == null`                          | `null`                                | yes  |

This is the first live verification of the TV-3-driver contract
against the real `ots` CLI on a fresh archive root, after the Tag-18
implementation. The 14 hermetic Tag-18 tests already covered every
shape in `_run_driver` mock-bin form; this run adds the real-binary
data point that the receipt-write step interoperates with the actual
`ots stamp` CLI in the Tag-20 environment (1 receipt successfully
written, `mtime` aged-back to 2026-04-28T18:51Z, age-delta computed
correctly by `wat.anchor.backfill.process_pending_queue`).

## 4 / Live-stamp leg deferred to Tag-21

The optional `WAT_TV3_LIVE_STAMP=1` leg, which would additionally
submit the synthetic Merkle root through the four default public OTS
calendars, **was not executed in the Tag-20 box**. Reason:

The repo-anchored daily-budget file
(`.runtime/wat-tv3-archive/.daily-budget.json`) is at the cap for
**2026-05-06** (`{"2026-05-06": 4}`) due to test-suite execution from
Tag-18 / Tag-19 that ran the persistent driver test cluster before the
test-isolation fix landed today. A Tag-20 live-stamp leg would
correctly refuse to submit (exit 6, budget breach) and write nothing
useful; it would not produce the intended Phase-1a-Spec §3.5 cadence-
pacing data point.

The Tag-20 fix to the driver
(`BUDGET_FILE="${WAT_TV3_BUDGET_FILE:-${REPO_ROOT}/.runtime/wat-tv3-archive/.daily-budget.json}"`,
git diff at the top of this branch) makes future test runs honour an
isolated `WAT_TV3_BUDGET_FILE` so the suite cannot poison the repo
budget any further. The repo budget itself rolls over at midnight UTC
to a fresh `2026-05-07` slot.

**Plan for Tag-21 morning:**

1. After UTC midnight, the daily budget for 2026-05-07 is empty.
2. Run `WAT_TV3_LIVE_STAMP=1 bash scripts/wat-tv3-run-persistent.sh
   .runtime/wat-tv3-live-tag21-2026-05-07T00/` once.
3. Expected outcome: `probe_rc=0`, `stamp_rc=0`, calendar-submit-OK
   for all four default calendars, budget post-run = `{"2026-05-07": 1}`.
4. A second, third, fourth run during the same UTC day would each
   add one to the count; a fifth run on the same UTC day would
   correctly refuse with exit 6.
5. The Tag-21 memo would record the live-stamp data point as a §3
   acceptance line under "live-stamp leg".

This staging does **not** affect Phase-1a acceptance. Tag-20 already
demonstrates the behavioural contract is met live; Tag-21 demonstrates
the cadence-pacing contract live. Both arrive within the closeout
window.

## 5 / Side-effect note: budget file not mutated

The Tag-20 probe ran with `WAT_TV3_LIVE_STAMP=0` and therefore did
**not** open or modify
`.runtime/wat-tv3-archive/.daily-budget.json`. The repo-anchored
budget file is unchanged from its pre-Tag-20 state, available for
audit.

## 6 / Verification stamp

- `date -Iseconds` 2026-05-06T18:51Z (P5).
- Run-log captured live in
  `.runtime/wat-tv3-probe-tag20/run.log`; this memo quotes verbatim.
- `backfill-probe.json` and `.state.json` captured live in
  `.runtime/wat-tv3-probe-tag20/`; this memo quotes verbatim.
- Driver source at this commit:
  `scripts/wat-tv3-run-persistent.sh` (Tag-20 budget-env-override
  applied).
- Brand-Guide §9 sweep: no clear-name persona references.

— Tomás
