<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# WAT TV-3 — Backfill-Leg Test Plan

Status: draft, Phase 1a, scheduled for KW 21-22 of 2026.
Parent plan: `docs/wat-smoke-test-plan.md` (Tag-22 full-smoke).
Sibling plans: `docs/wat-tv1-test-plan.md` (volume),
`docs/wat-tv2-test-plan.md` (chain-check, in flight).

This document concretises Test Vector 3 (TV-3) of the Tag-22
full-smoke plan: the **backfill leg**. TV-1 and TV-2 cover the
happy-path hourly anchor; TV-3 covers what happens when the public
OpenTimestamps calendars are unreachable for several consecutive
hours and the backfill daemon has to clear the pending queue once
they come back. This is the test vector that proves the seven-day
soft window from WAT-Phase-1a-Spec §3.4 is actually enforced and
that a stuck pending receipt eventually surfaces as a hard alarm
rather than rotting silently in the archive.

## 1. Test scenario

A simulated three-day operational window is replayed against a
synthetic receipt archive:

- **Hours 0..23** (day 0): the hourly driver succeeds; receipts are
  written but the calendar service is "slow" and none of them
  upgrade to a Bitcoin attestation on the first try. This is
  steady-state pre-Bitcoin-confirmation behaviour and not a fault
  by itself — TV-3 just uses it as the population the backfill
  daemon will work on.
- **Hours 24..47** (day 1): the calendars are flagged as **down**.
  The hourly driver still writes manifest + `.ots` skeletons (the
  current production code stages a `root.bin` even when calendar
  submission fails — see `wat/cmd/anchor_cli.py`), but no upgrade
  is possible. Pending receipts accumulate.
- **Hour 48** (day 2): calendars come back. The 4×/day backfill
  cron (`wakir-wat-backfill.timer`, see §4) starts upgrading the
  oldest receipts first. Aging is computed off receipt mtime per
  `wat.anchor.backfill._receipt_age_days`.
- **Hours 48..167** (day 2..6): every backfill pass upgrades a
  larger fraction of the pending pool. Aging never crosses the
  seven-day soft window.
- **Day 7+ (negative-path branch)**: a single receipt is
  deliberately marked as un-upgradable across the whole window and
  must trigger `soft_window_breached=True` on the first backfill
  pass after the seven-day boundary.

## 2. Backfill daemon behaviour

The daemon under test is `wat.anchor.backfill.process_pending_queue`,
driven by `scripts/wat-backfill.sh` and triggered by
`wakir-wat-backfill.timer` at 00:30, 06:30, 12:30, and 18:30 UTC.
TV-3 asserts the following behavioural contract:

- **Soft-window pflege**: any pending receipt with mtime age
  ≤ 7 days returns `soft_window_breached=False`, regardless of
  whether the upgrade attempt produced a Bitcoin block height.
- **Hard alarm pattern**: any pending receipt with mtime age
  > 7 days **and** still not finalised returns
  `soft_window_breached=True`. The wrapper script propagates this
  as exit code 1, which the audit alarm channel grep'es out of the
  systemd journal (see README §"WAT hourly operations").
- **Idempotency**: re-running the backfill daemon on a directory
  that has no pending receipts is a no-op (zero results, exit 0).
- **Deterministic ordering**: results are returned in
  sort-by-path order so the audit log can diff successive runs
  cleanly.
- **Per-receipt isolation**: a single receipt that raises
  `AnchorError` does not stop the daemon — it is recorded with
  `error=...` and processing continues with the next file.

## 3. Pending-receipts aging detection

`UpgradeResult.age_days` is derived from `Path.stat().st_mtime` at
process start (with an injectable `now` for the test). TV-3
exercises the boundary explicitly:

| receipt mtime offset | upgraded? | expected `soft_window_breached` |
| -------------------- | --------- | ------------------------------- |
| `-1 day`             | no        | False                           |
| `-6.5 days`          | no        | False                           |
| `-7.0 days` (exact)  | no        | False (`>` not `>=`)            |
| `-7.01 days`         | no        | **True**                        |
| `-10 days`           | yes       | False (finalised wins)          |

