<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# WAT TV-2 — First Multi-Hour Chain-Check Live Run, 2026-05-06/07

Status: live — Phase 1a, Tag 17.
Driver: `scripts/wat-tv2-run-persistent.sh`.
Sibling test: `tests/wat/test_tv2_chain_check_real.py` (gated, hour
slots `2026-05-27T00..03`).

This memo records the first **live, persisted** TV-2 run against the
public OpenTimestamps calendar federation. Unlike TV-1 (a single hour,
cold-start manifest), TV-2 builds a 4-hour deterministic event chain
where each hour's manifest threads `prev_hour_root` from the previous
hour's Merkle root, every hour stamps its own root through all four
default OTS calendars, and the verifier is exercised with
`--chain-check` against the last hour.

This is the WAT pipeline's first real **multi-hour Bitcoin anchor data
point** with prev-hour-root chaining wired end-to-end. It exists as a
Phase-1a milestone on the way to Tag-22 full smoke (KW 21-22) and as a
data point for Aufsichtsrat-Datapunkt §-style Brand-Demo extensions.

## 1. Run metadata

| field             | value                                                              |
| ----------------- | ------------------------------------------------------------------ |
| run host          | local Fedora workstation (`scripts/setup.sh` venv)                 |
| utc start         | 2026-05-06T17:37:26Z                                               |
| utc complete      | 2026-05-06T17:37:43Z                                               |
| hours (`H`)       | 4                                                                  |
| hour base         | `2026-05-27T00` (matches gated TV-2 fixture)                       |
| hour slots        | `2026-05-27T00`, `T01`, `T02`, `T03`                               |
| events per hour   | 5 (deterministic generator, mirrors gated test)                    |
| total events      | 20                                                                 |
| inter-hour sleep  | 2 s (politeness)                                                   |
| min calendars     | 2-of-N policy (default `--min-calendars 2`)                        |
| verify_rc         | 3 (pending — expected on a fresh stamp)                            |
| archive root      | `.runtime/wat-tv2-archive/20260506T173726Z/` (local, gitignored)   |

The archive root is intentionally outside the public repo. Per-hour
manifests, roots, pending receipts, run log, and synthetic spools all
live there; only the persistent script + this memo are committed.

## 2. Per-hour Merkle roots and prev-hour wiring

| hour slot         | merkle root                                                          | prev_hour_root                                                       |
| ----------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `2026-05-27T00`   | `9f1a89598c934fe3c8569d6fd110872075b3c91a7fc13d2a5954662f3665584b`   | `null` (cold-start)                                                  |
| `2026-05-27T01`   | `44046000e08faeb791af80792c4dd44ccec2497ea5eb593436244fd07ddf0f42`   | `9f1a89598c934fe3c8569d6fd110872075b3c91a7fc13d2a5954662f3665584b`   |
| `2026-05-27T02`   | `47bdb2788b7eb386af62b70505018dbec13310200283875ad0e562083ca1241a`   | `44046000e08faeb791af80792c4dd44ccec2497ea5eb593436244fd07ddf0f42`   |
| `2026-05-27T03`   | `9ad619e1c5c526e6a22a3ab9420c0c943c2c9bee484c4b3ece2d7894c4f3edad`   | `47bdb2788b7eb386af62b70505018dbec13310200283875ad0e562083ca1241a`   |

The driver re-reads each manifest after build and asserts that the
written `prev_hour_root` field equals the threaded `PREV_ROOT`
variable. Mismatches would Exit 4. None occurred — chain wiring is
byte-for-byte intact across all four hours.

## 3. Calendar submit status

All four default OTS calendars accepted submissions for **all four
hours** on the first try (16-of-16 ok):

| calendar                                                  | h0  | h1  | h2  | h3  |
| --------------------------------------------------------- | :-: | :-: | :-: | :-: |
| `https://alice.btc.calendar.opentimestamps.org`           | ok  | ok  | ok  | ok  |
| `https://bob.btc.calendar.opentimestamps.org`             | ok  | ok  | ok  | ok  |
| `https://finney.calendar.eternitywall.com`                | ok  | ok  | ok  | ok  |
| `https://btc.calendar.catallaxy.com`                      | ok  | ok  | ok  | ok  |

Politeness budget: **16 calendar submits per run** — within the
public-daily envelope cap and well below any single calendar's known
rate-limit horizon. The 2 s inter-hour sleep spreads the submits
enough to avoid bursty patterns; per the operator runbook
(`docs/wat-tv2-operator-runbook.md`), the script must not be looped on
the same `WAT_TV2_HOUR_BASE`. The default `2026-05-27T00` base is the
TV-2 fixture slot and is the only slot used during Phase-1a smoke
runs.

