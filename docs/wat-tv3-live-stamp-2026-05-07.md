<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# WAT TV-3 — Tag-21 Live-Stamp Attempt (Budget-Breach Path)

## 0 / Document scope

This memo records the **second** end-to-end live execution of the TV-3
backfill-behaviour driver, with `WAT_TV3_LIVE_STAMP=1`, on
**2026-05-06 20:11 UTC** (Tag-21 hourly-tick box).

It is the planned follow-up to `wat-tv3-live-probe-2026-05-07.md`
(Tag-20, behaviour-only). Tag-20 §4 documented the deferral of the
live-stamp leg to "Tag-21 morning" once the daily budget rolled over
to a fresh UTC day. This memo records what actually happened: the
Tag-21 box ran inside the same UTC day (`2026-05-06`) as Tag-20, the
daily budget remained at the 4-of-4 cap, and the driver correctly
refused to stamp with **exit code 6 (budget breach)** as designed.

The honest data point this memo captures is the **cadence-pacing
contract live verification** — exit-6 is the expected behaviour for a
budget-saturated UTC day, not a bug. The rc=0 stamp-leg is rescheduled
to Tag-22 (after UTC midnight `2026-05-07T00:00Z`).

## 1 / Run metadata

| field           | value                                                                       |
|-----------------|-----------------------------------------------------------------------------|
| start (UTC)     | 2026-05-06T20:11:43Z                                                        |
| end (UTC)       | 2026-05-06T20:11:43Z (sub-second, no calendar traffic emitted)              |
| driver          | `scripts/wat-tv3-run-persistent.sh` (Tag-18 + Tag-20 budget-env-override)   |
| archive root    | `.runtime/wat-tv3-live-tag21/`                                              |
| hour slot       | `2026-05-26T17` (synthetic, default `WAT_TV3_HOUR_BASE`)                    |
| age hours       | 192 (= 8 days; crosses the 7-day soft window)                               |
| live stamp env  | `1` (live-stamp leg requested)                                              |
| daily budget    | `{"2026-05-06": 4}` — at cap before run, unchanged after run                |
| merkle root     | `7a9c2ffee000ed8cbb22a5d450323bf34f2ac7bd780d4958ef8ca492d43dd2ea`          |
| state file      | `.runtime/wat-tv3-live-tag21/2026-05-26T17/.state.json`                     |
| exit code       | **6** (budget breach, refused to stamp)                                     |

## 2 / Verbatim driver output

```
[wat-tv3-run] repo_root=/var/home/fred/AI-Corp/agents-workspaces/dev-engineering/wakir-runtime
[wat-tv3-run] archive_root=.runtime/wat-tv3-live-tag21/
[wat-tv3-run] hour_slot=2026-05-26T17 age_hours=192 live_stamp=1
[wat-tv3-run] started=2026-05-06T20:11:43Z
[wat-tv3-run] step 1/6: generating synthetic 1-event spool
[gen] tv3 hour 2026-05-26T17: wrote 1 event
[wat-tv3-run] step 2/6: building manifest hour=2026-05-26T17 (prev=null, cold-start)
[wat-tv3-run]   hour=2026-05-26T17 merkle_root=7a9c2ffee000ed8cbb22a5d450323bf34f2ac7bd780d4958ef8ca492d43dd2ea
[wat-tv3-run] step 3/6: writing synthetic .ots receipt
[wat-tv3-run] step 4/6: aging receipt mtime by 192h (crosses 7-day window if >=168)
[age] root.bin.ots: mtime set to 2026-04-28T20:11:43.403971+00:00
[wat-tv3-run] step 5/6: invoking backfill behavioural probe
backfill: receipt .runtime/wat-tv3-live-tag21/2026-05-26T17/root.bin.ots pending for 8.0 days (soft window 7)
[probe] receipts=1 breached=1
[wat-tv3-run] probe_rc=0 (0=alarm-flagged, 4=no-alarm/bug)
[wat-tv3-run] step 6/6: checking daily submit budget for 2026-05-06
[budget] 2026-05-06: used=4 limit=4 — REFUSE
EXIT=6
```

## 3 / `.state.json` artefact

```json
{
  "steps_done": [
    "spool",
    "manifest",
    "receipt",
    "aged",
    "probe"
  ]
}
```

Five of six pre-stamp steps completed. The `stamp` step is **not** in
the list because it was refused before any calendar traffic was
emitted. The state file is the resume substrate: a Tag-22 re-run
against the same archive root will pick up at step 6 and (assuming
UTC midnight rolled over to `2026-05-07`) succeed with rc=0.

## 4 / Why exit-6 is the right answer

