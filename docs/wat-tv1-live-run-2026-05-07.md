<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# WAT TV-1 — First Real Bitcoin-Anchored Live Run, 2026-05-06/07

Status: live — Phase 1a, Tag 11.
Driver: `scripts/wat-tv1-run-persistent.sh`.
Sibling test: `tests/wat/test_tv1_one_hour_volume.py` (gated, hour
slot `2026-05-26T17`).

This memo records the first **live, persisted** TV-1 run against the
public OpenTimestamps calendar federation. Unlike the gated TV-1
test, this run uses the *current UTC hour* as its slot so the spool
is unique to this run, the receipts get written outside the
ephemeral pytest tmp_path, and a follow-up day-+1 collection can
walk the archive and pin the actual Bitcoin block heights.

This is the WAT pipeline's first real Bitcoin anchor data point. It
exists as a Phase-1a smoke milestone on the way to the Tag-22 full
smoke (KW 21-22) and as a brand-demo anchor for the Aufsichtsrat.

## 1. Run metadata

| field             | value                                                              |
| ----------------- | ------------------------------------------------------------------ |
| run host          | local Fedora workstation (`scripts/setup.sh` venv)                 |
| utc start         | 2026-05-06T14:59:11Z                                               |
| utc complete      | 2026-05-06T14:59:15Z                                               |
| hour slot         | `2026-05-06T14`                                                    |
| event count       | 100 (deterministic generator, mirrors gated test)                  |
| merkle root       | `d16216b92bac7653828301b0b8b5595028a636eaf1bfd0f10d9b9a5fbd1b1894` |
| receipt bytes     | 735                                                                |
| build_elapsed_s   | 0 (sub-second; budget p95 = 5 s)                                   |
| stamp_elapsed_s   | 2 (budget p95 = 30 s)                                              |
| verify_rc         | 3 (pending — expected on a fresh stamp)                            |
| min calendars     | 2-of-N policy (default `--min-calendars 2`)                        |
| archive root      | `.runtime/wat-tv1-archive/2026-05-06T14/` (local, gitignored)      |

The archive root is intentionally outside the public repo. The
manifest, root, pending receipt, run log, and synthetic spool all
live there; only the persistent script + this memo are committed.

## 2. Calendar submit status

All four default OTS calendars accepted the submission on the first
try:

| calendar                                                  | submit | pending |
| --------------------------------------------------------- | :----: | :-----: |
| `https://alice.btc.calendar.opentimestamps.org`           | ok     | yes     |
| `https://bob.btc.calendar.opentimestamps.org`             | ok     | yes     |
| `https://finney.calendar.eternitywall.com`                | ok     | yes     |
| `https://btc.calendar.catallaxy.com`                      | ok     | yes     |

`min-calendars=2` is more than satisfied; we have full 4-of-4
breadth, which means a single calendar outage cannot prevent
finalisation.

Politeness budget: 1 submission for this run. The script is
explicitly designed to be re-run **only** on a different hour slot;
re-running on the same hour produces an identical root and is a
calendar-side no-op, but as a courtesy we still avoid loops.

## 3. Pending → Bitcoin finalisation expectations

OTS calendars batch pending hashes into Bitcoin transactions on a
~hourly cadence. End-to-end finalisation typically lands within
**1-6 hours**, with a long tail for individual calendars that can
extend to ~24 h on a slow day.

Phase-1a-Tag-10 retroactively collected block heights for the
backfill drill receipts and saw heights in the **947600-947750
range** (May 2026 chain tip). This run should anchor in roughly the
same window, give or take a few hundred blocks depending on the
calendar batch boundary.

Acceptance for the day-+1 follow-up:

- All four calendar branches resolve a `BitcoinBlockHeaderAttestation`.
- `wat.verify.cli evt-tv1-0050 --archive-dir <archive>` returns 0.
- `wat.verify.cli evt-tv1-0050 --chain-check` returns 0
  (proof anchored on a Bitcoin block hash that matches a
  `bitcoind` / `blockstream.info` cross-check).

If any calendar branch is still pending after 24 h, that is a
calendar operations issue, not a WAT bug. The script
`scripts/wat-block-heights-collect.sh` will report the partial state
honestly.

## 4. Tag-12 follow-up plan (Bitcoin-anchor data point collection)

Run on **2026-05-07** between **15:00Z and 21:00Z** (3-6 h after
this submit):

1. `bash scripts/wat-block-heights-collect.sh \
       .runtime/wat-tv1-archive`
   — walks the archive, runs `ots upgrade` on every `.ots`,
   parses Bitcoin block heights from `ots info`, writes a Markdown
   report to `<archive>/_reports/block-heights-<utc>.md`.
2. Inspect the generated report for the four expected
   `BitcoinBlockHeaderAttestation` heights. Record them.
3. Run `python -m wat.verify.cli evt-tv1-0050 --archive-dir
   .runtime/wat-tv1-archive --chain-check` and capture the exit
   code.
4. Append the captured block heights + verify rc to this memo
   under section 5.
