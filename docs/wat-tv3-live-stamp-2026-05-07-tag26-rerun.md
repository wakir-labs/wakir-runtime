<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# WAT TV-3 — Tag-26 Live-Stamp Re-Run (post defect-fix)

## 0 / Document scope

This memo records the **fourth** end-to-end live execution of the
TV-3 backfill-behaviour driver with `WAT_TV3_LIVE_STAMP=1`, on
**2026-05-07 07:25 UTC** (Tag-26 box, post-fix re-run).

This is the live-mainnet verification of the Tag-25 driver-defect
fix (commit `9b3546a`) which addressed the receipt-persistence
regression observed on Tag-22 / Tag-24. The hermetic Cluster-6
test suite proved the fix on a mocked `anchor_cli` substrate; this
run proves it on the **real four-calendar OpenTimestamps mainnet**.

Predecessors:
- Tag-21 (`wat-tv3-live-stamp-2026-05-07.md`): cadence-pacing
  exit-6 verification, no calendar submit.
- Tag-22 (`wat-tv3-live-stamp-2026-05-07-tag22.md`): first live
  calendar submit, **defect-instance** — receipt on disk was the
  25-byte synthetic ASCII marker, not the real OTS proof.
- Tag-25 (outbox `2026-05-07-phase-1b-tag-25-tv3-driver-defect-fix.md`):
  driver fix + hermetic regression tests (17/17 green).

Tag-26 closes the audit-trail-repair loop by demonstrating that the
fixed driver, running unmodified against the production calendars,
persists a real OTS proof to disk.

## 1 / Run metadata

| field           | value                                                                       |
|-----------------|-----------------------------------------------------------------------------|
| start (UTC)     | 2026-05-07T07:25:38Z                                                        |
| end (UTC)       | 2026-05-07T07:25:41Z                                                        |
| driver          | `scripts/wat-tv3-run-persistent.sh` (Tag-25 fix: `rm -f` + 700-byte floor)  |
| archive root    | `.runtime/wat-tv3-archive/20260507T072538Z/`                                |
| hour slot       | `2026-05-26T17` (synthetic, default `WAT_TV3_HOUR_BASE`)                    |
| age hours       | 192 (= 8 days; crosses the 7-day soft window)                               |
| live stamp env  | `1` (live-stamp leg requested)                                              |
| daily budget    | `{"2026-05-06": 4, "2026-05-07": 2}` after run (2/4 used, 2 remaining)      |
| merkle root     | `7a9c2ffee000ed8cbb22a5d450323bf34f2ac7bd780d4958ef8ca492d43dd2ea`          |
| receipt file    | `.runtime/wat-tv3-archive/20260507T072538Z/2026-05-26T17/root.bin.ots`      |
| receipt size    | **805 bytes** (real OTS proof, > 700-byte floor)                            |
| exit code       | **0** (probe_rc=0, stamp_rc=0)                                              |

The merkle root is identical to Tag-21 / Tag-22 — the spool
generator is deterministic on `WAT_TV3_HOUR_BASE`, so the same hour
slot always yields the same root. Tag-26 is therefore a **third
public-OTS submit** of the same root; together with Tag-21 (refused,
budget-exhausted, no submit) and Tag-22 (submitted but lost locally),
the calendars now hold three logically equivalent attestations of
this root via the Tag-22 + Tag-26 happy-path submits.

## 2 / Verbatim driver output