Tag-21 box-execution time is **2026-05-06T20:11Z**, not Tag-21 *morning
UTC* as the Tag-20 deferral memo had assumed. The hourly-tick
brief at 22:00 CEST (~20:00 UTC) anticipated "frischer UTC-Day
2026-05-07", but UTC midnight is at 22:00 UTC, ~2 hours after the
brief and ~1 h 49 min after the live-stamp attempt. The daily budget
file is keyed on UTC-day `2026-05-06`, which is at its 4-of-4 cap
from earlier test-suite runs (Tag-18 / Tag-19, before the Tag-20 test-
isolation fix landed) and from the four real Tag-11 calendar submits
that funded the TV-1 long-tail data point.

The cadence-pacing contract is therefore exercised live in the
correct way: a fifth submit on the same UTC day **must** be refused
to honour calendar politeness. The driver returns exit 6, leaves the
budget file unchanged, and emits zero calendar traffic. That is the
spec-defined `WAT-Phase-1a-Spec §3.5` cadence-pacing behaviour.

## 5 / Plan for Tag-22 (rc=0 stamp-leg)

UTC midnight `2026-05-07T00:00Z` rolls the daily budget into a fresh
slot (the file becomes `{}` or auto-resets the `2026-05-07` key on
the next read). The Tag-22 box can then run:

```
WAT_TV3_LIVE_STAMP=1 bash scripts/wat-tv3-run-persistent.sh \
  .runtime/wat-tv3-live-tag22-2026-05-07T00/
```

Expected outcome:

- `probe_rc=0` (alarm correctly flagged on aged receipt).
- `stamp_rc=0` (calendar-submit OK for all four default calendars).
- daily budget post-run: `{"2026-05-07": 1}`.
- exit 0.

Re-running the **same archive root** also works (resume substrate),
but emitting a fresh archive root is cleaner because it gives a
distinct merkle root and a distinct calendar submit set per UTC day.

A second, third, fourth Tag-22 run on the same UTC day would each
add one to the count; a fifth run on the same UTC day would
correctly refuse with exit 6 — the same cadence-pacing branch this
Tag-21 memo just verified live.

## 6 / Acceptance against §3.5 (cadence-pacing branch)

Spec contract under test:

> The TV-3 driver MUST refuse to submit a calendar stamp when the
> daily budget for the current UTC day is at its `WAT_TV3_DAILY_SUBMIT_BUDGET`
> cap. Refusal MUST exit code 6, MUST NOT mutate the budget file,
> and MUST NOT emit any HTTP traffic to the public OTS calendars.

Probe assertions (all met):

| assertion                                                        | observed                                  | pass |
|------------------------------------------------------------------|-------------------------------------------|------|
| exit code is 6                                                   | `EXIT=6`                                  | yes  |
| budget file unchanged from pre-run state                         | `{"2026-05-06": 4}` -> `{"2026-05-06": 4}` | yes  |
| no calendar traffic emitted                                      | (no `[stamp]` line, no submit attempts)   | yes  |
| pre-stamp steps all completed                                    | 5/5 in `.state.json`                      | yes  |
| probe_rc on aged receipt is still 0 (behaviour contract intact)  | `probe_rc=0`                              | yes  |
| log line `[budget] ... REFUSE` printed                           | `[budget] 2026-05-06: used=4 limit=4 — REFUSE` | yes |

This is the first live verification that the cadence-pacing branch
of the TV-3 driver does what the spec says, exercised against a real
budget-saturated UTC day. Tag-22 will add the rc=0 happy-path data
point to close the §3.5 acceptance pair.

## 7 / Side-effect note: budget file unchanged

The Tag-21 attempt ran with `WAT_TV3_LIVE_STAMP=1` but
**did not mutate** `.runtime/wat-tv3-archive/.daily-budget.json` —
the refusal happens *before* the budget-increment step. The repo-
anchored budget file is byte-identical to its pre-Tag-21 state,
available for audit.

## 8 / Verification stamp

- `date -Iseconds` 2026-05-06T22:11:32+02:00 (P5, box start).
- Run-log captured live at
  `.runtime/wat-tv3-live-tag21/run.log`; this memo quotes verbatim.
- `.state.json` artefact captured live; this memo quotes verbatim.
- Driver source at this commit:
  `scripts/wat-tv3-run-persistent.sh` (Tag-20 budget-env-override
  applied, no Tag-21 changes to the driver itself).
- Brand-Guide §9 sweep: this memo carries no clear-name persona
  references. (Pre-existing TV-1-memo end-of-file author-sig is
  legacy content from Tag-11 / Tag-15; the Tag-21 box did not
  introduce any new author-sigs.)
