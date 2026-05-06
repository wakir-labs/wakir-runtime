<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# WAT TV-2 — Chain-Check Real-Calendar Test Plan

Status: draft, Phase 1a, scheduled for KW 21-22 of 2026.
Parent plan: `docs/wat-smoke-test-plan.md` (Tag-22 full-smoke).
Sibling plans: `docs/wat-tv1-test-plan.md` (volume),
`docs/wat-tv3-test-plan.md` (backfill leg).

This document concretises Test Vector 2 (TV-2) of the Tag-22
full-smoke plan: the **chain-check real-calendar pendant**. TV-1
proves the volume baseline for a single hour; TV-3 proves the
backfill daemon clears the queue after a multi-hour outage. TV-2
sits between them and proves the **multi-hour `prev_hour_root`
chain** holds against real public OpenTimestamps calendars over a
contiguous 4-6 hour window — i.e. the audit-trail-walking surface
that ADR-0020 commits us to.

The verifier-side chain semantics are already covered by
`tests/wat/test_verify_chain_check.py` (Tag-8) with mocked OTS
receipts. TV-2 is the integration mirror: same semantics, but every
hour in the chain is a real submission against the four production
calendars, and the Merkle root of hour H+1 cryptographically
references the Merkle root of hour H via the manifest's
`prev_hour_root` slot.

## 1. Multi-hour chain-construction strategy

A contiguous window of `H = 4` hours is the default; the test
parameterises `H ∈ {4, 5, 6}` so an operator can choose the
window length on the command line via `WAT_TV2_HOURS=N`. The
fixed-anchor strategy keeps the run reproducible:

- **Hour-0 slot**: `2026-05-27T00`. Each subsequent hour is `+1h`
  in lexicographic UTC notation. `H=4` runs `2026-05-27T00..03`.
- **Events per hour**: 5. TV-2 is about cross-hour wiring, not
  in-hour volume — that's TV-1's job. Five events is enough for a
  non-trivial Merkle tree (`tree_levels >= 3`) without spending
  calendar budget on a full hundred-event spool per hour.
- **Event generation** (per hour `h`):
  - `event_id`: `evt-tv2-{h:02d}-{i:04d}` for hour index `h` and
    event index `i ∈ [0, 4]`.
  - `time`: `2026-05-27T{h:02d}:{i*10:02d}:00.000Z` so events span
    the hour at 10-minute intervals. RFC 3339 millisecond
    precision matches TV-1.
  - `payload_hash`: SHA-256 of `f"tv2-h{h}-payload-{i}".encode()`.
  - `capability_token_hash`: SHA-256 of `tv2-cap-{i % 3}`. Three
    rotating capability tokens, smaller than TV-1's five — TV-2
    does not exercise dedup.

The hour-0 manifest is built with `prev_hour_root = null`
(cold-start of the audit trail). Each subsequent hour is built
with `--prev-hour-root <merkle_root_of_previous_hour>`, which
cryptographically links the chain.

## 2. Real-calendar submit cadence

Public OpenTimestamps calendars are a courtesy resource. TV-2
respects two hard rules:

- **One submit per hour-slot, no retries on success.** The test
  builds and stamps each hour exactly once. A calendar timeout on
  the first submit is logged and the hour is skipped (`H` in the
  acceptance criteria becomes `H-1`); the test does not loop.
- **Sequential, not parallel.** The four `OnCalendar` calendars
  receive submits in series across the hour-slots, never in
  parallel across hours. A `time.sleep(2.0)` delay between hours
  spreads the submits enough that bursty rate limits never trip.

Total calendar load for a single TV-2 run is therefore
`H × 4 = 16..24` calendar submits (one stamp call per hour, four
calendars per stamp). That is well within the ~daily budget the
public calendars publish in their FAQ.

## 3. `prev_hour_root` wiring contract

Per `docs/wat-manifest-spec.md` §"prev_hour_root reservation",
the v1 manifest treats `prev_hour_root` as **optional** with
default `null`. TV-2 exercises the opt-in branch:

- Hour 0: `prev_hour_root = null`. Verifier with `--chain-check`
  must report `chain_status = "chain-skipped"` and exit 0.
- Hours 1..H-1: `prev_hour_root = <hex of hour h-1 merkle_root>`.
  Verifier with `--chain-check` must report
  `chain_status = "chain-verified"` and exit 0.
- Negative-path (separate sub-test, not the main flow): manually
  rewrite hour 2's `prev_hour_root` to all-`ff` after the chain
  has been built. Verifier must then report
  `chain_status = "chain-mismatch"` and exit 4.

The negative-path sub-test does **not** re-stamp — it edits the
manifest JSON in place and re-verifies. Calendar receipts stay
attached to the original (correct) Merkle root, so the OTS-receipt
verify still passes; the failure surface is exactly the chain
check, which is what TV-2 is for.

## 4. Verify-CLI `--chain-check` integration

Each hour `h ∈ [1, H-1]` has its sample event verified via the
production verify-CLI:

```sh
$ python -m wat.verify.cli evt-tv2-{h:02d}-0000 \
      --archive-dir <archive> \
      --chain-check \
      --quiet
```

