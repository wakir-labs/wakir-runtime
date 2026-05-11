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
| `prev_hour_root` | string \| null   | no (v1) / yes (v2) | hex root of the preceding hour, or null at chain boundaries; see "Manifest versions v1 / v2 — chain semantics" |

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

## Manifest versions v1 / v2 — chain semantics

`prev_hour_root` chains adjacent hours: each hour's manifest carries
the root of the preceding hour, so an auditor verifying a contiguous
range can walk the chain backward without trusting any intermediate
manifest in isolation. Two manifest versions are defined:

| version                            | `prev_hour_root` slot | `--chain-check` flag (verify CLI) |
| ---------------------------------- | ---------------------------- | ---------------------------------- |
| `wakir-wat-manifest/v1` (Phase-1a) | **optional**, default `null` | **opt-in** — `--chain-check` exists, off by default |
| `wakir-wat-manifest/v2` (Phase-1b) | **required** (`null` only for legitimate edge cases — see below) | **default-on** — chain check runs unless explicitly disabled |

### v1 (Phase-1a) — current behaviour

- The `prev_hour_root` field is **optional** at the manifest layer.
  Writers SHOULD emit it (default `null` when no parent exists);
  readers MUST tolerate both presence and absence.
- The verify CLI accepts `--chain-check` as an **opt-in flag**. When
  set, it walks one step back through `prev_hour_root` and compares
  the value against the previous hour's `merkle_root`.
- A v1 verifier without `--chain-check` performs the inclusion proof
  and OTS check only and ignores `prev_hour_root` entirely.
- Legacy v1 manifests written before the always-emit aggregator fix
  may lack the `prev_hour_root` key altogether. A `--chain-check`
  verifier MUST treat a missing key as `chain-skipped`, not as an
  error.

The opt-in design is deliberate: chain-walking requires access to
the previous-hour archive, which is not always co-located with the
target hour (selective replication, offline audit, single-event spot
checks). Forcing chain-check would break those use cases.

### v2 (Phase-1b) — planned behaviour

- The `prev_hour_root` field becomes **required**. Aggregators MUST
  emit it for every hour. `null` remains valid only at well-defined
  boundaries (genesis hour, post-gap restart — see edge cases).
- The verify CLI runs `--chain-check` by default. A new `--no-chain-
  check` flag re-enables the v1-style inclusion-proof-only mode for
  cases where the previous-hour manifest is intentionally unavailable.
- A v2 verifier reading a v1 manifest behaves as in v1: the `--chain-
  check` decision is honoured per-flag, missing keys are tolerated.

### Verification behaviour matrix

| manifest version           | `prev_hour_root` value | `--chain-check` (v1 / v2 default) | result            |
| -------------------------- | ---------------------- | ----------------------------------- | ----------------- |
| v1 or v2                   | absent (key missing)   | off                                 | `verified` (chain not consulted) |
| v1 or v2                   | absent (key missing)   | on                                  | `verified`, `chain_status=chain-skipped` |
| v1 or v2                   | `null`                 | off                                 | `verified` |
| v1 or v2                   | `null`                 | on                                  | `verified`, `chain_status=chain-skipped` |
| v1 or v2                   | hex root, prev exists, matches  | off                        | `verified` |
| v1 or v2                   | hex root, prev exists, matches  | on                         | `verified`, `chain_status=chain-verified` |
| v1 or v2                   | hex root, prev exists, mismatches | on                       | `chain-mismatch`, exit code 4 |
| v1 or v2                   | hex root, prev manifest missing | on                         | `chain-mismatch`, exit code 4 |
| v2 (writer side, not verify) | absent                | n/a                                 | aggregator MUST refuse to emit; v2 writers always emit the slot |

Exit codes follow the verify-CLI contract: `0` verified, `1` failed,
`3` pending (OTS not yet finalised on Bitcoin), `4` chain-mismatch
(introduced Tag-8 alongside the opt-in flag).

### Edge cases

- **Genesis hour.** The first anchored hour of an audit trail has no
  predecessor. Aggregators emit `prev_hour_root: null`. Verifiers
  treat this as `chain-skipped`, not as an error, in both v1 and v2.
- **Empty hour.** An hour with zero events writes a manifest with
  `merkle_root: null` and emits no `root.bin`. The next hour's
  `prev_hour_root` is set to `null` rather than chaining over the
  empty hour — there is no root to chain. A non-empty hour following
  an empty hour is therefore a legitimate `chain-skipped` boundary.
- **Hour gap.** If the aggregator was offline and an hour has no
  manifest at all, the next emitted hour records `prev_hour_root:
  null`. The gap itself is not silently bridged. A `--chain-check`
  verifier reports `chain-skipped` rather than walking across the
  gap. (Mira default-decision, Tag-8: no walk-back across gaps.
  A separate Phase-1b feature may add explicit gap markers.)
- **Mismatched chain.** A non-null `prev_hour_root` that does not
  equal the previous hour's `merkle_root` is the only chain-state
  that yields `chain-mismatch` and exit code 4. The inclusion proof
  for the current hour may still be valid; chain-mismatch is
  reported as an audit-trail integrity event in addition to the
  proof outcome.
- **Legacy manifest (no `prev_hour_root` key).** Treated identically
  to `prev_hour_root: null`: `chain-skipped`. This keeps pre-Tag-8
  archives verifiable with a current `--chain-check` verifier
  without any backfill.

