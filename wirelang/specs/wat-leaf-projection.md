<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Callandor GmbH and contributors

Licensed under the Creative Commons Attribution 4.0 International
License. Full text: https://creativecommons.org/licenses/by/4.0/
-->

# WAT Leaf Projection from Wirelang Layer-1 Frames — Specification

Version: `wakir-wat-leaf-projection/v1`
Status: stable for Phase 1a.
Audience: Wirelang Layer-1 producers (NATS bridges, agent runtimes)
and WAT aggregator consumers.

This document specifies how a Wirelang Layer-1 frame is projected onto
the four-field WAT leaf tuple consumed by `wat.merkle.aggregator.compute_leaf_hash`.
It is the bridge contract between two modules under separate licences:
Wirelang (Apache-2.0) produces the frames; the WAT leaf projection is
a value-derivation contract, not a transformation of WAT-internal
state, and is therefore documented under CC-BY-4.0 as part of the
Wirelang spec corpus.

## 1. Scope

A Wirelang Layer-1 frame is a CloudEvents 1.0 envelope plus eight
Wakir-reserved extension attributes (`wirelang/schemas/layer-1-wire.json`).
The WAT leaf is a four-string tuple aggregated hourly into a Bitcoin-
pattern Merkle tree. The projection MUST be deterministic: given the
same frame, every conformant implementation MUST produce the same
four-tuple bytes.

The projection is one-way. The leaf-tuple is sufficient to detect
tampering with a frame's identity, time, payload, or capability use,
but not to reconstruct the frame.

## 2. Four-field B1 tuple

Per the cross-review-zone-2 consensus marker (commit `338e007`,
OpenTimestamps `918a79b`):

| field                   | type   | source in Layer-1 frame              |
| ----------------------- | ------ | ------------------------------------ |
| `event_id`              | string | `id`                                 |
| `time`                  | string | `time`                               |
| `payload_hash`          | string | `SHA-256(JCS(data))`, hex-lower      |
| `capability_token_hash` | string | `caprefs[0]` payload, or empty string |

The tuple is then JCS-canonicalised (RFC 8785) and SHA-256-hashed by
`compute_leaf_hash` to yield the 32-byte leaf digest. The hash is the
sole identity of the leaf in the tree; the tuple itself is stored in
the manifest for offline verification.

## 3. Field-by-field projection rules

### 3.1 `event_id`

Set to the Layer-1 `id` field verbatim. Wakir convention is UUIDv7
(time-ordered, hash-stable lexicographic sort). The projection does
not validate or rewrite `id` — empty strings, malformed UUIDs, and
arbitrary non-empty strings are accepted at this layer; upstream
schema validation is the producer's job.

### 3.2 `time`

Set to the Layer-1 `time` field verbatim. The Layer-1 schema requires
RFC 3339 (`format: date-time`) and Wakir frames MUST set this even
though CloudEvents marks it OPTIONAL. The projection does not
re-normalise the timestamp: a frame with `2026-05-06T12:00:00Z` and
a frame with `2026-05-06T12:00:00.000Z` will project to two distinct
leaf tuples and therefore two distinct leaf hashes. This is the
intended invariant — the audit-trail records the bytes as observed,
not a re-canonicalised echo.

### 3.3 `payload_hash`

Defined as:

```
payload_hash = hex_lower( SHA-256( JCS( frame.data ) ) )
```

The hash function is SHA-256 (FIPS 180-4 / RFC 6234). The
canonicalisation function is JCS (RFC 8785), which sorts object keys
lexicographically and emits no whitespace. Hex encoding is lowercase
with no `0x` prefix and no separator (`64-char [0-9a-f]+`).

`frame.data` is the CloudEvents `data` slot — the Wirelang Layer-2
semantic payload validated by `schemaid`+`schemaversion`. The hash is
computed over the deserialised JSON value, not over the raw bytes
that arrived on the wire; producers and consumers MUST agree on this
distinction so a wire-level whitespace change does not invalidate the
manifest.

#### 3.3.1 Empty `data`

A frame MAY have no semantic payload. Two cases are distinguished:

- `data` is the empty object `{}` → `JCS({})` is `{}` (two bytes), and
  `payload_hash` is the SHA-256 of those two bytes:
  `44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a`.