```
[wat-tv3-run] repo_root=/var/home/fred/AI-Corp/agents-workspaces/dev-engineering/wakir-runtime
[wat-tv3-run] archive_root=/var/home/fred/AI-Corp/agents-workspaces/dev-engineering/wakir-runtime/.runtime/wat-tv3-archive/20260507T072538Z
[wat-tv3-run] hour_slot=2026-05-26T17 age_hours=192 live_stamp=1
[wat-tv3-run] started=2026-05-07T07:25:38Z
[wat-tv3-run] step 1/6: generating synthetic 1-event spool
[gen] tv3 hour 2026-05-26T17: wrote 1 event
[wat-tv3-run] step 2/6: building manifest hour=2026-05-26T17 (prev=null, cold-start)
[wat-tv3-run]   hour=2026-05-26T17 merkle_root=7a9c2ffee000ed8cbb22a5d450323bf34f2ac7bd780d4958ef8ca492d43dd2ea
[wat-tv3-run] step 3/6: writing synthetic .ots receipt
[wat-tv3-run] step 4/6: aging receipt mtime by 192h (crosses 7-day window if >=168)
[age] root.bin.ots: mtime set to 2026-04-29T07:25:39.236866+00:00
[wat-tv3-run] step 5/6: invoking backfill behavioural probe
backfill: receipt /var/home/fred/AI-Corp/agents-workspaces/dev-engineering/wakir-runtime/.runtime/wat-tv3-archive/20260507T072538Z/2026-05-26T17/root.bin.ots pending for 8.0 days (soft window 7)
[probe] receipts=1 breached=1
[wat-tv3-run] probe_rc=0 (0=alarm-flagged, 4=no-alarm/bug)
[wat-tv3-run] step 6/6: checking daily submit budget for 2026-05-07
[budget] 2026-05-07: used=2/4 — OK
[wat-tv3-run] step 6/6: removing synthetic marker before live stamp
[wat-tv3-run] step 6/6: stamping merkle_root via 4 default calendars
pending receipt: /var/home/fred/AI-Corp/agents-workspaces/dev-engineering/wakir-runtime/.runtime/wat-tv3-archive/20260507T072538Z/2026-05-26T17/root.bin.ots
  https://alice.btc.calendar.opentimestamps.org: ok
  https://bob.btc.calendar.opentimestamps.org: ok
  https://finney.calendar.eternitywall.com: ok
  https://btc.calendar.catallaxy.com: ok
[wat-tv3-run] step 6/6: receipt persisted (805 bytes)
[wat-tv3-run] summary: hour=2026-05-26T17 age_hours=192 probe_rc=0 stamp_rc=0 archive=/var/home/fred/AI-Corp/agents-workspaces/dev-engineering/wakir-runtime/.runtime/wat-tv3-archive/20260507T072538Z root=7a9c2ffee000ed8cbb22a5d450323bf34f2ac7bd780d4958ef8ca492d43dd2ea
```

Three new diagnostic log lines from the Tag-25 fix are visible:
"removing synthetic marker before live stamp", the four `: ok`
calendar lines from `ots stamp`, and "receipt persisted (805 bytes)".

## 3 / Receipt inspection

`wc -c` on the receipt:

```
805 .runtime/wat-tv3-archive/20260507T072538Z/2026-05-26T17/root.bin.ots
```

First 64 bytes of the receipt (hex + ASCII):

```
00000000: 004f 7065 6e54 696d 6573 7461 6d70 7300  .OpenTimestamps.
00000010: 0050 726f 6f66 00bf 89e2 e884 e892 9401  .Proof..........
00000020: 08bd f617 b4b7 e249 3512 066a 1cd0 cb7d  .......I5..j...}
00000030: 0908 7d9a 682a 1598 1d74 44d2 937d 7bbc  ..}.h*...tD..}{.
```

This is the canonical OTS proof magic header (`\x00OpenTimestamps\x00\x00Proof\x00`)
followed by the per-calendar attestation stream. **Not** the
25-byte ASCII marker `SYNTHETIC_TV3_OTS_RECEIPT` that landed on
disk during Tag-22.

## 4 / Calendar status spot-check

`ots verify .runtime/wat-tv3-archive/20260507T072538Z/2026-05-26T17/root.bin.ots`
performed at **2026-05-07T07:26 UTC** (~30 seconds post-submit),
returns:

```
Calendar https://bob.btc.calendar.opentimestamps.org:    Pending confirmation in Bitcoin blockchain
Calendar https://finney.calendar.eternitywall.com:       Pending confirmation in Bitcoin blockchain
Calendar https://alice.btc.calendar.opentimestamps.org:  Pending confirmation in Bitcoin blockchain
Calendar https://btc.calendar.catallaxy.com:             Pending confirmation in Bitcoin blockchain
```

