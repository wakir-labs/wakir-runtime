<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Callandor GmbH and contributors

Licensed under the Creative Commons Attribution 4.0 International
License. Full text: https://creativecommons.org/licenses/by/4.0/
-->

# WAT Hour-Spool — Format Specification

Version: `wakir-wat-spool/v1`
Status: stable for Phase 1a.
Audience: bridge implementers (Wirelang Layer-0 → spool writers) and
aggregator operators reading the spool with `wakir-merkle build`.

The hour-spool is the on-disk staging format between the Wirelang
Layer-1 frame stream and the WAT hourly Merkle aggregator. One file
per UTC hour, JSON-Lines, append-only until the hour is sealed.

## 1. File layout

```
<spool>/YYYY-MM-DDTHH.jsonl          # open (current hour, late-frame window)
<spool>/YYYY-MM-DDTHH.jsonl.sealed   # sealed (hour boundary + 5min passed)
```

Hour slots are UTC. Local time is never used. The spool directory
`<spool>` is configured per-deployment; the aggregator CLI accepts it
via `--spool-dir`.

A bridge process writes one event per line to the open file. After
the UTC hour boundary plus a 5-minute late-frame window has elapsed,
the bridge atomically renames the file to the `.sealed` suffix
(`rename(2)`-equivalent on the same filesystem). Once sealed, the
file is read-only; subsequent late frames for that hour are
discarded with an operator-visible warning.

## 2. Line format — 9-field tuple

Each line is a JSON object with the following shape:

```json
{
  "event_id":              "01HK4P8X3W2N5Q9V0R6T7S8YZ2",
  "time":                  "2026-05-06T12:01:30Z",
  "payload_hash":          "<64-char hex>",
  "capability_token_hash": "<64-char hex or empty>",
  "source":                "did:web:wakir.dev:treasury-agent",
  "actorrole":             "treasury-operator",
  "agentid":               "treasury-agent-001",
  "schemaid":              "wakir.treasury.read",
  "schemaversion":         "0.1.0"
}
```

### 2.1 Hash-input fields (4)

These four fields are the input to `wat.merkle.aggregator.compute_leaf_hash`
per the leaf-projection spec (`wirelang/specs/wat-leaf-projection.md`):

| field                   | type   | notes                                       |
| ----------------------- | ------ | ------------------------------------------- |
| `event_id`              | string | from Layer-1 `id`                           |
| `time`                  | string | from Layer-1 `time`, RFC 3339, UTC          |
| `payload_hash`          | string | `SHA-256(JCS(frame.data))`, hex-lower       |
| `capability_token_hash` | string | first `caprefs` entry stripped, or empty   |

### 2.2 Audit-metadata fields (5)

These five fields are not hashed into the leaf but are written
through to the hourly manifest's per-event entries to support
post-hoc audit queries (e.g. "show all writes by `actorrole=treasury-
operator` in hour H" without re-fetching every original frame):

| field           | type   | notes                                       |
| --------------- | ------ | ------------------------------------------- |
| `source`        | string | Layer-1 `source` DID — sending agent        |
| `actorrole`     | string | Layer-1 `actorrole` — pseudonymised role    |
| `agentid`       | string | Layer-1 `agentid` — stable agent slug       |
| `schemaid`      | string | Layer-1 `schemaid` — semantic shape         |
| `schemaversion` | string | Layer-1 `schemaversion` — semver            |

Audit metadata is informational at the spool layer. Independent
verifiers MUST NOT depend on these fields for the integrity proof —
the integrity proof flows through the four hash-input fields and the
Merkle root only.

## 3. Hash pre-computation

`payload_hash` is computed by the **bridge** at frame-ingest time,
not by the aggregator. Rationale:

- the bridge has the live `frame.data` value and access to the same
  JCS canonicaliser the aggregator uses;
- pre-computation lets the aggregator stay a pure-aggregation tool
  (no JSON parsing of payloads, no schema-validation re-runs);
- the aggregator can be operated as a sealed offline tool against a
  spool produced by an arbitrary bridge implementation.

Bridges MUST use the contract documented in `docs/wat-hash-spec.md`
(JCS RFC 8785 → SHA-256 → hex-lower). Drift between bridge and
aggregator is detected by the test-vector pack in
`tests/fixtures/jcs-leaf-vectors/`, which is run from both module
test trees.

## 4. Re-ordering and sort

Lines in the spool MAY be written in any order. Real-world causes:

- multi-producer bridges with no global lock;
- back-pressured queues that flush out of arrival order;
- replay of a buffered batch after a transient bridge restart.

The aggregator (`wakir-merkle build`) is responsible for sorting at
build time. The canonical sort is **lexicographic on the 2-tuple
`(time, event_id)`**, ascending. Both fields are strings; both
default Python and standard JSON consumers sort lexicographically;
both Wakir conventions (RFC 3339 `Z`-suffixed timestamps and UUIDv7
event IDs) are designed for lexicographic sort to be time-ordered.

The sort is the only ordering guarantee. The Merkle-tree pairing
order, padding rules, and inclusion-proof construction are then
fully determined by `wat.merkle.aggregator.build_merkle_tree`.

## 5. Sealing — hour boundary plus 5-minute late window

A bridge MUST seal the hour-H spool no earlier than:

```
seal_at(H) = H_end + 5min  (UTC)
```

where `H_end` is the start of hour H+1. The 5-minute slack absorbs
clock skew, network jitter, and back-pressured publishes. Frames
arriving with `time` in hour H but observed at or after `seal_at(H)`
are dropped from spool H and recorded with a warning; they are NOT
re-routed to spool H+1, because the verifier proof is bound to the
recorded `time`.

Sealing is implemented as an atomic rename:

```
mv <spool>/YYYY-MM-DDTHH.jsonl <spool>/YYYY-MM-DDTHH.jsonl.sealed
```

The atomicity is required so the aggregator can detect "ready hours"
by listing `*.sealed` files without race conditions against the
bridge writer. Sealed files MUST NOT be reopened for append; if a
bridge needs to amend a sealed hour it MUST emit a compensating
event in the next-hour spool with a `schemaid` that the audit query
recognises as a correction.

## 6. Empty hours

A bridge MAY skip writing the spool entirely if hour H produced zero
frames. The aggregator treats a missing `*.sealed` file for an hour
as equivalent to an empty hour and emits the empty-hour manifest
documented in `docs/wat-manifest-spec.md` §"Empty hours".

## 7. Encoding conventions

- One event per line. Trailing newline on each line. Empty / blank
  lines are tolerated by the reference reader and skipped.
- UTF-8 throughout. Non-ASCII content (e.g. multi-byte UTF-8 in
  audit-metadata fields) is permitted and round-trips through JCS.
- Hash and digest fields are hex-lower, no `0x` prefix, no separator.
- Timestamps are RFC 3339 with a `Z` suffix denoting UTC.
- Filenames use `T` as the date-hour separator (matches manifest
  hour-slot encoding).

## 8. Reference implementation

- Reader (aggregator side): `wat.cmd.aggregator_cli` (`wakir-merkle build`).
- Hash core: `wat.merkle.aggregator.compute_leaf_hash`.
- Bridge: not yet shipped — Phase-1a-Tag-7 implementation per the
  tag-6 spec hand-off.