Per-hour stamp elapsed: 2 s on each hour (budget p95 = 30 s).
Receipt sizes: 595 - 840 bytes (driven by per-calendar batch
membership, no anomalies).

## 4. Verify-CLI sample with --chain-check

The driver's step 4 runs `wat.verify.cli evt-tv2-03-0000
--chain-check` against the last hour. Result:

```
pending evt-tv2-03-0000
verify_rc=3 (0=verified+chain-verified, 3=pending — both expected today)
```

Exit 3 ("pending") is the expected outcome on a fresh stamp:
the receipts are submitted but no calendar branch has produced a
Bitcoin block attestation yet. This is identical behaviour to TV-1
on Tag 11 (its first verify after stamp also returned exit 3) and
becomes exit 0 once the long-tail batches catch up.

The chain-check itself is not the load-bearing assertion at Tag-17
— that comes day-+1 after `scripts/wat-block-heights-collect.sh`
upgrades the receipts. What Tag-17 verifies is that

1. the four hours are byte-for-byte wired (per-hour
   `prev_hour_root` matches the previous hour's `merkle_root`),
2. all 16 calendar submits succeeded, and
3. the Verify-CLI cleanly reports "pending" (no schema drift, no
   manifest crash, no receipt-parse failure).

All three rows green.

## 5. Pending → Bitcoin finalisation expectations

OTS calendars batch pending hashes into Bitcoin transactions on a
~hourly cadence. End-to-end finalisation typically lands within
**1-6 hours**, with a long tail to ~24 h on a slow day. With four
hours of chained roots stamped within ~17 s, all four are likely to
batch into the **same** Bitcoin block window or two adjacent windows
— but the four are independent receipts and any per-calendar
finalisation order is acceptable.

Acceptance for the Tag-18 (or Tag-19) follow-up:

- Each of the four hours has at least one calendar branch that
  resolves to a `BitcoinBlockHeaderAttestation`.
- `wat.verify.cli evt-tv2-03-0000 --archive-dir
  .runtime/wat-tv2-archive/20260506T173726Z` returns 0 (single-hour
  verify against last hour).
- `wat.verify.cli evt-tv2-03-0000 --chain-check` returns 0
  (chain-verified against `prev_hour_root` ladder back to hour 0,
  Bitcoin-anchor cross-checked via the Esplora fallback).

If any calendar branch is still pending after 24-72 h, that is a
calendar-ops issue, not a WAT bug. The same Tag-15 Esplora-HTTP
fallback that unblocked TV-1's verify (no local `bitcoind`) applies
unchanged here.

## 6. Tag-18 follow-up plan (Bitcoin-anchor data-point collection)

Run on **2026-05-07** between **15:00Z and 22:00Z** (after at least
one Bitcoin batch boundary post-submit):

1. `bash scripts/wat-block-heights-collect.sh \
       .runtime/wat-tv2-archive/20260506T173726Z`
   — walks the archive, runs `ots upgrade` on every `.ots`, parses
   Bitcoin block heights from `ots info`, writes a Markdown report
   to `<archive>/_reports/block-heights-<utc>.md`.
2. Inspect the generated report for **four** expected per-hour
   receipts. Each should show at least one
   `BitcoinBlockHeaderAttestation` once the calendars have batched.
3. Run `python -m wat.verify.cli evt-tv2-03-0000 --archive-dir
   .runtime/wat-tv2-archive/20260506T173726Z --chain-check` and
   capture the exit code.
4. Append the captured per-hour block heights + verify rc to this
   memo under a new "Section 7. Day-+1 results" subsection (analog
   to TV-1's §5 pattern).

## 7. Acceptance recap vs. §5 (Tag-17 baseline)

| acceptance criterion                                                       | status                                                |
| -------------------------------------------------------------------------- | ----------------------------------------------------- |
| All 4 hours stamped with `prev_hour_root` chaining                         | **yes** (16-of-16 calendar submits ok)                |
| Per-hour `prev_hour_root` matches previous hour's `merkle_root`            | **yes** (driver re-read sanity check, no Exit 4)      |
| Verify-CLI `--chain-check` reports cleanly (pending exit 3 OK)             | **yes** (clean parse, no schema drift)                |
| Each hour resolves at least one `BitcoinBlockHeaderAttestation`            | pending: 0/4 at Tag-17 17:37Z (~0 min post-submit); Tag-18 re-check queued |
| Verify-CLI `--chain-check` exit 0 once batches land                        | pending: queued for Tag-18 re-check                   |

The Tag-17 baseline rows are green on the wiring + verifier side.
The Bitcoin-anchor rows depend on calendar batch cadence and are
day-+1 items, mirroring TV-1's Tag-14/15 pattern.

— Tomás