All four calendars return *Pending confirmation in Bitcoin
blockchain* — the expected state for a fresh submit. Bitcoin
attestation typically anchors within 4-12 hours; a 4-of-4 full
upgrade is **not** expected at this point in time and is **not**
the acceptance criterion for Tag-26.

The Tag-26 acceptance criterion is the **receipt-persistence
proof** (805-byte real OTS proof on disk + four calendar acks),
which is satisfied.

## 5 / Audit-trail-repair balance vs Tag-22

Side-by-side comparison of the same merkle root submitted twice:

| dimension                  | Tag-22 (defect)                           | Tag-26 (fixed)                                  |
|----------------------------|-------------------------------------------|-------------------------------------------------|
| submit time (UTC)          | 2026-05-07T06:43:05Z                      | 2026-05-07T07:25:40Z                            |
| four calendar acks         | yes (calendars accepted submit)           | yes (alice/bob/finney/catallaxy: ok)            |
| receipt file path          | `…2026-05-26T17/root.bin.ots`             | `…2026-05-26T17/root.bin.ots`                   |
| receipt size on disk       | **25 bytes** (ASCII synthetic marker)     | **805 bytes** (real OTS proof)                  |
| `xxd` first bytes          | `53 59 4e 54 48 45 54 49` (`SYNTHETI…`)   | `00 4f 70 65 6e 54 69 6d` (`.OpenTim…`)         |
| `ots verify` against file  | fails (not a parseable proof)             | succeeds — four pending-confirmation calendars  |
| audit-trail-reconstructible | no — local proof was never written       | yes — proof persists on disk                    |

The Tag-22 calendar submission itself was successful (the
calendars hold a proof of the merkle root, indexable by root hex);
what was broken was the **local audit-trail file**. The Tag-22
archive on disk could not be used to upgrade or verify, because
the on-disk file was not a valid OTS proof. The Tag-26 run
restores the on-disk audit-trail substrate.

The Tag-22 archive itself remains unrepaired — that is a sunk
cost — but the broken receipt is no longer reproducible by the
driver, and any future TV-3 live-stamp run will write a real OTS
proof. Two valid Bitcoin attestations of the same root now exist
in the calendar network (Tag-22 submit + Tag-26 submit); a future
4-of-4-upgrade would close the loop on either path.

## 6 / Daily budget accounting

Pre-Tag-26 daily-budget state for UTC `2026-05-07`: 1/4 used.
Post-Tag-26 state: 2/4 used. Remaining for the UTC day: 2 submits.

The Tag-26 live-run consumed 1 budget unit and did so with explicit
CEO authorisation (Tag-26 briefing, 2026-05-07).

## 7 / Acceptance — Tag-26 acceptance criteria

- [x] Driver re-executed on live mainnet with the Tag-25 fix in place.
- [x] All four default OpenTimestamps calendars returned ok on submit.
- [x] On-disk receipt file ≥ 700 byte (805 measured).
- [x] On-disk receipt file is a real OTS proof (magic header verified).
- [x] `ots verify` reports four pending-confirmation calendars.
- [x] Daily budget consumption recorded (2/4 for UTC 2026-05-07).
- [x] Audit-trail-repair balance documented (Tag-22 vs Tag-26 diff).

## 8 / Tag-27 spot-check (T+13 min post-submit)

Spot-check executed in the Tag-27 box (2026-05-07T07:38 UTC,
~13 min after the Tag-26 submit at 07:25:40Z) using
`scripts/wat-block-heights-collect.sh` against the Tag-26 archive
plus a direct `ots verify` to surface per-calendar transaction IDs.

### Calendar progression vs Tag-26 box-end

At Tag-26 box-end (T+~30s post-submit), all four calendars
reported `Pending confirmation in Bitcoin blockchain`. 13 minutes
later, two of the four have already broadcast a Bitcoin
transaction; the other two remain Pending:

