<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Callandor GmbH and contributors

Licensed under the Creative Commons Attribution 4.0 International
License. Full text: https://creativecommons.org/licenses/by/4.0/
-->

# WAT Hourly Manifest — Format Specification

Version: `wakir-wat-manifest/v1`
Status: stable for Phase 1a.
Audience: implementers of independent verifiers and external auditors
who want to validate Wakir Audit Trail receipts without depending on
the reference runtime.

The hourly manifest is the bridge between the aggregator side
(`wakir-merkle build`) and the verifier side (`wakir-verify`). It is
the only on-disk artefact, beyond the OTS receipt itself, that an
external party needs in order to reconstruct the proof of inclusion
for any single event recorded during the hour.

## File layout

Each anchored hour produces a directory named after its UTC hour slot:

```
<archive>/<YYYY-MM-DDTHH>/
    manifest.json     # this document specifies its shape
    root.bin          # 32-byte raw Merkle root (omitted for empty hours)
    root.bin.ots      # OpenTimestamps receipt (omitted for empty hours)
    bitcoin_block.txt # optional, written after upgrade finalises
```

Hour slots are UTC; local time is never used. The five-minute slack
between the hour boundary and the cron run (Phase-1a-Spec §3.2) lets
late events settle before aggregation.

## Top-level fields

| field            | type             | required | notes                                  |
| ---------------- | ---------------- | -------- | -------------------------------------- |
| `version`        | string           | yes      | `wakir-wat-manifest/v1`                |
| `hour_slot`      | string           | yes      | `YYYY-MM-DDTHH`, UTC                   |
| `merkle_root`    | string \| null   | yes      | 64-char lowercase hex, or null if hour empty |
| `event_count`    | integer          | yes      | length of `events`                     |
| `events`         | array of objects | yes      | leaf entries, see below                |
| `leaves`         | array of objects | yes      | alias of `events`, identical contents  |
| `tree_levels`    | array of arrays  | yes      | level-by-level hash listing            |
| `build_time`     | string           | yes      | RFC 3339 UTC, when the manifest was emitted |
| `submission_time`| string           | no       | RFC 3339 UTC, written by anchor pipeline |
| `calendar_responses` | object       | no       | OTS calendar URL → `"ok"` or error string |
| `prev_hour_root` | string \| null   | no       | reservation slot, see §"prev_hour_root reservation" |

`events` and `leaves` carry the same payload. `events` is the legacy
key that the verify-CLI reads; `leaves` matches the aggregator-side
naming and is documented here so independent implementations have a
single name to refer to. New consumers should accept either; new
producers must write both.

## Event entry shape

Every entry in `events` / `leaves` carries the four B1-consensus
fields plus the recomputable leaf hash:

| field                   | type   | required | notes                          |
| ----------------------- | ------ | -------- | ------------------------------ |
| `event_id`              | string | yes      | stable identifier from Wirelang|
| `time`                  | string | yes      | RFC 3339 timestamp             |
| `payload_hash`          | string | yes      | 64-char lowercase hex          |
| `capability_token_hash` | string | yes      | 64-char lowercase hex; empty string allowed for non-capability events |
| `leaf_hash`             | string | yes      | 64-char lowercase hex; SHA-256 of JCS-canonicalised four-tuple |

The four B1 fields are the input to the leaf-hash function; storing
the resulting `leaf_hash` in the manifest is redundant by design.
External verifiers should recompute it from the four fields and
compare — a mismatch flags either a corrupt manifest or an
implementation drift between writer and reader.

### Leaf hash

```
leaf_hash = SHA-256( JCS({
    "event_id":              <string>,
    "time":                  <string>,
    "payload_hash":          <string>,
    "capability_token_hash": <string>
}) )
```

JCS is RFC 8785; the canonical form sorts keys and emits no
whitespace. The reference implementation uses Trail of Bits' `rfc8785`
PyPI package; an in-tree minimal canonicaliser is documented as a
fallback in `wat/merkle/aggregator.py`.

## Tree levels

