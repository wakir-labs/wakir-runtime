<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# WAT TV-2 — Operator Runbook

Status: draft, Phase 1a Tag-16, scheduled live-run KW 21-22 of 2026.
Companion to `docs/wat-tv2-test-plan.md` (spec) and
`scripts/wat-tv2-run-persistent.sh` (driver).

This runbook is the operator-facing checklist for running the TV-2
multi-hour chain-check **live** against the four production
OpenTimestamps calendars. It is not a development guide — see the
test plan for the design rationale and the gated pytest
`tests/wat/test_tv2_chain_check_real.py` for the offline regression
fixture.

## 1. Purpose recap

TV-2 walks a contiguous `H ∈ {4, 5, 6}` hour window and proves the
**`prev_hour_root`** wiring contract from `docs/wat-manifest-spec.md`
holds end-to-end through real public calendars. Each hour `h+1`'s
manifest carries a hex-encoded reference to hour `h`'s
`merkle_root`. Verifier `--chain-check` exits 0 only if the chain
links match byte-for-byte.

The driver script does **not** run the verifier acceptance loop —
that is the gated pytest's job. The driver's contribution is the
persistent archive directory that lets the day-+1 long-tail
collection and the verifier acceptance criteria run against real
Bitcoin block heights, mirroring TV-1's `wat-tv1-run-persistent.sh`
pattern.

## 2. Pre-flight check

Before invoking the driver:

| check                                                  | command                                          | expected             |
| ------------------------------------------------------ | ------------------------------------------------ | -------------------- |
| `ots` CLI on PATH                                      | `command -v ots`                                 | path returned        |
| Wakir runtime venv active                              | `python3 -c "import wat"`                        | exits 0              |
| Aggregator CLI accepts `--prev-hour-root`              | `python3 -m wat.cmd.aggregator_cli build --help` | shows the flag       |
| Anchor CLI accepts `--min-calendars`                   | `python3 -m wat.cmd.anchor_cli stamp --help`     | shows the flag       |
| At least one calendar reachable                        | `curl -sfo /dev/null https://bob.btc.calendar.opentimestamps.org` | exits 0              |
| `.runtime/` writable, no leftover TV-2 archive in path | `ls .runtime/wat-tv2-archive/`                   | empty or non-existent |
| Wall-clock UTC matches expected hour                   | `date -u`                                        | within drift band    |

Submit-cadence limits per the test plan §2:

- **Default budget**: `H × 4 = 16` calendar submits per run.
- **Stretch budget**: `H = 6 → 24` submits. Coordinate with the
  container-identity-eng (zone C) before running stretch
  back-to-back inside one calendar
  day; the public calendars publish a daily-budget guideline that
  the stretch run alone consumes ~50% of for a single project.
- **Inter-hour sleep**: default 2 s. Drop to 1 s only if the
  chain has to be visibly contiguous in wall-clock time — e.g. for
  a brand-launch demo recording. Do **not** drop below 1 s.

## 3. Run

```sh
# Default 4-hour chain, default fixed-anchor 2026-05-27T00..03.
$ bash scripts/wat-tv2-run-persistent.sh

# Custom 6-hour stretch
$ WAT_TV2_HOURS=6 bash scripts/wat-tv2-run-persistent.sh

# Custom anchor base (must stay inside one UTC date — no
# cross-midnight roll, see driver §HOUR_INT block)
$ WAT_TV2_HOUR_BASE=2026-05-27T08 bash scripts/wat-tv2-run-persistent.sh
```

Default archive root: `.runtime/wat-tv2-archive/<run-utc>/`. Override
via positional arg:

```sh
$ bash scripts/wat-tv2-run-persistent.sh /tmp/tv2-debug
```

The driver tees its output into `<archive-root>/run.log` and writes
a single-line `<archive-root>/summary.txt` for the outbox memo.

## 4. Expected output

Live-run output for the default `H=4` config (illustrative — actual
roots vary with manifest schema patches):

```
[wat-tv2-run] hours=4 hour_base=2026-05-27T00 inter_hour_sleep=2s
[wat-tv2-run] hour_slots: 2026-05-27T00 2026-05-27T01 2026-05-27T02 2026-05-27T03
[wat-tv2-run] step 1/4+: generating 4 hour spools (5 events each)
[gen] hour 0 (2026-05-27T00): wrote 5 events
[gen] hour 1 (2026-05-27T01): wrote 5 events
[gen] hour 2 (2026-05-27T02): wrote 5 events
[gen] hour 3 (2026-05-27T03): wrote 5 events
[wat-tv2-run] step 2.0/4: building manifest hour=2026-05-27T00 prev=<null>
[wat-tv2-run]   hour=2026-05-27T00 merkle_root=9f1a89598c93...
[wat-tv2-run] step 3.0/4: stamping merkle_root via 4 default calendars
[wat-tv2-run]   hour=2026-05-27T00 stamp_elapsed_s=2 receipt_bytes=608
[wat-tv2-run]   inter-hour sleep 2s (calendar politeness)
[wat-tv2-run] step 2.1/4: building manifest hour=2026-05-27T01 prev=9f1a8959...
...
[wat-tv2-run] step 4/4: verify sample event (--chain-check, pending tolerated)
[wat-tv2-run] verify_rc=3 (0=verified+chain-verified, 3=pending — both expected today)
[wat-tv2-run] summary: hours=4 hour_base=2026-05-27T00 archive=... verify_rc=3 roots=...
[wat-tv2-run] next: in ~3-24h re-run scripts/wat-block-heights-collect.sh ...
```