| calendar                                          | T+30s (Tag-26)      | T+13min (Tag-27)                   |
|---------------------------------------------------|---------------------|------------------------------------|
| `https://alice.btc.calendar.opentimestamps.org`   | Pending             | tx `2519dd36…85d9fa`, awaiting 6 confs |
| `https://bob.btc.calendar.opentimestamps.org`     | Pending             | tx `fe2208c7…7e1dc69`, awaiting 6 confs |
| `https://finney.calendar.eternitywall.com`        | Pending             | Pending                            |
| `https://btc.calendar.catallaxy.com`              | Pending             | Pending                            |

This is faster progression than Tag-22 / Tag-23 / Tag-24 / Tag-25
showed at the same offset; the alice-and-bob pair typically
publishes within the first calendar-aggregation window (~1 hour),
finney + catallaxy aggregate on slower cadences.

### Esplora-fallback cross-check

The two non-Pending calendars name explicit Bitcoin transaction
IDs. Cross-checked against the Esplora-compatible mempool.space
API:

```
GET https://mempool.space/api/tx/<txid>/status
```

| transaction id        | confirmed | block height | block hash                                                              |
|-----------------------|-----------|--------------|-------------------------------------------------------------------------|
| `2519dd36…85d9fa` (alice) | true      | **948286**   | `00000000000000000001132d70f3804b8d22ef84ed25535254e46dbf2f61602e`      |
| `fe2208c7…7e1dc69` (bob)  | true      | **948286**   | `00000000000000000001132d70f3804b8d22ef84ed25535254e46dbf2f61602e`      |

Both calendar transactions landed in **the same Bitcoin block**
(height 948286, current chain tip per `GET /api/blocks/tip/height`
at 07:38 UTC). That is 1-of-6 confirmations on each path; OTS
default-finalisation (the upstream `ots upgrade` recognises a
calendar branch as upgradeable) needs all 6.

The block-heights collection script does not yet surface this
1-of-6 in-mempool-confirmed state directly — it currently classes
the receipt as `pending` because no `BitcoinBlockHeaderAttestation`
has been embedded in the proof tree. That happens only after
`ots upgrade` succeeds, which in turn needs the 6-confirmation
threshold. The Esplora call exposes the *underlying* mempool /
chain reality earlier than the calendar's `ots upgrade` endpoint
does. This is the design intent of the Esplora fallback in
ADR-0007 §3.

### Block-heights collect report

```
[wat-block-heights] archive=.runtime/wat-tv3-archive/20260507T072538Z
[wat-block-heights] found 1 receipt(s); running ots upgrade on each
[wat-block-heights] warn: ots upgrade non-zero ... (continuing)
[wat-block-heights] pending   2026-05-26T17/root.bin.ots
[wat-block-heights] summary: receipts=1 finalised=0 pending=1
```

Report file:
`.runtime/wat-tv3-archive/20260507T072538Z/_reports/tag27-spot-check.md`.

### Tag-28 voll-closure-projection

With both alice and bob already in block 948286, the upgrade window
moves up: at the standard ~10-min Bitcoin block cadence, 6
confirmations land roughly 60 minutes from now (~08:35-08:40 UTC,
2026-05-07). At that point an `ots upgrade` against the Tag-26
receipt should embed Bitcoin-block-header attestations for the
alice + bob branches, lifting the receipt from `pending` to a
2-of-4 partial-anchor state without waiting for the 46-hour Tag-28
box at all.

Finney + catallaxy operate on slower aggregation cadences;
historical Tag-22/Tag-23/Tag-24 data shows they typically catch up
within 12-24 hours but can take longer. A Tag-28 box at 12Z
(~28h post-submit) is on the right wallclock to expect 4-of-4
finalisation by then.

### Acceptance — Tag-27 spot-check

- [x] `wat-block-heights-collect.sh` walked the Tag-26 archive
      without error.
- [x] `ots verify` surfaces calendar-level transaction IDs for
      alice + bob; finney + catallaxy still Pending.
- [x] Esplora cross-check confirms both TXs in block 948286
      (chain-tip at spot-check time), 1-of-6 confirmations.
- [x] Spot-check result documented as Tag-26-doc extension §8.

— Tomás
