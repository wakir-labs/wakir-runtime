<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

---
spec: wirelang-schema-registry
version: 0.1.0
status: draft
date: 2026-05-07
audience: implementers, integrators, operators
license: CC-BY-4.0
---

# Wirelang Schema Registry — NATS-KV Backend Specification (v0.1.0)

This specification defines the Wakir Wirelang **Schema Registry**: a
persistent, drift-aware store for the JSON-Schema documents that
validate Wirelang frames, AIP documents, FTD documents and the
Datalog caveat vocabulary. The registry's persistent substrate is a
single NATS-JetStream key-value bucket (`wakir-schemas`); the
registry's runtime API is a synchronous lookup contract analogous to
the V-908 `RouteRegistry` Protocol shipped in Phase-1b Sprint-2.

The registry is the natural consumer of Kai's Phase-1 NATS-KV
inventory `wakir-schemas` bucket (`scripts/init-nats-buckets.py`,
Phase-1b Sprint-2 Tag-2). Phase-1b Sprint-3 Tag-1 lands the
production-target backend wrapper; Phase-1c will land the
schema-distribution flow that publishes module-shipped schemas onto
the bucket on operator command.

## 1. Scope and motivation

### 1.1 Why a registry

Phase-1b ships seven on-disk JSON-Schema documents in
`wirelang/schemas/`:

1. `aip-document.json`               — AIP identity document
2. `datalog-caveat.json`             — Datalog caveat vocabulary
3. `federation-trust-document.json`  — V-908 FTD shape
4. `layer-0-transport.json`          — Layer 0 transport envelope
5. `layer-1-wire.json`               — Layer 1 wire frame
6. `layer-2-semantic.json`           — Layer 2 semantic frame
7. `layer-3-capability-token.json`   — Layer 3 capability-token wrap

These documents are loaded by verifier modules (e.g.
`wirelang.identity.verify_bridge`) via `importlib.resources` at
process start. The on-disk form is fine for in-process use, but it
does not scale to the Phase-2 production fleet:

- Multiple agents need the *same* schema document; without a single
  source of truth, divergence between agent containers is silent.
- Operators must roll out new schema versions atomically across
  agents; an on-disk roll-out is per-container and observably
  asynchronous.
- Audit consumers want a byte-anchorable artefact per schema; an
  on-disk file in a container image is not a stable reference.

The registry surfaces a single bucket-backed source of truth with
explicit version slots, drift detection at the test layer, and a
JCS-canonical envelope that is byte-stable for audit anchoring.

### 1.2 Phase boundaries

**Phase-1b Sprint-3 Tag-1 (this document):**

- The NATS-KV backend wrapper module.
- The on-the-wire **value envelope** schema and codec.
- The deterministic snapshot bridge (analogous to V-908
  `NatsKvRouteRegistry.snapshot`).
- 8–12 hermetic determinism tests against an in-memory mock KV.
- Bucket-config drift-test against Kai's `wakir-schemas` inventory
  entry (cross-reference test).

**Phase-1c (out of scope here):**

- The publisher CLI that pushes module-shipped schemas onto the
  bucket on operator command.
- The watch-stream consumer that materialises a `LiveSnapshot`-like
  registry for long-running supervisors.
- Cross-bucket schema replication for multi-region clusters.

**Phase-2 (out of scope here):**

- CAS-revision-pinned upserts (anti-clobber under concurrent edits).
- Schema-deprecation policy with overlapping-validity windows.
- IPFS-anchored schema-document hashes.

The Phase-1c and Phase-2 items are reserved as **OI-7-Phase-2..4**
in the Phase-1b backlog; this document does not implement them.

## 2. Bucket identity (cross-reference Kai inventory)

The registry uses bucket name `wakir-schemas`, already documented in
`scripts/init-nats-buckets.py` (`PHASE_1_BUCKETS[0]`). The Phase-1b
configuration is:

| Field            | Value         | Rationale                                                  |
|------------------|---------------|------------------------------------------------------------|
| `name`           | `wakir-schemas` | Phase-1 inventory entry; do not rename.                  |
| `description`    | `"Wirelang schema registry cache (Phase-1)"` | Operator-facing.       |
| `history`        | `5`           | Audit-trail of recent overwrites; matches federation-routes. |
| `ttl_seconds`    | `0`           | Schemas have no expiry; superseded entries stay for audit. |
| `max_value_size` | `262_144` (256 KiB) | Largest current schema is ~7.3 KiB; 256 KiB headroom for v0.2 expansion. |
| `storage`        | `"file"`      | Durability for production.                                 |
| `replicas`       | `1`           | Phase-1 single-node; Phase-2 multi-node will raise.        |

**Drift contract** (identical to the V-908 backend):

The registry backend does NOT auto-create or auto-correct bucket
configuration. It expects an operator-run `init-nats-buckets` to
have established the bucket before any `NatsKvSchemaRegistry` is
constructed. A `BUCKET_CONFIG` constant in the backend module is the
single source of truth for the test-layer drift check; the
operator-side drift check lives in the orchestrator script.

**Cross-Review-Memo to Kai:** the registry adds NO new bucket to the
Phase-1 inventory (the `wakir-schemas` bucket is already in Kai's
4-bucket inventory). Kai's 5th bucket (`wakir-federation-routes`,
Tag-4 Sprint-2) is paired Z-B-update; Sprint-3 Tag-1 does NOT add a
6th bucket. The registry is a *consumer* of the existing inventory
slot; the only Kai-side acknowledgement requested is a paired-update
note in the bucket-inventory cross-reference for Tag-1's
"`wakir-schemas` is consumed by Wirelang schema-registry backend"
documentation surface.

## 3. Identity model

A registry **entry** is identified by a triple `(layer, name,
version)` collapsed into a single KV key string:

```
schemas/<layer>/<name>/<version>
```

Examples:

```
schemas/identity/aip-document/0.1.0
schemas/wire/layer-1-wire/0.1.0
schemas/wire/layer-3-capability-token/0.1.0
schemas/federation/datalog-caveat/0.2.0
schemas/federation/federation-trust-document/0.1.0
```

The `<layer>` axis groups schemas by Wirelang concern (`identity`,
`wire`, `federation`); `<name>` is the kebab-case schema slug
matching the on-disk file basename (without `.json`); `<version>`
is the semver-like Wirelang schema version embedded in the
`$id` URI.

### 3.1 Phase-1b schema inventory (registry-side)

The Phase-1b registry recognises the following entries (the eight
slots cover the seven on-disk schemas plus one v0.2.0 slot for
`datalog-caveat` which was promoted to Phase-2 in Tag-15 of
Phase-1b daily build):

| Layer        | Name                          | Version  | On-disk basename                       |
|--------------|-------------------------------|----------|----------------------------------------|
| `identity`   | `aip-document`                | `0.1.0`  | `aip-document.json`                    |
| `wire`       | `layer-0-transport`           | `0.1.0`  | `layer-0-transport.json`               |
| `wire`       | `layer-1-wire`                | `0.1.0`  | `layer-1-wire.json`                    |
| `wire`       | `layer-2-semantic`            | `0.1.0`  | `layer-2-semantic.json`                |
| `wire`       | `layer-3-capability-token`    | `0.1.0`  | `layer-3-capability-token.json`        |
| `federation` | `datalog-caveat`              | `0.1.0`  | (Phase-1a archive; no on-disk file in Phase-1b) |
| `federation` | `datalog-caveat`              | `0.2.0`  | `datalog-caveat.json`                  |
| `federation` | `federation-trust-document`   | `0.1.0`  | `federation-trust-document.json`       |

Eight slots total. The `datalog-caveat/0.1.0` slot is reserved (no
on-disk file ships in Phase-1b; the entry is registered to make the
versioning surface explicit and to give Phase-1c a slot for
historical replay).

### 3.2 Versioning policy

Wirelang schema versions follow the same semver-like discipline as
the wirelang spec itself (see `wirelang-spec-v0-2.md` §1.1):