Exit codes accepted in TV-2:

| exit code | meaning                       | accepted? |
| --------- | ----------------------------- | --------- |
| 0         | verified + chain-verified     | yes       |
| 3         | pending (Bitcoin not yet)     | yes       |
| 1         | bad merkle proof              | **no**    |
| 4         | chain-mismatch                | **no** (positive path); **yes** (negative-path sub-test) |

Hour 0 is verified without `--chain-check` (trivially chain-skipped
when run with the flag, as captured in §3).

## 5. Acceptance criteria (mirror of Tag-22 plan A1-A5)

- **A1.** `tests/wat/test_tv2_chain_check_real.py` passes with
  `OTS_INTEGRATION_TEST=1`. Hash consistency against the offline
  reference computation in
  `tests/fixtures/jcs-leaf-vectors/` for at least the hour-0
  manifest (the cold-start hour reuses the TV-1 leaf-tuple shape).
- **A2.** Each of the `H` manifests has `event_count == 5` and
  `tree_levels >= 3` (`ceil(log2(5)) = 3`). The
  `version` field is `wakir-wat-manifest/v1`.
- **A3.** For each hour `h ∈ [1, H-1]`, the manifest's
  `prev_hour_root` field equals the previous hour's
  `merkle_root` byte-for-byte (hex-lower).
- **A4.** Verify-pending with `--chain-check` exits 0 or 3 for
  every sampled event in hours 1..H-1. Exit 1 or 4 in the
  positive path is a hard fail.
- **A5.** Negative-path sub-test (rewritten `prev_hour_root` in
  hour 2): verify-CLI with `--chain-check` exits 4 and prints
  `chain-mismatch` in `--quiet` mode, *without* invalidating
  the OTS receipt itself.

A1-A5 are each independent fail-points: any single failure blocks
TV-2 sign-off. Soft-budgets (calendar latency p95, build time
p50) carry over from TV-1 §3 and are recorded but do not gate.

## 6. Cross-Review-Hinweis — Reza (manifest-v1/v2-boundary)

Per `docs/wat-manifest-spec.md` §"chain semantics by manifest
version", the `prev_hour_root` slot is **optional in v1** and
**required in v2** (Phase 1b). TV-2 is a v1 test, so it builds
manifests with `version = "wakir-wat-manifest/v1"` and an
explicit `prev_hour_root` field per §3.

Two coordination risks against the v2 boundary:

- **Migration writer**: when the v2 writer lands (Phase 1b), TV-2
  becomes the regression baseline that v1 manifests still verify
  cleanly under v2 readers. The fixture builder must keep the v1
  shape forever, even after the production aggregator switches
  default to v2.
- **Field semantics**: v2 may tighten the legitimate-`null`
  set (currently "cold-start, post-empty-hour"); TV-2 hour 0
  pins the cold-start case. If v2 narrows that case, the hour-0
  fixture must explicitly opt into `version = "v1"` rather than
  inheriting the production default.

**Owner: Reza (Identity-Substrate / WAT manifest schema).** Surface
as a Tag-12 cross-review-zone-2 sync item if drift is detected
during TV-2 implementation rather than patching the fixture
inline. The wirelang-↔-WAT contract for hour-to-hour wiring lives
under his consensus owner hat.

## 7. Cross-Review-Hinweis — Kai (multi-hour calendar load)

The 16-24 calendar submits per TV-2 run sit comfortably inside
the public-calendar daily budget, but the cadence (`H` consecutive
hours over wall-clock minutes, not hours) is unusual for the
calendar operators. If Kai's Phase-1c container-identity work
ends up running CI on the gated suite, the TV-2 nightly should
**not** be scheduled in CI — it stays a manual, operator-driven
test. **Owner: Kai (infra / CI).** Surface as a Tag-13
cross-review-zone-C sync item if a CI-side trigger is proposed.

## 8. Operator runbook

```sh
# Default 4-hour chain
$ OTS_INTEGRATION_TEST=1 pytest tests/wat/test_tv2_chain_check_real.py -s

# Stretch to 6-hour chain (heavier calendar budget; courtesy check first)
$ OTS_INTEGRATION_TEST=1 WAT_TV2_HOURS=6 \
      pytest tests/wat/test_tv2_chain_check_real.py -s

# Harvest Bitcoin block heights once the daily anchor closes
$ bash scripts/wat-block-heights-collect.sh \
      "${WAKIR_RECEIPT_ARCHIVE:-./meta/timestamps/wat}"
```

The full TV-2 cycle (`H` hour-stamps + ~6 h Bitcoin batching) is
expected to complete inside 12-24 h on a normal weekday cadence.
The pytest run finishes in single-digit minutes (calendar latency
dominated); the block-heights harvest step is the same H+24
cadence as TV-1.

## 9. Out of scope

- **Backfill behaviour** when the calendar drops mid-window —
  TV-3 owns that path.
- **Volume-per-hour stress** — TV-1 owns that.
- **Cold-cache verifier startup latency** — covered indirectly
  by the verify-CLI smoke under `tests/wat/test_verify.py`.
- **Manifest-v2 chain semantics** — Phase-1b deliverable; out of
  TV-2's scope by design.