### v1 → v2 migration

The transition from v1 to v2 is **additive at the writer side and
default-flip at the reader side**:

- v1 → v2 writer: bump the `version` field to `wakir-wat-manifest/v2`
  and refuse to emit a manifest without `prev_hour_root`. No new
  fields are added; the v1 reservation slot becomes required.
- v1 → v2 reader: flip `--chain-check` to default-on; introduce
  `--no-chain-check` for opt-out.
- Backfill: existing v1 manifests that already carry
  `prev_hour_root` (per the always-emit aggregator path shipped at
  Tag-8) need no rewrite. v1 manifests that lack the key can be
  read by v2 verifiers as `chain-skipped` indefinitely; an offline
  backfill tool to compute and inject the missing values is a
  Phase-1b deliverable, not a v2-prerequisite.

The version bump does not invalidate v1 manifests. A v2 verifier
reads v1 manifests with v1 semantics (per the matrix above), and a
v1 verifier ignores any v2-only fields per the forward-compatibility
rule below.

## Forward compatibility

`version` is the schema version, not the implementation version. A
later `wakir-wat-manifest/v2` may add fields that current verifiers
do not understand; verifiers MUST tolerate unknown top-level fields
and MUST NOT fail a manifest solely because its version differs from
their built-in.

Likely v2 additions (non-binding, for context):

- a `proof_extension_slot` field carrying a zero-knowledge inclusion
  proof produced by a future companion module;
- the `prev_hour_root` slot transitions from optional-with-`null`-
  default to required-with-default-on `--chain-check` (specified in
  detail under "Manifest versions v1 / v2 — chain semantics" above);
- a `signer` block recording the agent identity that produced the
  manifest, signed with the AIP-document key from the identity
  substrate (Phase 1a, day 4).

These are all additive; the v1 fields and their semantics will not
be changed retroactively.

## Production signing (Phase-2 Sprint-6 Tag-3)

The aggregator emits an Ed25519 detached signature on the hour-
manifest when both `--sign-key` and `--sign-kid` are supplied. The
signature is written as an optional top-level `signature` slot on
the same envelope; older v1 verifiers ignore the slot per the
forward-compatibility rule, newer verifiers consume it via
`wakir-verify --verify-signature ...`.

The signature block shape is byte-identical to the AIP-document
and schema-registry-entry signing conventions:

```json
"signature": {
  "alg": "Ed25519",
  "kid": "<kid-string, references AIP-document public_keys[].kid>",
  "signature": "<128-char hex; 64-byte Ed25519 signature>"
}
```

Canonical pre-image: SHA-256 of `rfc8785.dumps(manifest_without_signature)`.
The slot is stripped from a deep copy before canonicalisation so
the signature cannot be part of its own pre-image.

The `--sign-key` argument is a path to a file containing the
64-char hex-encoded 32-byte Ed25519 raw seed (trailing newline
tolerated). The `--sign-kid` argument is a non-empty string that
the operator binds to an AIP-document `public_keys[]` entry under
the `wat-anchor` purpose; the kid is captured in the signature
block for the verifier-side resolver path
(`wat.identity.anchor_kid.resolve_wat_anchor_kid`).

Both flags must be supplied together; partial configuration is
rejected with exit code 2 so a half-edited cron does not silently
emit unsigned manifests.

### End-to-end example (Phase-2 Sprint-6 Tag-4)

The end-to-end demonstration script
`scripts/wat-e2e-aggregator-signed-tv2.py` ties the production-side
signing to the verifier-side signature-status gate. It replays the
TV-2 real-manifest cohort through `build_command(... sign_key=...,
sign_kid=...)`, copies the original `root.bin` / `root.bin.ots`
side-files into the staging directory byte-for-byte, then runs
`verify_real_manifest_file(verify_signature=True, ...)` against the
aggregator-signed output and asserts
`signature_status == "verified"` on every hour:

```text
$ .venv/bin/python scripts/wat-e2e-aggregator-signed-tv2.py
[2026-05-27T00] rows=5 merkle_match=True fields=True integrity=True
                ots=True signature_status=verified verdict=OK
[2026-05-27T01] rows=5 merkle_match=True fields=True integrity=True
                ots=True signature_status=verified verdict=OK
[2026-05-27T02] rows=5 merkle_match=True fields=True integrity=True
                ots=True signature_status=verified verdict=OK
[2026-05-27T03] rows=5 merkle_match=True fields=True integrity=True
                ots=True signature_status=verified verdict=OK
---
end-to-end verdict: OK
```

The CI counterpart is `tests/wat/test_e2e_aggregator_signed_tv2.py`
(five tests: one per-hour-parametrised plus one cohort-wide). The
script's `--keep-staging` flag preserves the temp directory for
post-mortem inspection. Exit code is 0 iff every hour passes every
gate (fields + integrity + ots-anchor + signature) AND every
rebuilt `merkle_root` matched the fixture's (the deterministic-sort
contract from Tag-3).

## Reference implementations

- Writer: `wat.cmd.aggregator_cli` (`wakir-merkle build` subcommand).
- Reader: `wat.verify.cli` (`wakir-verify` console script).
- Hash core: `wat.merkle.aggregator`.

The on-disk format described above is the contract; the source code
is the implementation. If the two ever disagree, this document is
authoritative for v1.