- **Patch** (`x.y.Z`) — clarification, no shape change. New entry,
  same `(layer, name)`; previous patch becomes superseded but stays
  in the bucket history (`history=5`).
- **Minor** (`x.Y.0`) — additive shape change (new optional fields).
  New entry. Verifiers select the highest minor compatible with the
  frame's declared version.
- **Major** (`X.0.0`) — breaking change. New entry. Phase-1b does NOT
  perform automatic major migration; consumers select major
  explicitly.

**Phase-1b boundary:** the registry does NOT enforce schema
super-/sub-set compatibility between versions. That is a Phase-2
hardening item (OI-7-Phase-2 reserved slot).

## 4. Value envelope

Each KV entry is a JSON object with these fields:

```json
{
  "schema": "wakir.wirelang.schema-registry-entry/1",
  "layer": "<layer>",
  "name": "<name>",
  "version": "<version>",
  "schema_id": "https://wakir.dev/wirelang/schema/<name>/<version>",
  "schema_body": { ... full JSON-Schema document ... },
  "schema_body_sha256": "<hex>",
  "registered_at": "<RFC 3339 UTC>",
  "registered_by": "<role-string or aip-id>",
  "supersedes": "<key-string of previous patch entry, or null>"
}
```

Field semantics:

- `schema`: envelope schema URI fragment, fixed for Phase-1b at
  `wakir.wirelang.schema-registry-entry/1`. Drift gate; mismatched
  envelopes fail at decode.
- `layer` / `name` / `version`: identity triple, copies of the KV
  key components for self-contained reads.
- `schema_id`: the `$id` URI of the JSON-Schema document. MUST match
  the document's own `$id` field; this is verified at write time.
- `schema_body`: the full JSON-Schema document, embedded verbatim.
  Producers MUST canonicalise the body via JCS (RFC 8785) before
  embedding so the byte form is reproducible.
- `schema_body_sha256`: SHA-256 of the JCS-canonicalised
  `schema_body` bytes. Allows callers to byte-verify a fetched
  schema against an external anchor (e.g., a WAT manifest) without
  re-canonicalising.
- `registered_at`: write-time UTC timestamp.
- `registered_by`: the agent / role that wrote the entry. Phase-1b
  permits a free-form string (role-string per Brand-Guide §9 or
  AIP-id of the publishing agent); Phase-2 will tighten this to an
  AIP-id with a verified signature.
- `supersedes`: the key-string of the entry this one supersedes, or
  `null` for the first version of a `(layer, name)` pair. Allows a
  consumer to walk the supersession chain backwards.

JCS is REQUIRED for the embedded `schema_body` bytes (so the SHA-256
anchor is meaningful) but not for the envelope itself. The envelope
is stored with `sort_keys=True, separators=(",", ":")` so the bytes
are reproducible per caller; this is sufficient for in-bucket reads.

## 5. Backend API

The Phase-1b Sprint-3 Tag-1 backend module ships at
`wirelang/schemas/registry_nats_kv_backend.py`. The API mirrors the
V-908 `route_registry_nats_kv_backend` shape:

```python
@dataclass
class NatsKvSchemaRegistry:
    kv: Any
    bucket_name: str = BUCKET_NAME

    async def get(self, key: str) -> Optional[SchemaRegistryEntry]: ...
    async def get_by_triple(
        self, layer: str, name: str, version: str
    ) -> Optional[SchemaRegistryEntry]: ...
    async def put(self, entry: SchemaRegistryEntry) -> int: ...
    async def delete(self, key: str) -> None: ...
    async def list_keys(self) -> list[str]: ...
    async def snapshot(self) -> InMemorySchemaRegistry: ...
```

The `InMemorySchemaRegistry` class is a synchronous read-only view
mirroring the V-908 in-memory pattern: it exposes a `lookup(key)`
method and a `lookup_by_triple(layer, name, version)` method, both
returning `Optional[SchemaRegistryEntry]`.

### 5.1 Determinism contract