`verify_rc=3` (pending) on the same day is the expected output —
the Bitcoin batch cadence does not catch up inside the script's
runtime. Re-run `wat-block-heights-collect.sh` in 3-24 h to harvest
heights; long-tail completion is 24-72 h, same as TV-1.

## 5. Failure modes

| failure                                            | exit | recovery                                                                            |
| -------------------------------------------------- | ---- | ----------------------------------------------------------------------------------- |
| spool drift (event count != 5)                     | 1    | Re-pull repo head, ensure no local edits to the embedded Python heredoc.            |
| `WAT_TV2_HOURS` outside `{4,5,6}`                  | 1    | Re-export with valid value.                                                         |
| Hour expansion crosses midnight                    | 1    | Re-baseline `WAT_TV2_HOUR_BASE` so `HOUR + H ≤ 23` (driver refuses to roll silently). |
| Aggregator non-zero (`build` failed)               | 2    | Inspect `<archive-root>/<hour>/manifest.json` if present; check `wat.aggregator` traceback. |
| Anchor non-zero (`stamp` failed)                   | 2    | Calendar timeout most likely. Re-run is **not** automatic — see §6.                  |
| `prev_hour_root` mismatch in re-read of manifest   | 4    | Driver bug or corrupted manifest. Surface as a Tag-N-incident, do not retry blind.   |
| `ots` CLI missing                                  | 3    | `bash scripts/setup.sh` to populate the runtime venv.                                |

## 6. Re-run / partial-fail policy

Per test plan §2, **the driver does not retry a failed calendar
submit**. If hour `h` fails mid-window, the receipts in hours
`0..h-1` are already on Bitcoin's path and stay valid; the chain
simply truncates at hour `h-1`.

Recovery policy:

- **Calendar timeout, no receipt written**: accept the truncated
  chain, document `H_actual = h` in the outbox memo, do **not**
  re-run inside the same UTC hour. A re-run with the same root
  produces a duplicate calendar submit.
- **Aggregator crash, no manifest written**: safe to re-run the
  driver in the same hour; the spool is deterministic and the
  aggregator is idempotent against an absent prior manifest. Pass
  the same `WAT_TV2_HOUR_BASE` so the chain replays identically.
- **Manifest written, stamp crash before `root.bin.ots`**: also
  safe to re-run because the calendar accepts a duplicate of the
  same Merkle root as a no-op. But: the duplicate submit costs
  budget; coordinate with operator on-call.

## 7. Day-+1 harvest

Once the run has completed and at least 3 h have elapsed:

```sh
$ bash scripts/wat-block-heights-collect.sh \
      .runtime/wat-tv2-archive/<run-utc>/
```

Block-heights output goes to
`.runtime/wat-tv2-archive/<run-utc>/_reports/`. The same long-tail
24-72 h cadence as TV-1 applies; expect 1-of-4 on day +1, 4-of-4
on day +2 or +3 in the typical case.

## 8. Acceptance hand-off

After the live run, drop the following into the next-day outbox
memo:

- `summary.txt` line (single-line, for the memo header).
- `<archive-root>/_reports/block-heights-<utc>.md` (block-heights
  table per receipt).
- Verifier acceptance per test plan §5: A1-A5 each pass / fail line.

The gated pytest is the binding acceptance gate; this driver only
provides the persistent archive that the gated pytest's day-+1
re-verify reads.

## 9. Cross-review hooks

- **wirelang-eng (zone 2)** — `prev_hour_root` is v1-optional; the
  driver threads it explicitly. If the manifest-v2 work tightens the
  contract, see test plan §6 for the migration constraint and surface
  any drift via `agents-workspaces/dev-engineering/outbox/` as a
  zone-2 sync item.
- **container-identity-eng (zone C)** — `H × 4` calendar submits per
  run. The default `H=4` is well inside daily budget; `H=6` is a
  stretch. Coordinate before scheduling a TV-2 live-run in CI (the
  gated pytest is manual-only, see test plan §7).
- **sre-eng (zone H/I)** — `WAKIR_ESPLORA_BASE_URL` override is
  available the same way as for TV-1. The block-heights harvest at
  §7 uses it transparently when no local Bitcoin node is present.

— wat-eng
