<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# WAT Brand-Asset Snapshot — JSON Schema Spec (Stub)

Status: **stub / draft**, KW-21-Brand-Launch-Vorbereitung
Owner: dev-engineering / matrix-lead
Origin: Tag-24 Item 4 (Brand-Demo-Snapshot-Distribution-Vorbereitung,
Tag-23-followup), Sprint-Frontend-2-Trigger-Surface
Bezug: `agents-workspaces/dev-engineering/outbox/2026-05-07-brand-demo-anker-tv2-vollanker.md`
(Tag-23 Brand-Demo-Memo, TV-2 4-of-4-Voll-Anker), Sprint-Frontend-1
Brand-Asset-Embed-Item, ADR-0009 §3 Acceptance, ADR-0047
Live-Run-Vollanker.

This stub is **not** an implementation directive. It is the
JSON-Schema-Surface so frontend-engineering can plan the Sprint-Frontend-2-Item
"brand-page consumes structured snapshot" without waiting for the
JSON-mode Tag-25-Verifier-Pickup.

---

## 1. Problem statement

The Tag-23 Brand-Demo-Memo
(`outbox/2026-05-07-brand-demo-anker-tv2-vollanker.md`) is markdown
and human-readable. The Sprint-Frontend-1-Item embeds the markdown
prose directly into the brand page. That works for KW-20 mockups.

For KW-21 brand-launch and beyond, the brand page should consume a
**structured JSON snapshot** with the same facts, so:

1. Frontend can render the live-anchored facts without re-parsing
   markdown tables.
2. Snapshot can be re-generated cheaply on every successful Voll-
   Anker run (TV-2-style, future TV-x-style) without rewriting prose.
3. External consumers (other docs sites, embeddings) can pin the
   snapshot URL and verify against the chain independently.

The snapshot schema is **separate** from the verifier `--output json`
schema (Tag-25 pickup, per-event-id verification result). This is
a hour-aggregate, multi-receipt, brand-display-oriented payload —
the verifier-result schema is per-event-id and audit-oriented.

## 2. Snapshot schema (proposed)

JSON file, served at `https://wakir.dev/brand/snapshot.json` (or
similar; URL-stability is a Sprint-Frontend-2 decision).

```json
{
  "version": "wakir-brand-snapshot/1.0",
  "generated_at_utc": "2026-05-07T06:53:00Z",
  "source_run_id": "tv2-2026-05-06T17:37:26Z",
  "summary": {
    "headline": "Multi-Hour Audit-Trail in Bitcoin verankert",
    "hours_anchored": 4,
    "calendars_per_hour": 4,
    "bitcoin_blocks_distinct": 4,
    "block_height_min": 948198,
    "block_height_max": 948254,
    "block_height_span_blocks": 56,
    "closure_latency_hours": 13,
    "first_anchored_at_utc": "2026-05-06T17:37:26Z"
  },
  "hours": [
    {
      "hour_slot": "2026-05-27T00",
      "event_count": 5,
      "merkle_root": "9f1a89598c934fe3c8569d6fd110872075b3c91a7fc13d2a5954662f3665584b",
      "prev_hour_root": null,
      "calendar_anchors": [
        {
          "calendar": "alice.btc.calendar.opentimestamps.org",
          "bitcoin_block_height": 948199,
          "bitcoin_block_hash": "000000000000000000002cc843615a8953e1d6f6d706e42ad5503567b4327e22",
          "aggregator_tx_hash": "1ceb163b139c6215711dbfe86e2d2097c2476716023fa6a2c4d3e9f3efa3d9a3"
        },
        {
          "calendar": "bob.btc.calendar.opentimestamps.org",
          "bitcoin_block_height": 948198,
          "bitcoin_block_hash": "0000000000000000000044e0e6c1d6f85d3562523d6d63cfa7fb2250cb467fbe",
          "aggregator_tx_hash": "5f5b03985d2993aad1b4cd4c5de505bb88595156372c47869838a095f55d33e8"
        },
        {
          "calendar": "btc.calendar.catallaxy.com",
          "bitcoin_block_height": 948223,
          "bitcoin_block_hash": "00000000000000000001ed358dca9d1561bbddb7cc25b59e79fbc09b7869ec19",
          "aggregator_tx_hash": "d5223f6bffa8da4b3d108ed9afdf777d5d2516bf0801ed5bddc957d2bace28b3"
        },
        {
          "calendar": "finney.calendar.eternitywall.com",
          "bitcoin_block_height": 948254,
          "bitcoin_block_hash": "000000000000000000019f5ce13bd23a6e141a87da2bc5e1b6df3a05d8fb7fa2",
          "aggregator_tx_hash": "55ec8bd14708f7087f8beef15b1dec52454715174aa19d749981bb07b57216be"
        }
      ]
    }
  ],
  "verify": {
    "cli_repo": "https://github.com/wakir-labs/wakir-runtime",
    "cli_command_template": "wakir-verify <event_id> --archive-dir <archive> --chain-check",
    "exit_codes": {
      "0": "verified",
      "1": "failed",
      "3": "pending",
      "4": "chain-mismatch"
    }
  },
  "external_explorer_links": [
    {
      "calendar": "alice.btc.calendar.opentimestamps.org",
      "block_explorer_url": "https://mempool.space/block/000000000000000000002cc843615a8953e1d6f6d706e42ad5503567b4327e22",
      "tx_explorer_url": "https://mempool.space/tx/1ceb163b139c6215711dbfe86e2d2097c2476716023fa6a2c4d3e9f3efa3d9a3"
    }
  ],
  "caveats": [
    "Snapshot is a static export of one successful run; chain-tip moves on."
  ]
}
```