`tree_levels` records the post-padding hash list at every level of
the Merkle tree, bottom-up. `tree_levels[0]` is the leaf level (which
may include a duplicated trailing leaf if the original count was
odd); `tree_levels[-1]` is a single-element list holding the Merkle
root.

This level dump is included in the manifest so an offline auditor
can sanity-check the root without re-running the JCS canonicaliser
over every event. Independent verifiers must still recompute the
root from the leaves to detect tampering with `tree_levels`.

## Encoding conventions

- Hash and digest fields are encoded as lowercase hexadecimal strings
  with no `0x` prefix and no separator.
- All timestamps are RFC 3339 with a `Z` suffix denoting UTC.
- Field order in the JSON file is informative only; consumers must
  parse by key name.
- The on-disk JSON is pretty-printed (two-space indent) for human
  inspection. Verifiers must not assume canonical JSON at the
  manifest layer; only the leaf-hash inputs are JCS-canonicalised.

## Empty hours

If the input spool for an hour contains zero events, the manifest is
still written, but with:

- `merkle_root` set to `null`
- `event_count` set to `0`
- `events`, `leaves`, `tree_levels` all set to `[]`
- no `root.bin` and no `root.bin.ots` written
- the anchor pipeline skipped (no OTS submission)

This keeps the archive structurally consistent (one directory per
hour, including silent ones) without anchoring an all-zero or
placeholder root that would force a verify-time special case.

## prev_hour_root reservation

`prev_hour_root` is reserved in v1 as an **optional** field with
`null` as its default. Its purpose, formalised in v2, is to chain
adjacent hours together: each hour's manifest carries the root of the
preceding hour, so an auditor verifying a contiguous range can walk
the chain forward without re-fetching every intermediate manifest in
parallel.

| version                       | semantics of `prev_hour_root`                              |
| ----------------------------- | ---------------------------------------------------------- |
| `wakir-wat-manifest/v1`       | optional. Default `null`. Writers MAY emit it; readers MUST tolerate it. No verification semantics — a v1 verifier ignores the value. |
| `wakir-wat-manifest/v2` (Phase-1b) | required. Must equal the previous hour's `merkle_root` (or `null` for the first anchored hour, or for the hour immediately following an empty hour). Verifiers running in `--chain-check` mode fail if the chain breaks. |

Reserving the slot in v1 lets the aggregator start writing it now,
so by the time the v2 verifier ships there is already historical
chain data to walk. Writing it is harmless because v1 verifiers
ignore unknown-semantics fields and the field is optional in their
schema.

### `--chain-check` flag

The verify CLI (`wakir-verify`) gains an optional `--chain-check` flag
in v2: when set, the verifier walks `prev_hour_root` backward from
the target hour and confirms each link matches. The flag is opt-in
because chain-walking requires access to every manifest in the
range, which is not the default verifier use case. Phase-1a verifiers
do not support the flag; the flag is documented here so writers can
populate the field consistently from day one.

## Forward compatibility

`version` is the schema version, not the implementation version. A
later `wakir-wat-manifest/v2` may add fields that current verifiers
do not understand; verifiers MUST tolerate unknown top-level fields
and MUST NOT fail a manifest solely because its version differs from
their built-in.

Likely v2 additions (non-binding, for context):

- a `proof_extension_slot` field carrying a zero-knowledge inclusion
  proof produced by a future companion module;
- the `prev_hour_root` slot reserved in v1 (see "prev_hour_root
  reservation" above) graduates to a required field, with `--chain-
  check` enforcement in the verifier;
- a `signer` block recording the agent identity that produced the
  manifest, signed with the AIP-document key from the identity
  substrate (Phase 1a, day 4).

These are all additive; the v1 fields and their semantics will not
be changed retroactively.

## Reference implementations

- Writer: `wat.cmd.aggregator_cli` (`wakir-merkle build` subcommand).
- Reader: `wat.verify.cli` (`wakir-verify` console script).
- Hash core: `wat.merkle.aggregator`.

The on-disk format described above is the contract; the source code
is the implementation. If the two ever disagree, this document is
authoritative for v1.
