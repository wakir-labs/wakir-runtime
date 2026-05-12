<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# WAT TV-3 — Operator Runbook

Status: draft, Phase 1a Tag-18, scheduled live-probe sequence Tag-19+
across the next 2-3 UTC days subject to public-calendar daily budget.
Companion to `docs/wat-tv3-test-plan.md` (spec) and
`scripts/wat-tv3-run-persistent.sh` (driver). Gated regression
fixture: `tests/wat/test_tv3_backfill_leg.py`.

This runbook is the operator-facing checklist for invoking the TV-3
backfill-behaviour persistent driver. Unlike TV-1 and TV-2, TV-3
exercises the **backfill daemon's age-window contract**, not a
calendar latency or chain-check contract.

## 1. Purpose recap

TV-3 verifies that `wat.anchor.backfill.process_pending_queue` flags
a pending OpenTimestamps receipt that has been stuck for longer than
the seven-day soft window from WAT-Phase-1a-Spec §3.4. The driver
synthesises an aged receipt, invokes the daemon with a stub upgrader
(no public-calendar traffic), and captures the per-receipt
`UpgradeResult` to `backfill-probe.json` for evidence retention.

The behavioural contract:

| age (mtime delta) | finalised? | expected `soft_window_breached` |
| -----------------:| -----------| ------------------------------- |
| ≤ 7 days          | no         | `False`                         |
| > 7 days          | no         | `True`  (alarm)                 |
| > 7 days          | yes        | `False` (finalisation wins)     |

The driver exercises the middle row in its default mode (aged +
non-finalised stub). The first row is covered by hermetic script
tests; the third row is covered by the gated pytest.

## 2. Pre-flight check

Before invoking the driver:

| check                                            | command                                        | expected            |
| ------------------------------------------------ | ---------------------------------------------- | ------------------- |
| `ots` CLI on PATH                                | `command -v ots`                               | path returned       |
| Wakir runtime venv active                        | `python3 -c "import wat"`                      | exits 0             |
| Aggregator CLI accepts `--prev-hour-root`        | `python3 -m wat.cmd.aggregator_cli build --help` | shows the flag    |
| Backfill module importable                       | `python3 -c "from wat.anchor import backfill"` | exits 0             |
| `.runtime/` writable                             | `ls -ld .runtime`                              | drwx writable       |
| (live-stamp only) calendar reachable             | `curl -sfo /dev/null https://bob.btc.calendar.opentimestamps.org` | exits 0 |

The default behavioural-only mode does not need calendar reachability.

## 3. Submit-cadence pacing

TV-3's behavioural probe spends **zero submits** on the public OTS
calendars. When `WAT_TV3_LIVE_STAMP=1` is set, the driver additionally
submits one stamp through the four default calendars per invocation.
Pacing is enforced via a UTC-day budget file at
`.runtime/wat-tv3-archive/.daily-budget.json`. Default budget is
4 submits/day (override via `WAT_TV3_DAILY_SUBMIT_BUDGET`).

A multi-day live-stamp sequence is staged across 2-3 UTC days:

| UTC day | invocation                                     | submits this day | budget used |
| ------- | ---------------------------------------------- | ---------------- | ----------- |
| D+0     | `WAT_TV3_LIVE_STAMP=1 bash scripts/wat-tv3-run-persistent.sh` | 4 | 4 / 4       |
| D+1     | (re-invoke, fresh archive, new UTC date)       | 4                | 4 / 4       |
| D+2     | (re-invoke, fresh archive)                     | 4                | 4 / 4       |

Budget refusal returns exit 6 and leaves the rest of the behavioural
probe data in place — the operator can then either wait until the
next UTC day or raise `WAT_TV3_DAILY_SUBMIT_BUDGET` deliberately
(do not raise it without test-plan approval).

## 4. Failure modes

| symptom                                          | cause                                             | recovery                                                                |
| ------------------------------------------------ | ------------------------------------------------- | ----------------------------------------------------------------------- |
| Exit 1, `WAT_TV3_HOUR_BASE=... not in YYYY-MM-DDTHH form` | env var typo                              | re-run with the documented shape                                        |
| Exit 1, `WAT_TV3_AGE_HOURS=... not a non-negative integer` | env var typo                            | re-run with a non-negative integer                                      |
| Exit 1, `expected 1 event, got <n>`              | spool generator drift vs. gated test fixture      | abort; cross-check `_write_receipt`/spool heredoc against `test_tv3_backfill_leg.py` |
| Exit 2, aggregator failure                        | `wat.cmd.aggregator_cli build` raised             | check stderr; usually a manifest-spec drift                             |
| Exit 3, `ots CLI not on PATH`                     | venv not activated, or setup.sh skipped           | run `bash scripts/setup.sh` and re-invoke                                |
| Exit 4, `backfill probe did not flag soft-window breach` | `WAT_TV3_AGE_HOURS` set < 168 (= 7 days)   | raise to ≥ 192 (= 8 days) or investigate `process_pending_queue` regression |
| Exit 5, state file malformed / resume-from missing dir | `.state.json` corruption or wrong env var | inspect `.state.json`, fix or delete; re-run fresh                       |
| Exit 6, daily submit budget breached              | live-stamp invoked too often this UTC day          | wait for next UTC day, or raise budget deliberately                      |

## 5. Resume path

The driver records completed step labels in `<archive-root>/.state.json`
after each step transition. To resume an interrupted run:

```
WAT_TV3_RESUME_FROM=/path/to/archive bash scripts/wat-tv3-run-persistent.sh
```

The driver re-reads the state file, skips the labelled steps, and
picks up at the first non-completed step. If `.state.json` is
malformed, the driver aborts with exit 5 — delete the file (or the
archive) and start fresh rather than hand-editing.

The state file is the single source of truth for resume; mtimes and
file existence are not consulted directly. Losing the state file
means a full re-run.

## 6. Day-+1 harvest

**TV-3 does not have a day-+1 harvest leg.** The behavioural contract
under test reports synchronously inside the driver. There is no
analogue to TV-1's `wat-block-heights-collect.sh` here.

If `WAT_TV3_LIVE_STAMP=1` was set, the resulting `root.bin.ots`
becomes a real pending OTS receipt and can be harvested later via
`wat-block-heights-collect.sh` against the archive root, but that is
a sidecar verification, not part of the TV-3 acceptance loop.

## 7. Acceptance criteria

A TV-3 run is considered acceptance-grade if:

1. Exit 0 from `wat-tv3-run-persistent.sh`.
2. `<archive>/<hour-slot>/backfill-probe.json` contains exactly one
   `results` entry with `soft_window_breached: true` and `age_days
   >= 7.0`.
3. `<archive>/summary.txt` line includes `probe_rc=0`.
4. (live-stamp variant only) `<archive>/<hour-slot>/root.bin.ots`
   exists and is ≥ 256 bytes after a real calendar submit.
5. State file `.state.json` lists `spool`, `manifest`, `receipt`,
   `aged`, and `probe` (and `stamp` if live-stamp was used).

A run that meets (1)–(3) above and does not invoke live-stamp is the
default acceptance path for the Phase-1a sign-off; live-stamp is
only required if the test plan calls for it explicitly.

## 8. After-run hygiene

- `.runtime/` is in `.gitignore`; never check archives into the
  public repo.
- `backfill-probe.json` may quote real receipt paths; treat the
  archive as local-only evidence and reference it via run-UTC ID
  in any outbox memo, not by absolute path on disk.
- The daily budget file persists across runs intentionally; do not
  delete it as part of cleanup unless the operator wants to reset
  the day's submit history (which would let the next invocation
  exceed the documented cap).