## 3. Field semantics

### 3.1 `version`

`wakir-brand-snapshot/<major>.<minor>`. Major bump on field-removal
or semantic break. Minor bump on additive field. Frontend consumes
`major == 1` strict.

### 3.2 `generated_at_utc`

RFC 3339 UTC instant when the snapshot was rendered from the
underlying `.runtime/wat-tv*-archive/` source-of-truth.

### 3.3 `source_run_id`

Stable identifier of the run. Format proposal:
`<tv-marker>-<hour-of-first-receipt-utc>`. Pins the snapshot to one
specific archive directory so re-generation is reproducible.

### 3.4 `summary`

Pure roll-up for hero-section / press-release-block consumption
without iterating `hours[]`. All values are derived from `hours[]`
(redundant, but avoids client-side aggregation).

- `headline`: short copy-paste-fähige Aussage. Default DE; optional
  i18n via separate `summary_i18n: {locale: {headline, ...}}` block
  if frontend needs it (Sprint-Frontend-3-Item).
- `hours_anchored`: `len(hours)`.
- `calendars_per_hour`: derived `len(hours[0].calendar_anchors)`,
  assumes all hours have the same calendar set (true for TV-2-style
  Voll-Anker). v1.1 may add `calendars_per_hour_min/max` for mixed
  cases.
- `bitcoin_blocks_distinct`: `len(set(b.bitcoin_block_height for h in
  hours for b in h.calendar_anchors))`.
- `block_height_min`, `block_height_max`, `block_height_span_blocks`:
  obvious min/max/diff.
- `closure_latency_hours`: hours from first calendar-submit to
  4-of-4-finalisation (Tag-22-style ~13 h for TV-2). Integer hours,
  rounded down. v1.1 may add minutes.
- `first_anchored_at_utc`: when the first calendar-submit happened
  (= run-start-time, RFC 3339).

### 3.5 `hours[]`

Ordered list of hour-aggregate objects. Order = chronological
ascending hour-slot (so `hours[0]` is the earliest, `hours[-1]` the
latest).

- `hour_slot`: UTC hour bucket, format `YYYY-MM-DDTHH` (no minute /
  second / TZ-suffix; matches archive layout).
- `event_count`: integer.
- `merkle_root`: 64-char lowercase hex.
- `prev_hour_root`: 64-char lowercase hex **or** `null` for cold-
  start. Frontend must handle both.
- `calendar_anchors[]`: ordered list of per-calendar Bitcoin
  attestations. Order = `bitcoin_block_height` ascending, ties
  broken by calendar-name lex-sort.

### 3.6 `verify`

Fixed metadata for the verify-CLI invocation. Stable across
snapshots (changes only on CLI-surface changes).

- `cli_repo`: HTTPS URL to the public repo.
- `cli_command_template`: invocation template with `<placeholder>`
  syntax; frontend can render or copy-paste verbatim.
- `exit_codes`: dict-of-int-to-string mapping. Source-of-truth is
  `wat/verify/cli.py`; snapshot mirrors at generation time.

### 3.7 `external_explorer_links[]`

One entry per calendar-anchor (so `len ==
sum(len(h.calendar_anchors) for h in hours) // hours_anchored`,
typically `4` for TV-2-style). Provides direct mempool.space (or
similar) URLs for independent verification without local tooling.

Frontend can render these as clickable links in the brand page or
omit them (CSP / link-policy decision).

### 3.8 `caveats[]`

Free-text list of brand-disclosed limitations. Examples:

- "Snapshot is a static export of one successful run; chain-tip
  moves on."
- "Verifier exit-codes are stable; archive layout may evolve."
- "Reorg risk on `block_height_max - chain_tip < 6` blocks is
  noted at generation time but not auto-tracked."

## 4. Generation pipeline (proposed)

A new script `scripts/wat-brand-snapshot-emit.sh` (or Python module
`wat/cmd/brand_snapshot.py`) walks the archive root and emits the
JSON to stdout. Invocation:

