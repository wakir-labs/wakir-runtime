<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# WAT TV-3 — Tag-22 Live-Stamp Happy-Path (rc=0)

## 0 / Document scope

This memo records the **third** end-to-end live execution of the TV-3
backfill-behaviour driver, with `WAT_TV3_LIVE_STAMP=1`, on
**2026-05-07 06:43 UTC** (Tag-22 box).

It is the planned follow-up to `wat-tv3-live-stamp-2026-05-07.md`
(Tag-21, Section 5). Tag-21 verified the cadence-pacing branch live
(exit-6 refusal on a budget-saturated UTC day). Tag-22 closes the
spec acceptance pair by exercising the **rc=0 happy-path** on the
fresh UTC day `2026-05-07` (UTC midnight rolled at 02:00 CEST,
~4 h 43 min before box start).

This is the first wholly-driver-emitted live Bitcoin-calendar
submit in the Sprint-1 dataset (TV-1 / TV-2 calendar submits were
direct `ots stamp` invocations on hand-rolled receipts; the TV-3
driver wraps generate → manifest → receipt → age → probe → stamp
in one persistent harness).

## 1 / Run metadata

| field           | value                                                                       |
|-----------------|-----------------------------------------------------------------------------|
| start (UTC)     | 2026-05-07T06:43:04Z                                                        |
| end (UTC)       | 2026-05-07T06:43:06Z                                                        |
| driver          | `scripts/wat-tv3-run-persistent.sh` (Tag-18 + Tag-20 budget-env-override)   |
| archive root    | `.runtime/wat-tv3-live-tag22-2026-05-07T00/`                                |
| hour slot       | `2026-05-26T17` (synthetic, default `WAT_TV3_HOUR_BASE`)                    |
| age hours       | 192 (= 8 days; crosses the 7-day soft window)                               |
| live stamp env  | `1` (live-stamp leg requested)                                              |
| daily budget    | `{"2026-05-06": 4, "2026-05-07": 1}` after run                              |
| merkle root     | `7a9c2ffee000ed8cbb22a5d450323bf34f2ac7bd780d4958ef8ca492d43dd2ea`          |
| state file      | `.runtime/wat-tv3-live-tag22-2026-05-07T00/2026-05-26T17/.state.json`       |
| exit code       | **0** (probe_rc=0, stamp_rc=0)                                              |

Note the merkle root is identical to the Tag-21 root — the spool
generator is deterministic on `WAT_TV3_HOUR_BASE` and the per-event
synthetic payload, so the same hour slot always yields the same
root. The Tag-22 calendar submit is therefore a **second public-OTS
receipt** of the same root, useful as a duplicate-anchor data point.

## 2 / Verbatim driver output

```
[wat-tv3-run] repo_root=/var/home/fred/AI-Corp/agents-workspaces/dev-engineering/wakir-runtime
[wat-tv3-run] archive_root=.runtime/wat-tv3-live-tag22-2026-05-07T00/
[wat-tv3-run] hour_slot=2026-05-26T17 age_hours=192 live_stamp=1
[wat-tv3-run] started=2026-05-07T06:43:04Z
[wat-tv3-run] step 1/6: generating synthetic 1-event spool
[gen] tv3 hour 2026-05-26T17: wrote 1 event
[wat-tv3-run] step 2/6: building manifest hour=2026-05-26T17 (prev=null, cold-start)
[wat-tv3-run]   hour=2026-05-26T17 merkle_root=7a9c2ffee000ed8cbb22a5d450323bf34f2ac7bd780d4958ef8ca492d43dd2ea
[wat-tv3-run] step 3/6: writing synthetic .ots receipt
[wat-tv3-run] step 4/6: aging receipt mtime by 192h (crosses 7-day window if >=168)
[age] root.bin.ots: mtime set to 2026-04-29T06:43:04.775978+00:00
[wat-tv3-run] step 5/6: invoking backfill behavioural probe
backfill: receipt .runtime/wat-tv3-live-tag22-2026-05-07T00/2026-05-26T17/root.bin.ots pending for 8.0 days (soft window 7)
[probe] receipts=1 breached=1
[wat-tv3-run] probe_rc=0 (0=alarm-flagged, 4=no-alarm/bug)
[wat-tv3-run] step 6/6: checking daily submit budget for 2026-05-07
[budget] 2026-05-07: used=1/4 — OK
[wat-tv3-run] step 6/6: stamping merkle_root via 4 default calendars
pending receipt: .runtime/wat-tv3-live-tag22-2026-05-07T00/2026-05-26T17/root.bin.ots
  https://alice.btc.calendar.opentimestamps.org: ok
  https://bob.btc.calendar.opentimestamps.org: ok
  https://finney.calendar.eternitywall.com: ok
  https://btc.calendar.catallaxy.com: ok
[wat-tv3-run] summary: hour=2026-05-26T17 age_hours=192 probe_rc=0 stamp_rc=0 archive=.runtime/wat-tv3-live-tag22-2026-05-07T00/ root=7a9c2ffee000ed8cbb22a5d450323bf34f2ac7bd780d4958ef8ca492d43dd2ea
[wat-tv3-run] completed=2026-05-07T06:43:06Z
```