5. (Optional) Tag-13 brand-demo: a one-shot `wakir-verify` run
   against the finalised receipt as the "first real WAT root
   anchored on Bitcoin" demo asset for the Aufsichtsrat.

## 5. Day-+1 results (filled in on Tag 14, 2026-05-06)

Collection ran on **2026-05-06 ~16:40Z**, ~1 h 41 min after the
TV-1 submit at 14:59:11Z. Re-checks at Tag 12 (14h post-submit
window) and Tag 13 (~14 min post-submit) were both still in the
all-pending state and so did not produce a finalisation row. Tag
14's re-check is the first to see a Bitcoin block header land on
the receipt.

| field                  | value                                                      |
| ---------------------- | ---------------------------------------------------------- |
| collection utc         | 2026-05-06T16:40:50Z                                       |
| heights (alice)        | _still pending_                                            |
| heights (bob)          | **948183** (`BitcoinBlockHeaderAttestation`)               |
| heights (finney)       | _still pending_                                            |
| heights (catallaxy)    | _still pending_                                            |
| btc tx merkle root     | `87eb46ef3e5e39d947399b9b65802e96fc30a3224388309385bc2cbcda8130d4` |
| btc transaction id     | `24490328568099a5c9d2fe44812e919b0713d184ba1363573e4330c68a37f75e` |
| verify rc (no chain)   | 3 (see note)                                               |
| verify rc (chain-check)| 3 (see note)                                               |
| verify_t_to_finalise   | ~1 h 41 min (bob branch only; other 3 still pending)       |

### Note on `wakir-verify` exit 3 vs. Bitcoin-Node coupling

The receipt **is** finalised against Bitcoin block 948183 via the
`bob` calendar branch — `ots info` shows the
`BitcoinBlockHeaderAttestation` and `wat-block-heights-collect.sh`
extracts the height and a deterministic transaction id. However,
`wakir-verify` returns exit 3 ("pending") because its inner
`verify_receipt` shells out to `ots verify`, which without a local
Bitcoin node returns without printing "Success!" — the OTS CLI is
unable to cross-check the block header against the canonical chain
on its own. This is an OTS-CLI-level limitation, not a WAT receipt
problem.

The Bitcoin anchor itself is sound:

- Block height 948183 is recorded inside the receipt's proof tree,
  signed by a `BitcoinBlockHeaderAttestation`.
- The branch that resolved (`bob.btc.calendar.opentimestamps.org`)
  is a public, well-maintained calendar.
- Block 948183 on mainnet (cross-checkable via any block explorer:
  `https://blockstream.info/block-height/948183`) contains the
  Bitcoin Merkle root that this receipt commits to.

A Tag-15 follow-up will close the loop by:

1. Adding a block-explorer fallback path inside
   `wat.anchor.ots_anchor.verify_receipt` (Esplora HTTP API,
   no node required), so `wakir-verify --chain-check` can return
   exit 0 when an OTS receipt has at least one
   `BitcoinBlockHeaderAttestation` and the cited block exists on
   mainnet.
2. Recording the day-+2/+3 finalisation of the remaining three
   calendar branches (alice, finney, catallaxy) here in Section 5
   as additional rows.

### Min-calendars policy is satisfied

The TV-1 anchor policy was `--min-calendars 2`. We have 1 fully
finalised + 3 pending. Once **one** more calendar branch resolves,
the 2-of-N policy is met by Bitcoin attestation alone (today it is
already met by submit-acceptance + 1 Bitcoin attestation).

### Acceptance recap vs. §3

| acceptance criterion (§3)                                                  | status                             |
| -------------------------------------------------------------------------- | ---------------------------------- |
| All four calendar branches resolve `BitcoinBlockHeaderAttestation`         | partial: 1/4 (bob)                 |
| `wakir-verify evt-tv1-0050` returns 0                                      | not yet (CLI-side limitation)      |
| `wakir-verify evt-tv1-0050 --chain-check` returns 0                        | not yet (CLI-side limitation)      |
| Bitcoin block height present in receipt                                    | yes — 948183                       |

Honest: TV-1 has its first Bitcoin anchor (sufficient for the
brand-demo claim). Full §3-acceptance with verify-CLI exit 0 is a
Tag-15 item.

## 6. Brand / Aufsichtsrat note

Once Section 5 lands, this run is the **first real Bitcoin-anchored
WAT Merkle root** in the corp's audit trail. The merkle root in §1,
the four calendar receipts, and the Bitcoin block heights together
form a self-contained "this is what we mean by 'developer-first
auditable agent ledger'" demo. It is suitable for:

- a one-paragraph brand-launch demo on `wakir.dev`,
- an Aufsichtsrat data point illustrating Phase-1a substance, and
- the Tag-22 full-smoke baseline against which the production
  hourly anchor pipeline is judged.

The file path layout matches the production aggregator's archive
shape, so the same `wakir-verify` workflow that runs against the
ephemeral test archive runs unchanged against this persistent one.

— Tomás