```bash
python -m wat.cmd.brand_snapshot \
  --archive-dir .runtime/wat-tv2-archive/20260506T173726Z \
  --tv-marker tv2 \
  --headline "Multi-Hour Audit-Trail in Bitcoin verankert" \
  > docs/brand/snapshot-tv2-20260506.json
```

Inputs:

- `--archive-dir`: required, points to the per-run-ID archive root
  containing `<hour-slot>/manifest.json` + `<hour-slot>/root.bin.ots`
  pairs.
- `--tv-marker`: required, `tv1` / `tv2` / `tv3` / `tv4+` etc.
- `--headline`: required string, copy-edited by comms / brand-voice
  owner (Cross-Review-Zone-G).

Behaviour:

- For each hour-slot dir under archive-dir, read `manifest.json`
  → extract `hour_slot`, `event_count`, `merkle_root`,
  `prev_hour_root`.
- Run `ots info` on `root.bin.ots` → parse `BitcoinBlockHeaderAttestation(N)`
  per calendar.
- For each calendar-anchor, fetch the block-hash and aggregator-tx-
  hash from Esplora-HTTP-fallback (`wat/anchor/esplora.py`).
  Cache hits avoid re-querying.
- Aggregate into `summary`, write JSON to stdout.

Exit codes: `0` on success, `1` on archive-malformed, `2` on
Esplora-fetch-fail, `3` on no-finalised-receipts (= run hasn't
closed yet; brand page should keep the previous snapshot).

## 5. Sprint-Frontend-2 Trigger-Surface

Frontend consumption:

- HTTP `GET /brand/snapshot.json` → 200 JSON.
- Pin to `version: "wakir-brand-snapshot/1.0"` strict major; warn-log
  on minor mismatch.
- Render `summary.headline` in hero, `hours[]` in collapsible
  Section-3b-style table, `external_explorer_links[]` as outbound
  links.
- Cache-control: 24 h; snapshot regenerated at most daily during
  KW-21-launch period.

Frontend does **not** validate Bitcoin attestations. The snapshot
is the trust surface; independent verification is the
`verify.cli_command_template` for users who want to re-check.

## 6. Open questions (must resolve before Sprint-Frontend-2 implementation)

1. **Snapshot URL stability:** `wakir.dev/brand/snapshot.json` vs
   `wakir.dev/brand/snapshot-<run-id>.json` (with index)? Mein
   Vorschlag: latest-stable URL plus per-run archive URL (both).
   Frontend-Cross-Review-Zone-E sign-off.
2. **i18n:** Default DE in `headline` / `caveats` or default EN
   with i18n sidecar? Mein Vorschlag: default EN matches public-
   facing repo language (ADR-0012); DE-Übersetzung als optional
   `summary_i18n.de`. Comms-Cross-Review-Zone-G sign-off.
3. **Caveat curation:** wer freigibt die `caveats[]`-Liste vor
   Brand-Launch? Mein Vorschlag: comms / brand-voice owner +
   internal-audit reviewer. Beide vor KW-21-Launch.
4. **Multi-cap-events forward-compat:** wenn Manifest-v2 emerges
   (post-Sprint-2), erweitert Snapshot um `multi_cap_events_count`
   in `summary` und optional `caprefs_root` per hour. Schema-Bump
   `wakir-brand-snapshot/1.1` (additive, kein Major).

## 7. Cross-Persona impact

| Persona      | Impact                                                                 |
| ------------ | ---------------------------------------------------------------------- |
| frontend     | **Sprint-Frontend-2 Trigger** — consumes JSON, renders brand page.     |
| comms        | **OQ-2 + OQ-3** — i18n default + caveat curation.                      |
| wirelang     | None for v1.0; OQ-4 (multi-cap forward-compat) is v1.1.                |
| sre          | Snapshot generation runs on cron post-Voll-Anker-run; SRE-Pipeline-    |
|              | Item, kein Strategie-Bruch.                                            |
| qa           | Test-Vector for snapshot-emit (TV-snapshot-1).                         |
| pengine      | None — snapshot is presentation-layer.                                 |

## 8. Implementation timeline (proposed)

- **Sprint-1 Tag-25:** verifier `--output json` (frontend-engineering
  pickup, Tag-23-Inbox-Memo) lands. **Different schema** (per-event-
  id result), but shares `verify.exit_codes` semantics with this
  snapshot.
- **Sprint-2 Tag-1-2:** `wat/cmd/brand_snapshot.py` scaffold, walks
  TV-2-archive, emits v1.0 JSON. Tests against TV-2 archive fixture.
- **Sprint-2 Tag-3:** Esplora-fetch integration, block-hash + tx-hash
  enrichment. Cache.
- **Sprint-2 Tag-4:** OQ-1/2/3 resolution (Cross-Review Zone E + G),
  schema-frozen.
- **Sprint-Frontend-2 (parallel):** Frontend consumes snapshot,
  hero + Section-3b-collapsible.
- **KW-21:** Brand-launch with snapshot-driven page.

---

— dev-engineering / matrix-lead