## 3 / `.state.json` artefact

```json
{
  "steps_done": [
    "spool",
    "manifest",
    "receipt",
    "aged",
    "probe",
    "stamp"
  ]
}
```

All six steps in the persistent driver completed. Compare Tag-21
`.state.json` (5 steps, no `stamp` because of budget refusal) — the
schema is the same, the resume substrate works in both directions.

## 4 / Daily budget side-effect

Pre-run: `{"2026-05-06": 4}`.
Post-run: `{"2026-05-06": 4, "2026-05-07": 1}`.

The Tag-21 memo §7 noted the budget file was byte-identical pre/
post-Tag-21 (refusal happens before the increment). Tag-22 mutates
the budget file with the expected `+1` on the new UTC-day key. The
file remains repo-anchored at `.runtime/wat-tv3-archive/.daily-budget.json`.

## 5 / Acceptance against §3.5 (rc=0 happy-path branch)

Spec contract under test:

> The TV-3 driver MUST submit a calendar stamp when (a) the receipt
> is aged past the soft window, (b) the probe reports an alarm
> flag, and (c) the daily-submit-budget for the current UTC day is
> below `WAT_TV3_DAILY_SUBMIT_BUDGET`. On success, exit 0 and
> increment the budget file by 1 for the current UTC day.

Probe assertions (all met):

| assertion                                                        | observed                                  | pass |
|------------------------------------------------------------------|-------------------------------------------|------|
| exit code is 0                                                   | `EXIT=0`                                  | yes  |
| stamp_rc is 0                                                    | `stamp_rc=0`                              | yes  |
| four-calendar broadcast all `ok`                                 | alice/bob/finney/catallaxy ok             | yes  |
| budget file incremented by 1 for current UTC day                 | `{"2026-05-07": 1}` (new key created)     | yes  |
| `.state.json` contains all six steps including `stamp`           | 6/6 in `.state.json`                      | yes  |
| probe_rc on aged receipt still 0 (behaviour contract intact)     | `probe_rc=0`                              | yes  |
| log line `[budget] ... OK` printed before stamp                  | `[budget] 2026-05-07: used=1/4 — OK`     | yes  |

Combined with Tag-21 (refusal branch), the §3.5 cadence-pacing
contract is now **fully verified live** on both branches:

| branch          | tag    | budget pre-run         | budget post-run               | exit |
|-----------------|--------|------------------------|-------------------------------|------|
| refusal         | Tag-21 | `{"2026-05-06": 4}`    | `{"2026-05-06": 4}` (unchanged) | 6    |
| happy-path      | Tag-22 | `{"2026-05-06": 4}`    | `{"2026-05-06": 4, "2026-05-07": 1}` | 0    |

## 6 / Bitcoin-anchor expectations and Tag-23 follow-up

The four PendingAttestation submits issued at 06:43:06Z join the
public-OTS calendar batch queue. Per the TV-1/TV-2 cadence corridor
(median 1-6 h, long tail to 24-72 h), Bitcoin-anchor heights for
the TV-3 root should land in roughly the same window:

- earliest expected partial finalisation: **2026-05-07 ~08:00Z**
  (~1 h post-submit).
- most-likely full 4-of-4 finalisation: **2026-05-07 ~12-20Z**
  (~5-13 h post-submit, mirroring TV-2).
- long-tail outer bound: **2026-05-09 ~07Z** (~48 h post-submit).

Queued for Tag-23: `bash scripts/wat-block-heights-collect.sh
.runtime/wat-tv3-live-tag22-2026-05-07T00/` to capture the actual
Bitcoin block heights and (assuming 1-of-4 lands) close the
TV-3-live-stamp acceptance dataset.

## 7 / Brand / Aufsichtsrat note

This memo together with `wat-tv3-live-stamp-2026-05-07.md` (Tag-21
refusal) form the first complete live-attestation pair of the
WAT-Phase-1a-Spec §3.5 cadence-pacing contract. The TV-3 driver is
now demonstrably emitting only the calendar traffic the spec
permits, and refusing the calendar traffic the spec forbids.

For Aufsichtsrat: this is the first time the TV-3 backfill-behaviour
driver has touched a public Bitcoin-calendar in non-test mode and
landed cleanly. Combined with TV-1 (single-hour root) and TV-2
(4-hour chain) Bitcoin-anchored runs, the WAT-Phase-1a Live-Run
dataset is now three-of-three vector classes covered with real
public-calendar submits.

## 8 / Verification stamp

- `date -u` 2026-05-07T06:43:04Z (P5, box start).
- Run-log captured live at
  `.runtime/wat-tv3-live-tag22-2026-05-07T00/run.log`; this memo
  quotes verbatim.
- `.state.json` artefact captured live; this memo quotes verbatim.
- Driver source at this commit:
  `scripts/wat-tv3-run-persistent.sh` (no changes from Tag-21).
- Brand-Guide §9 sweep: this memo carries no clear-name persona
  references.

— Tomás