The `>` (strict) comparison is the one currently in
`backfill.py` line 115 and 108; TV-3 pins it so a future refactor
to `>=` would surface as a test failure rather than a silent
shift in alarm semantics.

## 4. 4×/day cron trigger

The systemd timer is **not** invoked from the test (we cannot
assume systemd-user is available in CI). TV-3 instead asserts:

- the timer file at `scripts/systemd/wakir-wat-backfill.timer`
  contains exactly four `OnCalendar=` lines at the documented
  offsets (00:30, 06:30, 12:30, 18:30 UTC),
- `scripts/wat-backfill.sh` exits 1 when the synthetic archive
  has at least one breached receipt and 0 otherwise — without
  invoking the actual `process_pending_queue` (the test stubs the
  Python entry point so no real OTS calendar is contacted).

## 5. Acceptance criteria (mirror of Tag-22 plan A1-A5)

- **A1.** `tests/wat/test_tv3_backfill_leg.py` passes with
  `OTS_INTEGRATION_TEST=1`. The test does **not** contact public
  calendars; the gate is preserved for symmetry with TV-1/TV-2 and
  to keep the suite skip-clean on default CI.
- **A2.** All synthetic pending receipts younger than 7 days are
  either finalised (`bitcoin_block_height is not None`) within the
  simulated window or remain `soft_window_breached=False`.
- **A3.** The single deliberately-stuck receipt triggers exactly
  one `soft_window_breached=True` result at the first backfill
  pass past the seven-day boundary, and continues to do so on
  every subsequent pass until removed.
- **A4.** `process_pending_queue` is idempotent: running it
  twice in succession on the same archive produces the same
  result list (modulo any newly-finalised receipts from the first
  pass).
- **A5.** `scripts/wat-backfill.sh` exits 1 in the breach case
  and 0 in the clean case, matching the contract documented in
  README §"WAT hourly operations".

## 6. Cross-Review-Hinweis — wirelang-eng (spool-format-drift)

TV-3 generates synthetic `.ots` files via mock substitution rather
than a real OTS submission. If the spool format spec
(`docs/wat-spool-spec.md`) shifts in a way that adds required
sidecar files next to the `.ots` (e.g. a separate manifest JSON
that the upgrade path reads), the TV-3 fixture builder must be
extended to write those sidecars too. **Owner: wirelang-eng.** Surface as
a Tag-12 cross-review-zone-2 sync item if detected during TV-3
implementation rather than patching the fixture inline.

## 7. Cross-Review-Hinweis — SRE persona (backfill monitoring)

ADR-0042 activates a dedicated SRE persona in KW 22-23 of 2026.
Backfill alarm patterns — what counts as "stuck", what the
journal-grep query looks like, how the alarm escalates from
ntfy to mail to phone — are SRE-owned operational concerns, not
implementation concerns. TV-3 fixes the **detection contract**
(soft-window-breach flag, exit code 1) but explicitly does not
prescribe the alarm-channel behaviour. **Handoff to SRE persona
once activated:** decide journal-grep cadence, ntfy topic, and
whether breached-receipts should auto-page or accumulate on a
dashboard.

## 8. Operator runbook

```sh
# Run the gated TV-3 suite locally
$ OTS_INTEGRATION_TEST=1 pytest tests/wat/test_tv3_backfill_leg.py -s

# Reproduce a soft-window breach in a scratch archive
$ export WAKIR_RECEIPT_ARCHIVE=$(mktemp -d)
$ touch -d '8 days ago' "${WAKIR_RECEIPT_ARCHIVE}/stuck.ots"
$ bash scripts/wat-backfill.sh   # expect exit code 1
```

The second invocation shows the operator-facing alarm path: a
pending receipt older than the soft window causes the wrapper to
exit non-zero, which the systemd unit surfaces in the journal
under `[wat-backfill]`.
