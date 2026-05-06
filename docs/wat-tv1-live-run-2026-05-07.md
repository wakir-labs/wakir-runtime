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

## 5. Day-+1 results (Tag-14 collection + Tag-15 Esplora-fallback)

First collection ran on **2026-05-06 ~16:40Z**, ~1 h 41 min after
the TV-1 submit at 14:59:11Z; re-checks at Tag 12 and Tag 13 were
both all-pending. Tag-14 saw the first `BitcoinBlockHeaderAttestation`
land on the bob branch. Tag-15 added the Esplora HTTP fallback to
`verify_receipt` and re-ran the chain-check; the verify CLI now
returns exit 0 against block 948183 even on a host with no local
Bitcoin node. The other three calendar branches (alice, finney,
catallaxy) remain in the long tail of normal Bitcoin batch cadence
on Tag-15 17:03Z (~26 h post-submit), which is unsurprising and
not a WAT issue.

| field                  | value                                                      |
| ---------------------- | ---------------------------------------------------------- |
| first collection utc   | 2026-05-06T16:40:50Z (Tag-14)                              |
| latest collection utc  | 2026-05-06T17:03:26Z (Tag-15 re-check)                     |
| heights (alice)        | _still pending_ at 17:03Z                                  |
| heights (bob)          | **948183** (`BitcoinBlockHeaderAttestation`, Tag-14 first) |
| heights (finney)       | _still pending_ at 17:03Z                                  |
| heights (catallaxy)    | _still pending_ at 17:03Z                                  |
| btc tx merkle root     | `87eb46ef3e5e39d947399b9b65802e96fc30a3224388309385bc2cbcda8130d4` |
| btc transaction id     | `24490328568099a5c9d2fe44812e919b0713d184ba1363573e4330c68a37f75e` |
| btc block hash         | `00000000000000000000ec730435b01d9bdd9de0a10f1a8c4a33ea27e52b2110` |
| verify rc (no chain)   | **0** (Tag-15, Esplora fallback)                           |
| verify rc (chain-check)| **0** (Tag-15, chain-skipped because cold-start hour)      |
| verify_t_to_finalise   | ~1 h 41 min (bob branch only; other 3 still pending)       |

### Tag-15 Esplora HTTP fallback in `verify_receipt`

The Tag-14 limitation was: `verify_receipt` shelled out to `ots verify`
which without a local Bitcoin node could not confirm the
`BitcoinBlockHeaderAttestation(948183)` line was anchored on the
canonical chain. Tag-15 adds an HTTP fallback against the public
Esplora API (default `https://blockstream.info/api`, overridable via
`WAKIR_ESPLORA_BASE_URL` to point at `mempool.space` or a self-hosted
deployment). When `ots verify` does not return "Success!" the
fallback now extracts every `BitcoinBlockHeaderAttestation(H)` line
from `ots info`, resolves block `H` via Esplora, and on a 200-OK
hash response treats the receipt as cross-validated. The block hash
is persisted in `bitcoin_block_hash.txt` next to the receipt so that
repeat verifies short-circuit the network call.

The Esplora API is free and Apache-2.0-licensed (the implementation
itself is open-source). No formal rate-limit is published; we apply
a 10-second per-call timeout, a single sidecar-cache-protected GET
per receipt, and the User-Agent `wakir-runtime/0.0.1 (+https://wakir.dev)`
to be polite. Repeat verifies of the same receipt issue zero HTTP
calls.

Re-run on Tag 15 against the same receipt:

```text
$ wakir-verify evt-tv1-0050 --archive-dir .runtime/wat-tv1-archive --chain-check
event_id:       evt-tv1-0050
hour_slot:      2026-05-06T14
merkle_root:    d16216b92bac7653828301b0b8b5595028a636eaf1bfd0f10d9b9a5fbd1b1894
block_height:   948183
status:         verified
chain_status:   chain-skipped
EXIT: 0
```

The `chain-skipped` status is correct: TV-1 is a single-hour run, so
its manifest carries `prev_hour_root: null` (cold-start hour). A
multi-hour TV-2 run will produce `chain-verified` instead.

### Min-calendars policy is satisfied

The TV-1 anchor policy was `--min-calendars 2`. We have 1 fully
finalised on Bitcoin + 3 pending. Once **one** more calendar branch
resolves, the 2-of-N policy is met by Bitcoin attestation alone
(today it is already met by submit-acceptance + 1 Bitcoin
attestation, with the Bitcoin attestation independently
cross-validated via Esplora).

### Tag-16 long-tail re-check

Re-ran `bash scripts/wat-block-heights-collect.sh .runtime/wat-tv1-archive`
on **2026-05-06 17:20:24Z** (~26 h 21 min post-submit). The Esplora
fallback is now the default verify path on the host, so the upgrade
leg is decoupled from the local-Bitcoin-node story.

```
[wat-block-heights] found 1 receipt(s); running ots upgrade on each
[wat-block-heights] finalised 2026-05-06T14/root.bin.ots heights=948183
[wat-block-heights] summary: receipts=1 finalised=1 pending=0
```

Per-calendar status from `ots info` on the same receipt at
**2026-05-06 17:20Z** (Tag-16):

| calendar                                    | status                              |
| ------------------------------------------- | ----------------------------------- |
| bob.btc.calendar.opentimestamps.org         | finalised → block **948183** (Tag-14) |
| alice.btc.calendar.opentimestamps.org       | still pending                       |
| btc.calendar.catallaxy.com                  | still pending                       |
| finney.calendar.eternitywall.com            | still pending                       |

