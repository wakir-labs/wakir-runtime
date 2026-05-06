<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# WAT Tag-22 Full-Smoke Test Plan

Status: draft, Phase 1a, scheduled for KW 22 of 2026.

This document captures the test plan for the Tag-22 full smoke run
of the Wakir Audit Trail (WAT) hourly anchor pipeline. The Tag-9
realistic smoke (this branch) is a precursor; Tag-22 is the final
sign-off pass before Phase 1a closes.

## Scope

The Tag-22 smoke covers the hourly contract end-to-end:

1. event spool -> Merkle aggregation (`wakir-merkle build`)
2. Merkle root -> public OTS calendars (`wakir-anchor stamp`)
3. pending receipt -> Bitcoin attestation (`ots upgrade` after batch)
4. archived hour -> single-event proof (`wakir-verify`)
5. previous-hour root -> chain link (`--chain-check`)

Out of scope: the offline `wakir_verify` brand-proof package (covered
by its own test plan), federation cross-org checks (Phase 1b).

## Test vectors

### TV-1 — 100 events over a single hour

Synthetic spool of 100 events with valid B1-consensus shape, sorted
by `(time, event_id)` per `docs/wat-spool-spec.md` §4. The hour is
pinned to a fixed slot (`2026-05-26T17`) so the test is reproducible
across runs.

Expected: manifest `event_count` = 100, `tree_levels` ≥ 7, root
matches the offline reference computation in
`tests/fixtures/jcs-leaf-vectors/`.

### TV-2 — calendar failover simulation

One known-bad calendar URL (loopback closed port) plus three healthy
calendars, `-m 2` policy. Asserts the pipeline records the failure
without falling under the threshold.

Optional upgrade: a single calendar deliberately blocked at the
network layer (`iptables`, requires CAP_NET_ADMIN; not run in CI but
documented for the audit drill).

### TV-3 — backfill leg

Two pending receipts forced into the archive (one fresh, one with
mtime backdated by 8 days). `wat-backfill.sh` must:

- attempt `ots upgrade` on both,
- exit 0 if both upgrade or both stay within the 7-day soft window,
- exit 1 if any pending receipt aged past 7 days without finalising
  (audit-alarm channel triggers — see WAT-Phase-1a-Spec §3.4).

### TV-4 — chain-check across two hours

Build hour H, build hour H+1 with `prev_hour_root` of H, run
`wakir-verify --chain-check` on an event from H+1. Mutate the H
manifest's root by one byte and re-run; expect exit code 4
(chain-mismatch).

## Acceptance criteria (WAT-Phase-1a-Spec §7-§8)

A Tag-22 smoke run is considered passing when:

- A1. All four `tests/wat/test_ots_integration.py` cases pass with
  `OTS_INTEGRATION_TEST=1`, including against the public pool aliases
  `a.pool.opentimestamps.org` and `b.pool.opentimestamps.org`.
- A2. `scripts/wat-smoke-test.sh` (full mode, no `--quick`) completes
  with exit code 0 (finalised) within 6 hours of a normal weekday
  Bitcoin-block cadence. Exit code 3 (still pending) is acceptable
  if the run started inside the last 60 minutes; in that case the
  audit-alarm threshold is not yet reached.
- A3. The full repository test suite stays at 274 passing tests
  (Tag-8 baseline) plus the 4 integration cases gated on the env
  variable. No new failures or skips introduced by the smoke layer.
- A4. Calendar latency budgets observed in TV-1:
  - submit p50 < 5s, p95 < 30s
  - verify-pending p50 < 2s, p95 < 10s
  - upgrade-after-batch p50 < 3 hours, p95 < 24 hours
- A5. The chain-check failure case (TV-4) yields exit code 4 and a
  `chain_status: chain-mismatch` field in the verify CLI's human
  output.

## Operator runbook

The Tag-22 smoke is driven from a single host with the `.venv`
activated:

1. `bash scripts/wat-smoke-test.sh` (full, ~5 min sleep + ~6 h wait
   for Bitcoin batching)
2. `OTS_INTEGRATION_TEST=1 pytest tests/wat/test_ots_integration.py`
3. `bash scripts/wat-backfill.sh` against a synthetic archive
   prepared per TV-3.
4. Record latencies (submit / verify / upgrade) in the audit log
   under `meta/timestamps/wat/_pending/` for the smoke hour.

A failure on any acceptance criterion blocks the Phase 1a close-out
and is escalated to engineering-lead within 24h.
