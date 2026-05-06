<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# WAT TV-1 — 100-Events One-Hour Volume Test Plan

Status: draft, Phase 1a, scheduled for KW 21-22 of 2026.
Parent plan: `docs/wat-smoke-test-plan.md` (Tag-22 full-smoke).

This document concretises Test Vector 1 (TV-1) of the Tag-22
full-smoke plan: a hundred synthetic events spool through the
production aggregator, anchor through the public OTS calendars, and
get verified end-to-end. TV-1 is the volume baseline against which
the per-event cost figures in WAT-Phase-1a-Spec §8 are measured.

## 1. Event-generation strategy

A single hour slot is fixed at `2026-05-26T17` so the test is
reproducible across runs. Inside that hour, 100 synthetic events
are generated with:

- `event_id`: `evt-tv1-NNNN` (zero-padded, 0..99). Lexicographic
  sort matches numeric sort within this naming scheme.
- `time`: `2026-05-26T17:MM:SS.fffZ`, where minute and second are
  computed from the index so events span the full hour. RFC 3339
  millisecond precision keeps the leaf-projection deterministic.
- `payload_hash`: SHA-256 of `f"tv1-payload-{i}".encode()`,
  hex-lower. Each event's hash is unique and reproducible offline.
- `capability_token_hash`: SHA-256 of one of five rotating cap-token
  identities (`tv1-cap-A` through `tv1-cap-E`). Five rotating tokens
  exercise the dedup-by-cap-hash path the aggregator uses for
  capability replay detection (Phase 1b feature; the leaf projection
  already records the bytes).
- `agent_did`: rotates through three synthetic DIDs
  (`did:wakir:tv1-agent-{1..3}`). Not part of the leaf tuple itself
  but kept for cross-module-vertrag against Wirelang Layer-1 frame
  shape — see `wirelang/specs/wat-leaf-projection.md` §3.

The synthetic spool is written to a `tmp_path` directory and never
persisted under `meta/` or version control.

## 2. Sortierungs-Verifikation

Per `docs/wat-spool-spec.md` §4 (and `wat-leaf-projection.md` §2),
the aggregator MUST sort events by `(time, event_id)` before
projecting leaves. TV-1 verifies this in two ways:

- **Pre-build assertion**: the test re-reads the spool, computes the
  expected `(time, event_id)` order in Python, and pins it.
- **Post-build assertion**: the test parses the manifest's
  `leaves[].event_id` array and asserts it matches the pre-computed
  order byte-for-byte.

A regression in `wat.merkle.aggregator.sort_events` (e.g. accidental
sort by `event_id` only) would surface here even before the OTS
calendars are touched.

## 3. Performance-Erwartungen

These budgets are the Phase-1a soft targets; Tag-22 sign-off
re-evaluates them against measured numbers. Hard CI gates are
deliberately absent — calendar latency is the dominant variable and
sits outside our control.

| stage                    | p50 budget | p95 budget |
| ------------------------ | ---------: | ---------: |
| build (100 events)       |    < 2.0 s |    < 5.0 s |
| stamp (-m 2, 4 calendars)|    < 5.0 s |   < 30.0 s |
| verify-pending (1 event) |    < 2.0 s |   < 10.0 s |
| upgrade-to-Bitcoin       |    < 3.0 h |   < 24.0 h |

Build time is the only stage entirely under WAT control; the others
are dominated by network round-trips.

## 4. Acceptance criteria (mirrors Tag-22 plan A1-A5)

- **A1.** `tests/wat/test_tv1_one_hour_volume.py` passes with
  `OTS_INTEGRATION_TEST=1`. Hash consistency against the offline
  reference computation in `tests/fixtures/jcs-leaf-vectors/`.
- **A2.** `manifest.event_count == 100` and `manifest.tree_levels >= 7`
  (`ceil(log2(100)) = 7`).
- **A3.** Verify-pending exits 0 or 3 for at least 95 of 100 sampled
  events. Exit 1 or 4 anywhere = TV-1 fail.
- **A4.** Stamp p50/p95 within the budgets in §3 across three
  consecutive runs. Outliers above p95 are recorded but do not block
  sign-off (the public calendars vary by ~10x at peak hours).
- **A5.** Once `wat-block-heights-collect.sh` is run on the TV-1
  archive, every receipt either yields ≥ 1 Bitcoin block height OR
  is younger than 24 h. No silent stuck pendings.

## 5. Cross-Review-Hinweis

TV-1 consumes the four-field B1 leaf tuple defined in
`wirelang/specs/wat-leaf-projection.md` §2. The TV-1 generator does
not synthesise full Wirelang Layer-1 frames — only the projected
fields — so spec drift between Wirelang frame shape and the WAT
leaf tuple is a coordination risk. The Identity-Substrate-Owner
(wirelang-eng) is the consensus owner for that contract; if drift
is detected during TV-1 implementation, flag
it as a Tag-10 cross-review-zone-2 sync item rather than patching
the projection inline.

## 6. Operator runbook

```
$ OTS_INTEGRATION_TEST=1 pytest tests/wat/test_tv1_one_hour_volume.py -s
$ bash scripts/wat-block-heights-collect.sh \
      "${WAKIR_RECEIPT_ARCHIVE:-./meta/timestamps/wat}"
```

The full TV-1 cycle (submit + ~6 h Bitcoin batching + upgrade) is
expected to complete inside 24 h on a normal weekday cadence. The
two commands above can therefore be split: run pytest at hour H,
run the block-heights collector at H+24 to harvest the heights for
the audit log.