- `data` is absent (the key is not present in the JSON envelope) →
  the projection treats this identically to `data: {}`. The intent is
  to keep the leaf shape stable; agents that wish to record "no
  payload" as a distinct outcome from "empty payload" SHOULD use a
  different `schemaid`, not a missing-vs-empty `data` distinction.

This rule is normative for the projection. Layer-2 validators MAY
reject an absent `data` for some `schemaid`s; that rejection happens
upstream and never reaches the projection.

### 3.4 `capability_token_hash`

Defined as:

- if `caprefs` is absent or empty: empty string `""`.
- if `caprefs` has one entry: that entry's hash payload, hex-lower.
- if `caprefs` has multiple entries: the **first** entry, hex-lower.

The `caprefs` schema (Layer-1) constrains entries to the form
`sha256:<64-char-hex>`. The projection strips the `sha256:` prefix
and forwards the 64-char hex tail. The empty-string sentinel for
absent `caprefs` is the same value `compute_leaf_hash` accepts as a
non-capability event (`wat/merkle/aggregator.py` docstring).

#### 3.4.1 Multi-capability frames — which capability comes first?

Layer-1 allows a frame to carry multiple capability tokens (e.g. a
delegation chain or a multi-scope action). The projection commits to
the **first entry** of `caprefs` for the leaf tuple. Rationale:

- Producers control `caprefs` ordering. The first entry is the
  capability the agent is *primarily* invoking; subsequent entries
  are typically attenuating delegations or co-scoped tokens.
- A future `wakir-wat-leaf-projection/v2` MAY introduce a multi-cap
  representation (e.g. concatenated hashes, Merkle-of-caps, or a
  separate audit-trail leaf per capability). The v1 single-token
  rule is forward-compatible: a v2 reader can inspect the whole
  `caprefs` list when it has the original frame, and the v1 leaf
  hash remains valid as a *first-cap* commitment.
- Producers that need to bind multiple capabilities into the audit
  trail right now SHOULD emit one frame per capability and let the
  Merkle tree aggregate them naturally.

This is a **commitment**, not just an implementation detail. Changing
the rule (e.g. switching to "last entry" or "lexicographic minimum")
breaks every previously-anchored receipt. v2 must be additive.

#### 3.4.2 AIP-Document hash hook (Phase-1b sketch, non-normative for v1)

Status: **non-normative sketch for Phase-1b**. v1 leaf projection is
unchanged by this subsection.

A capability token's `aip_refs[]` field (Capability-Token-Layer §2.E,
wirelang-eng Tag-23 vector pin pack) carries one or more
`sha256:<64-char-hex>` references to AIP-Documents that authenticate
the token issuer. Phase-1b will likely want to commit a single
`aip_document_hash` field into the leaf projection so that the audit
trail records *which issuer-document was in force at frame-emission
time* without requiring the receipt verifier to fetch the
AIP-Document over the network.

Possible Phase-1b additions, all subject to a v2 wirelang spec bump
and wat-leaf-projection v2:

- **Option A — fifth tuple field**: extend the four-field B1 tuple
  to a five-field B2 tuple `(event_id, time, payload_hash,
  capability_token_hash, aip_document_hash)`. Strongest binding,
  largest spec break.
- **Option B — separate audit-trail leaf**: emit a second
  `wat.aip-document-anchor` leaf type per frame, with its own
  one-shot tuple `(event_id, aip_document_hash)`. Requires a leaf
  type discriminator at the Merkle layer (currently single-type).
- **Option C — bind into payload_hash**: include `aip_document_hash`
  in the payload-hash JCS canonicalisation step. Simplest, but
  silently re-defines what "payload" means and conflicts with the
  Layer-2 `data` semantics.

wirelang-eng Tag-23 + wat-eng 2.E-Ack defer the choice to Phase-1b.
The Tag-25 Phase-1b-tracking-doc Item I-13 captures the discussion. v1 leaf
projection treats `aip_refs[]` as **out-of-scope** at the leaf layer:
the field is carried by the capability token itself and is
recoverable by a receipt verifier that has the original frame.

The first-entry-wins discipline of §3.4.1 carries forward to any
v2 `aip_document_hash` derivation: if `aip_refs[]` has multiple
entries, the v2 projection MUST commit to `aip_refs[0]` for
compatibility with the v1 capability-token-hash precedent.