Two snapshots taken back-to-back against the same bucket state MUST
yield byte-equal `InMemorySchemaRegistry` views (entry-set is the
same; entry envelopes round-trip byte-stable through the envelope
codec). This contract is enforced by T-SR-01 / T-SR-determinism.

### 5.2 Validation gates at write

The `put` method enforces, at write time:

1. The envelope's `schema_id` field MUST equal the embedded
   `schema_body.$id` (mismatch → `SchemaRegistryEnvelopeError`).
2. The envelope's `schema_body_sha256` field MUST equal the SHA-256
   of the JCS-canonicalised `schema_body` (mismatch → error).
3. The KV key string derived from `(layer, name, version)` MUST
   match the entry's identity triple (defence in depth against
   accidental mis-keying).

These gates protect the determinism contract: a poisoned or
mis-anchored envelope cannot reach the bucket through the typed
backend.

### 5.3 What Phase-1b does NOT do

- No CAS-revision-pinned upsert (`put_with_revision` reserved for
  Phase-2; OI-7-Phase-2 slot).
- No watch-stream surface (Phase-1c; OI-7-Phase-1c slot).
- No automatic schema-document loading from the on-disk
  `wirelang/schemas/` tree (publisher CLI is Phase-1c; the backend
  here is the *transport* surface, not the *publisher*).
- No envelope-side signature (Phase-2 with AIP-id-tied
  `registered_by`; OI-7-Phase-2 slot).

## 6. Test inventory

Phase-1b Sprint-3 Tag-1 ships hermetic tests at
`wirelang/tests/test_schema_registry_nats_kv_backend.py`. Inventory
T-SR-01..10 plus T-SR-aux probes:

- **T-SR-01:** `put` round-trips an entry through `get` (single-key
  semantics, identity-triple preserved).
- **T-SR-02:** `get` on an unknown key returns `None`.
- **T-SR-03:** `put` is last-write-wins for the same key.
- **T-SR-04:** `delete` removes an entry; subsequent `get` is `None`.
- **T-SR-05:** `snapshot` materialises an `InMemorySchemaRegistry`
  with all live entries.
- **T-SR-06:** a poisoned (non-JSON) value raises
  `SchemaRegistryEnvelopeError` from `get` and aborts `snapshot`.
- **T-SR-07:** envelope `schema` mismatch is rejected.
- **T-SR-08:** envelope `schema_id` ≠ `schema_body.$id` is rejected
  at write time.
- **T-SR-09:** envelope `schema_body_sha256` mismatch is rejected at
  write time.
- **T-SR-10:** bucket-config constants match the documented Phase-1
  inventory (drift-protection at the test layer).
- **T-SR-aux-determinism:** two back-to-back snapshots yield
  byte-equal `InMemorySchemaRegistry` keysets.
- **T-SR-aux-key-derivation:** `(layer, name, version)` ↔ key-string
  derivation is bijective.

Total: 10 primary determinism tests + 2 auxiliary probes = 12.

## 7. Cross-references and Open-Items

- V-908 backend pattern source:
  `wirelang/federation/route_registry_nats_kv_backend.py`.
- Bucket inventory source:
  `scripts/init-nats-buckets.py` `PHASE_1_BUCKETS[0]` (`wakir-schemas`).
- Phase-1c publisher CLI: **OI-7-Phase-1c** (reserved).
- Phase-2 CAS-revision pin: **OI-7-Phase-2** (reserved).
- Phase-2 envelope signature: **OI-7-Phase-2-sig** (reserved).
- Phase-2 deprecation policy: **OI-7-Phase-2-deprecation** (reserved).

## 8. Compatibility statement

The Phase-1b registry is purely additive relative to Phase-1a /
Phase-1b Sprint-2: no on-disk loader is removed, no verifier module
is forced to switch to the registry. Verifiers that already load
schemas via `importlib.resources` continue to function unchanged.
The registry is a **production-target substrate** that Phase-2
deployment will switch to; Phase-1b Sprint-3 Tag-1 lands the
substrate, not the cutover.

— End of spec —