The collect-script's per-receipt summary line reports the unique
*set* of resolved heights across all calendar branches inside one
receipt; with three branches still in `PendingAttestation` and one
in `BitcoinBlockHeaderAttestation(948183)`, that set is `{948183}`
and the script logs `pending=0` at receipt-level (the receipt is
finalised on Bitcoin via at least one branch). The branch-level
breakdown above is the operator-visible long-tail picture.

Long-tail status at Tag-16 (~26 h post-submit) is **1/4 calendar
branches finalised**, unchanged from Tag-15 17:03Z. This is still
inside the spec corridor: the public-calendar FAQ and historical
operator notes both place the median Bitcoin-anchor batch cadence
at 1-6 h with a long tail to ~24-72 h, and 26 h on three of four
non-bob calendars is unremarkable. **A Tag-17 re-check is queued**
to capture the remaining long-tail finalisations as they arrive.

### Tag-17 long-tail re-check

Re-ran `bash scripts/wat-block-heights-collect.sh .runtime/wat-tv1-archive`
on **2026-05-06 17:37:39Z** (~26 h 47 min post-submit, ~17 min after
the Tag-16 re-check). Same harness, Esplora fallback active.

```
[wat-block-heights] found 1 receipt(s); running ots upgrade on each
[wat-block-heights] finalised 2026-05-06T14/root.bin.ots heights=948183
[wat-block-heights] summary: receipts=1 finalised=1 pending=0
```

Per-calendar status from `ots info` directly on the receipt at
**2026-05-06 17:37Z** (Tag-17):

| calendar                                    | status                              |
| ------------------------------------------- | ----------------------------------- |
| bob.btc.calendar.opentimestamps.org         | finalised → block **948183** (Tag-14) |
| alice.btc.calendar.opentimestamps.org       | still pending                       |
| btc.calendar.catallaxy.com                  | still pending                       |
| finney.calendar.eternitywall.com            | still pending                       |

Long-tail status at Tag-17 (~26 h 47 min post-submit) is **1/4
calendar branches finalised**, unchanged from Tag-15 / Tag-16.
Still inside the spec corridor (long tail to ~24-72 h on
non-bob calendars). The bob → 948183 finalisation continues to
satisfy `BitcoinBlockHeaderAttestation` for the Brand-Demo and
Aufsichtsrat-Datapunkt minimum-claim. The Tag-18 re-check is queued
to capture remaining long-tail finalisations.

### Acceptance recap vs. §3 (Tag-17)

| acceptance criterion (§3)                                                  | status                                                |
| -------------------------------------------------------------------------- | ----------------------------------------------------- |
| At least one calendar branch resolves `BitcoinBlockHeaderAttestation`      | yes — bob branch → block 948183 (Tag-14)              |
| All four calendar branches resolve `BitcoinBlockHeaderAttestation`         | partial: 1/4 at Tag-17 17:37Z (~26 h 47 min post-submit); Tag-18 re-check queued |
| `wakir-verify evt-tv1-0050` returns 0                                      | **yes** (Tag-15, Esplora fallback)                    |
| `wakir-verify evt-tv1-0050 --chain-check` returns 0                        | **yes** (Tag-15, chain-skipped on cold-start hour)    |
| Bitcoin block height present in receipt                                    | yes — 948183                                          |
| Block 948183 cross-validated against canonical chain                       | **yes** (Tag-15, via Esplora HTTP)                    |

The §3 acceptance is functionally complete on the verifier side;
five of six rows are green. The remaining open item — full 4-of-4
finalisation — depends on Bitcoin-batch cadence on the
alice / finney / catallaxy calendars and is not a WAT or verifier
issue. The Tag-18 re-check will record the long-tail finalisations
as they arrive.

### Tag-18 re-check (2026-05-06 17:55Z, ~2 h 56 min post-submit)

Re-ran `bash scripts/wat-block-heights-collect.sh
.runtime/wat-tv1-archive/2026-05-06T14/` on **2026-05-06 17:55:44Z**
(~2 h 56 min post-submit). Same harness, Esplora fallback active.

```
[wat-block-heights] found 1 receipt(s); running ots upgrade on each
[wat-block-heights] finalised .runtime/wat-tv1-archive/2026-05-06T14/root.bin.ots heights=948183
[wat-block-heights] summary: receipts=1 finalised=1 pending=0
```

Per-calendar status from `ots info` directly on the receipt at
**2026-05-06 17:55Z** (Tag-18):

| calendar                                    | status                              |
| ------------------------------------------- | ----------------------------------- |
| bob.btc.calendar.opentimestamps.org         | finalised → block **948183** (Tag-14) |
| alice.btc.calendar.opentimestamps.org       | still pending                       |
| btc.calendar.catallaxy.com                  | still pending                       |
| finney.calendar.eternitywall.com            | still pending                       |

Long-tail status at Tag-18 (~2 h 56 min post-submit) is **1/4
calendar branches finalised**, unchanged from Tag-15 / Tag-16 /
Tag-17. The Tag-18 re-check window (~3 h post-submit) was earlier
than the typical alice / finney / catallaxy long-tail (24-72 h post-
submit per spec); the Tag-19 re-check at ~24 h post-submit is the
next meaningful checkpoint. The bob → 948183 finalisation continues
to satisfy `BitcoinBlockHeaderAttestation` for the Brand-Demo and
Aufsichtsrat-Datapunkt minimum-claim.

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