Empty-sentinel treatment (wirelang-eng 2.E-Ack 2026-05-06): a frame
whose capability-token has empty `aip_refs[]` projects
`aip_document_hash` to the empty string `""` under v2, mirroring the
§3.4 empty-`caprefs` treatment. This keeps the v1 → v2 migration byte-stable for frames
without AIP-Document binding.

## 4. Examples

### 4.1 Minimal frame — capability action

Frame (excerpt):

```json
{
  "specversion": "1.0",
  "type": "wakir.treasury.read",
  "source": "did:web:wakir.dev:treasury-agent",
  "id": "01HK4P8X3W2N5Q9V0R6T7S8YZ2",
  "time": "2026-05-06T12:01:30Z",
  "schemaid": "wakir.treasury.read",
  "schemaversion": "0.1.0",
  "actorrole": "treasury-operator",
  "agentid": "treasury-agent-001",
  "caprefs": [
    "sha256:deadbeef12345678deadbeef12345678deadbeef12345678deadbeef12345678"
  ],
  "data": {
    "action": "read.balance",
    "wallet": "wakir-treasury-eoa-phase-1",
    "amount_usd_cents": 12500
  }
}
```

Projects to:

| field                   | value                                                              |
| ----------------------- | ------------------------------------------------------------------ |
| `event_id`              | `01HK4P8X3W2N5Q9V0R6T7S8YZ2`                                       |
| `time`                  | `2026-05-06T12:01:30Z`                                             |
| `payload_hash`          | `b0b0f6cf24bfc58adbc163c9e1ac3a4c4590b2ee79fae18dec71a1e83eda5718` |
| `capability_token_hash` | `deadbeef12345678deadbeef12345678deadbeef12345678deadbeef12345678` |

This is `vector-2-typical-frame.json` in `tests/fixtures/jcs-leaf-vectors/`.

### 4.2 Announcement frame — no capability token

A frame that carries no capability (e.g. an unauthenticated public
announcement) sets `capability_token_hash` to the empty string:

| field                   | value                                                              |
| ----------------------- | ------------------------------------------------------------------ |
| `event_id`              | `01HK4P8X3W2N5Q9V0R6T7S8YZ3`                                       |
| `time`                  | `2026-05-06T12:02:15Z`                                             |
| `payload_hash`          | `f5cc2bd8539bab52b640f67993975645010dea80c7092bab400cd442c4664247` |
| `capability_token_hash` | `""` (empty string)                                                |

This is `vector-3-no-capability-token.json`.

## 5. Edge cases — summary

| case                              | rule                                       |
| --------------------------------- | ------------------------------------------ |
| `data` absent or `{}`             | `payload_hash` = SHA-256 of `JCS({})`      |
| `caprefs` absent or empty array   | `capability_token_hash` = `""`             |
| `caprefs` with one entry          | strip `sha256:` prefix, take the hex tail  |
| `caprefs` with N>1 entries        | first entry only (v1)                      |
| non-RFC-3339 `time`               | accepted verbatim — projection is byte-faithful |
| empty `id`                        | accepted — Layer-1 schema enforces `minLength:1` upstream |

## 6. Forward compatibility

`wakir-wat-leaf-projection/v2` is reserved. Anticipated additions:

- a multi-capability digest scheme (Merkle-of-caps or concatenated
  hashes) that supersedes the first-cap-wins rule;
- a `payload_hash` variant that accepts non-JSON Layer-2 payloads
  (e.g. CBOR or protobuf) by moving canonicalisation into the
  Layer-2 module rather than fixing it at JCS-of-JSON;
- a `time_normalisation` flag that allows producers to opt into
  RFC-3339 re-canonicalisation if the byte-faithful default
  produces too many false positives in audits.

All v2 changes will be opt-in by `wirelangversion`; v1 frames anchored
under the rules above remain valid forever.

## 7. Reference implementation

- Hash core: `wat.merkle.aggregator.compute_leaf_hash`
  (BSL-1.1, see `wat/LICENSE-BSL.md`).
- Test vectors: `tests/fixtures/jcs-leaf-vectors/` (Apache-2.0, five
  vectors covering the cases in §5).
- Related specs:
  - `docs/wat-hash-spec.md` — cross-domain JCS+SHA-256 contract.
  - `docs/wat-spool-spec.md` — JSONL hour-spool format that carries
    the projected fields plus audit metadata.
  - `docs/wat-manifest-spec.md` — hourly manifest format that exposes
    the four projection fields plus the recomputable `leaf_hash`.
