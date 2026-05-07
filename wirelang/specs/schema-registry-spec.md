<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

---
spec: wirelang-schema-registry
version: 0.3.0
status: draft
date: 2026-05-07
audience: implementers, integrators, operators
license: CC-BY-4.0
---

# Wirelang Schema Registry — NATS-KV Backend Specification (v0.3.0)

**Change log**

| Version | Date       | Change                                                 |
|---------|------------|--------------------------------------------------------|
| 0.1.0   | 2026-05-07 | Initial draft (Phase-1b Sprint-3 Tag-1).               |
| 0.2.0   | 2026-05-07 | Phase-1c CAS-pin contract reclassified from Phase-2 to Phase-1c and lands in Tag-3 (`put_with_revision` / `get_with_revision` / `SchemaRegistryConflictError`); §5.3 Phase-1c-Slot consumed; §5.4 added. Additive-only change relative to v0.1.0; M-2 / M-4 conformance preserved. |
| 0.3.0   | 2026-05-07 | Phase-1c watch-stream surface lands in Tag-4 (`watch()` / `WatchOp` / `WatchEvent` / `LiveSchemaSnapshot` / `open_watch_stream`); §5.3 OI-7-Phase-1c-watch slot CONSUMED; §5.5 added (watch-stream operational contract); §6.2 added (T-SR-WS-01..10 + 2 aux probes test inventory). Additive-only change relative to v0.2.0; M-2 / M-4 conformance preserved. |

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

**Phase-1b Sprint-3 Tag-3 (additive over Tag-1):**

- The CAS-pin upsert path
  (`NatsKvSchemaRegistry.put_with_revision` /
  `get_with_revision`) — Phase-1c reclassification of the Tag-1
  Phase-2 reservation, lands here as
  **OI-7-Phase-1c-CAS** (consumed).
- The `SchemaRegistryConflictError` typed exception for lost-update
  rejection.
- 8-12 hermetic determinism tests for the CAS-pin path
  (T-SR-CAS-01..10).

**Phase-1b Sprint-3 Tag-4 (this revision, additive over Tag-3):**

- The watch-stream surface
  (`NatsKvSchemaRegistry.watch()` / `open_watch_stream` /
  `WatchOp` / `WatchEvent` / `LiveSchemaSnapshot`) — pattern-mirror
  on V-908 Tag-6 watch-stream-snapshot layer, lands here as
  **OI-7-Phase-1c-watch** (consumed).
- The synchronous verifier surface (`InMemorySchemaRegistry.lookup`)
  is UNCHANGED. The watch-stream is a *consumer* surface that feeds
  a `LiveSchemaSnapshot`; verifier passes consume frozen
  `InMemorySchemaRegistry` views taken via `as_registry()`.
- Poisoned envelopes on the stream raise
  `SchemaRegistryEnvelopeError` and terminate the iterator (no
  silent envelope poison; same contract as full snapshot).
- 8-12 hermetic determinism tests for the watch-stream path
  (T-SR-WS-01..10 + aux probes).

**Phase-1c (still out of scope, reserved):**

- The publisher CLI that pushes module-shipped schemas onto the
  bucket on operator command (**OI-7-Phase-1c-publisher** reserved).
- Cross-bucket schema replication for multi-region clusters
  (**OI-7-Phase-1c-replication** reserved).

**Phase-2 (out of scope here):**

- CAS-quorum upserts on top of multi-replica clusters (extension of
  the Tag-3 single-replica CAS-pin to replicated clusters).
- Schema-deprecation policy with overlapping-validity windows.
- IPFS-anchored schema-document hashes.
- Envelope-side signature with AIP-id-tied `registered_by`.

The reserved Phase-1c items above are tracked as
**OI-7-Phase-1c-publisher / -watch / -replication** in the Phase-1b
backlog; the Phase-2 items as **OI-7-Phase-2-quorum / -deprecation /
-ipfs / -sig**. Tag-3 consumes the **OI-7-Phase-1c-CAS** slot only;
the other three Phase-1c slots remain reserved.

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
    async def get_with_revision(                         # Phase-1c (Tag-3)
        self, key: str
    ) -> Optional[tuple[SchemaRegistryEntry, int]]: ...
    async def put(self, entry: SchemaRegistryEntry) -> int: ...
    async def put_with_revision(                         # Phase-1c (Tag-3)
        self, entry: SchemaRegistryEntry, expected_revision: int
    ) -> int: ...
    async def delete(self, key: str) -> None: ...
    async def list_keys(self) -> list[str]: ...
    async def snapshot(self) -> InMemorySchemaRegistry: ...
    async def watch(self) -> _SchemaWatchStreamHandle: ...   # Phase-1c (Tag-4)
```

The Tag-4 watch-stream additions also expose:

```python
class WatchOp(enum.Enum):                                # Phase-1c (Tag-4)
    PUT = "PUT"
    DELETE = "DELETE"
    PURGE = "PURGE"

@dataclass(frozen=True)
class WatchEvent:                                        # Phase-1c (Tag-4)
    op: WatchOp
    key: str
    entry: Optional[SchemaRegistryEntry]
    revision: int

@dataclass
class LiveSchemaSnapshot:                                # Phase-1c (Tag-4)
    initial: InMemorySchemaRegistry
    last_revision: int = 0

    def apply(self, event: WatchEvent) -> None: ...
    def as_registry(self) -> InMemorySchemaRegistry: ...

    @classmethod
    async def from_backend(cls, backend) -> "LiveSchemaSnapshot": ...

async def open_watch_stream(backend) -> _SchemaWatchStreamHandle: ...
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

### 5.3 What Phase-1b Sprint-3 Tag-1 + Tag-3 + Tag-4 covers, and what Phase-1c / Phase-2 still does NOT do

**Tag-1 (v0.1.0) lands:**

- Async `get`/`put`/`delete`/`list_keys`/`snapshot` against a
  NATS-KV bucket.
- Synchronous `InMemorySchemaRegistry` view with bijective
  triple↔key derivation.
- 12 hermetic determinism tests (T-SR-01..10 + 2 aux probes).

**Tag-3 (v0.2.0) lands (additive over Tag-1):**

- Async `put_with_revision(entry, expected_revision)` for CAS-pinned
  upsert. Lost-update protection contract enforced through the
  underlying NATS-KV `update(key, value, last=expected_revision)`
  call. Conflict surfaces as `SchemaRegistryConflictError` carrying
  the observed `key`, `expected_revision`, and (when available)
  `actual_revision`.
- Async `get_with_revision(key) → Optional[(entry, revision)]` as the
  read pair: callers pass the returned revision back into
  `put_with_revision` to close the CAS loop.
- 8-12 additional hermetic determinism tests (T-SR-CAS-01..10).
- The same write-time validation gates from §5.2 run on the CAS-pin
  path BEFORE the revision-pin call. CAS does NOT relax envelope
  integrity.
- **OI-7-Phase-1c-CAS slot consumed.**

**Tag-4 (v0.3.0) lands (additive over Tag-3):**

- Async `watch() → _SchemaWatchStreamHandle` exposing decoded
  `WatchEvent` instances over the bucket. Adapter compatibility
  with two underlying watcher shapes: nats-py canonical `watchall()`
  yielding a Shape-2 watcher (`await updates()` returning next or
  None) and the alternative Shape-1 native async-iter watcher.
- `WatchOp` enum (`PUT` / `DELETE` / `PURGE`) and `WatchEvent`
  dataclass (`op` / `key` / `entry` / `revision`) carry the decoded
  operation kind, key, entry (None for DELETE/PURGE), and KV revision.
- `LiveSchemaSnapshot` keeps an in-memory copy of the registry
  (bootstrapped from `NatsKvSchemaRegistry.snapshot`), applies
  `WatchEvent` deltas via `apply()`, and hands out frozen
  `InMemorySchemaRegistry` copies via `as_registry()` for verifier
  passes. Determinism contract: a frozen copy does NOT mutate when
  subsequent watch events arrive.
- `open_watch_stream(backend)` is the entry-point; `backend.watch()`
  is the convenience wrapper.
- 8-12 additional hermetic determinism tests (T-SR-WS-01..10 + aux).
- A poisoned envelope on a `PUT` watch event raises
  `SchemaRegistryEnvelopeError` and terminates the iterator. An
  unknown `operation` kind raises the same typed error. Phase-1c
  does NOT silently swallow envelope poison on the stream.
- **OI-7-Phase-1c-watch slot consumed.**

**Phase-1c still does NOT include (remaining reserved slots):**

- No publisher CLI that pushes module-shipped schemas onto the
  bucket on operator command (`OI-7-Phase-1c-publisher` reserved).
- No cross-bucket schema replication for multi-region clusters
  (`OI-7-Phase-1c-replication` reserved).
- No watch-stream resume-from-revision policy (Phase-2 concern;
  nats-py supports it via `watchall(..., resume_from=...)`, but the
  Phase-1c stream wrapper does not bake in resume policy).

**Phase-2 still does NOT include:**

- No CAS-quorum upserts on top of multi-replica clusters (Tag-3
  CAS-pin assumes the operator's `replicas: 1` Phase-1 setup; the
  contract holds bit-equally on a multi-replica bucket but is not
  exercised at the test layer).
- No envelope-side signature (`OI-7-Phase-2-sig` reserved).
- No deprecation policy (`OI-7-Phase-2-deprecation` reserved).
- No IPFS-anchored schema hashes (`OI-7-Phase-2-ipfs` reserved).

### 5.4 CAS-pin operational contract (Tag-3)

The CAS-pin contract is the canonical compare-and-swap idiom.

**Read-modify-write loop:**

```python
read = await registry.get_with_revision("schemas/wire/layer-1-wire/0.1.0")
if read is None:
    raise NotFoundError(...)
entry, observed_revision = read

new_body = mutate(entry.schema_body)
new_entry = SchemaRegistryEntry(
    layer=entry.layer,
    name=entry.name,
    version=entry.version,
    schema_id=entry.schema_id,
    schema_body=new_body,
    schema_body_sha256=schema_body_sha256(new_body),
    registered_at=now_utc(),
    registered_by=entry.registered_by,
    supersedes=entry.supersedes,
)

try:
    new_revision = await registry.put_with_revision(
        new_entry, observed_revision
    )
except SchemaRegistryConflictError as exc:
    # Re-read and retry; or surface to the operator.
    ...
```

**Validation gate ordering (REQUIRED):**

1. Envelope `schema_id ↔ schema_body.$id` (gate 1, §5.2 / Tag-1).
2. Envelope `schema_body_sha256` ↔ recomputed JCS-anchored hash
   (gate 2, §5.2 / Tag-1).
3. Triple-derived key matches the entry (gate 3, §5.2 / Tag-1).
4. NATS-KV `update(key, value, last=expected_revision)` call;
   raises a backend-specific `KeyWrongLastSequenceError` if the live
   revision has advanced. The Tag-3 backend translates that into
   `SchemaRegistryConflictError`.

Gates 1-3 run BEFORE gate 4 so a malformed envelope cannot poison
the bucket even if the revision happened to be stale. Gate 4 runs
LAST so the network call only happens for envelopes that have
already passed integrity checks.

**KV adapter contract:**

The backend supports three KV adapter shapes (mock-friendliness):

- `kv.update(key, value, last=revision)` — canonical nats-py shape
  (KeyValue.update; raises KeyWrongLastSequenceError on conflict).
- `kv.update(key, value, expected_revision)` — positional fallback
  for mocks that don't accept the `last` keyword.
- `kv.put(key, value, expected_revision=...)` — keyword fallback for
  mocks that overload `put`.

Conflict detection is class-name-based: any exception whose class
name carries one of `WrongLastSequence` / `Conflict` /
`RevisionMismatch` is translated into
`SchemaRegistryConflictError`. This matches nats-py 2.x as well as
the orchestrator-side mock JetStream surface.

**Determinism contract (Tag-3 invariant):**

- Successful CAS-pin on the same `(key, expected_revision)` from two
  different callers: exactly one succeeds; the other receives a
  `SchemaRegistryConflictError`. The accepted writer's revision is
  monotonically greater than `expected_revision`.
- Any sequence of CAS-pins that all observe consistent revisions
  composes into a deterministic bucket state regardless of operator
  interleaving.
- A `SchemaRegistryConflictError` is **never** raised AFTER the
  envelope-integrity gates fail; the envelope-integrity gates run
  first and raise their own typed errors.

### 5.5 Watch-stream operational contract (Tag-4)

The watch-stream contract is the canonical incremental-view idiom for
long-running supervisors. It mirrors the V-908 Tag-6 watch-stream
pattern shipped in `wirelang/federation/route_registry_nats_kv_backend.py`.

**Bootstrap-and-apply loop:**

```python
backend = NatsKvSchemaRegistry(kv=kv_handle)

# 1. Take a full snapshot to bootstrap the in-memory view.
live = await LiveSchemaSnapshot.from_backend(backend)

# 2. Open the watch-stream and apply incoming events.
async with await backend.watch() as stream:
    async for event in stream:
        live.apply(event)
        if some_external_trigger:
            # Hand a frozen view to a verifier pass.
            frozen = live.as_registry()
            verify_with_registry(frozen)
```

**Event kinds:**

- `WatchOp.PUT`: a new or updated schema entry. The `WatchEvent.entry`
  field carries the decoded `SchemaRegistryEntry`. `LiveSchemaSnapshot.apply`
  inserts or replaces the entry.
- `WatchOp.DELETE`: an explicit tombstone on the bucket key. The
  `WatchEvent.entry` field is `None`. `LiveSchemaSnapshot.apply`
  removes the key from the live state (no-op if already absent).
- `WatchOp.PURGE`: a history-clearing purge on the key. Treated
  identically to DELETE for live-state purposes; surfaced separately
  so audit consumers can distinguish a purge from a tombstone.

**Adapter contract:**

The backend supports three watcher adapter shapes:

- nats-py canonical: `await kv.watchall()` returning a Shape-2 watcher
  (`await updates()` yielding next or `None` for end-of-stream).
- Shape-1 fallback: a native async-iter watcher (`__aiter__` /
  `__anext__`) raising `StopAsyncIteration` at end-of-stream.
- nats-py end-of-initial-replay sentinel (`None` between snapshot
  replay and live tail) is filtered out at the handle layer; consumers
  do NOT see it.

**Decoder contract (REQUIRED gate ordering on each event):**

1. Read `operation` attribute (or `Mapping["operation"]`); reject
   missing / unknown values with `SchemaRegistryEnvelopeError`.
2. Read `key` attribute (or `Mapping["key"]`); reject empty /
   non-string keys with `SchemaRegistryEnvelopeError`.
3. Read `revision` attribute (or `Mapping["revision"]`); coerce to
   `int` (default `0` if missing).
4. For `PUT`: decode `value` bytes through `_envelope_to_entry`
   (re-runs the Tag-1 envelope codec gates; a poisoned envelope
   surfaces `SchemaRegistryEnvelopeError`). For `DELETE` / `PURGE`:
   `entry` is `None`, no value-decode.

**Determinism contract (Tag-4 invariant):**

- A frozen `InMemorySchemaRegistry` returned from
  `LiveSchemaSnapshot.as_registry` does NOT mutate when subsequent
  `apply()` calls arrive. Verifier passes that hold a frozen view
  observe a stable point-in-time snapshot.
- `LiveSchemaSnapshot.last_revision` advances monotonically: an
  event with a revision lower than the current `last_revision` does
  NOT regress the counter (out-of-order or duplicate events do not
  corrupt the high-water mark).
- A poisoned envelope on a `PUT` event raises
  `SchemaRegistryEnvelopeError` from the iterator; the consumer must
  drop the `LiveSchemaSnapshot` and re-bootstrap from a fresh
  `NatsKvSchemaRegistry.snapshot`. Phase-1c does NOT attempt
  partial-recovery on the stream.

**Phase-1c boundary:**

- The watch-stream is a *consumer* surface; it does NOT replace
  `snapshot()`. Verifier passes always consume frozen
  `InMemorySchemaRegistry` views; the watch-stream is the *producer*
  of those views, not a new verifier substrate.
- Watch-stream resume-from-revision is a Phase-2 concern; the Tag-4
  wrapper exposes `WatchEvent.revision` so callers can implement
  resume policies on top, but the wrapper itself does not bake in
  any resume contract.
- Multi-watch federation (one supervisor watching multiple buckets,
  e.g. routes + schemas) is an integrator concern; each backend
  exposes its own `watch()` and the integrator composes them.

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

### 6.1 CAS-pin tests (Tag-3, additive over Tag-1)

Phase-1b Sprint-3 Tag-3 ships hermetic CAS-pin tests at
`wirelang/tests/test_schema_registry_cas_pin.py`. Inventory
T-SR-CAS-01..10 plus T-SR-CAS-aux probes:

- **T-SR-CAS-01:** `get_with_revision` round-trips an entry through
  `put_with_revision` (entry equality + revision monotonic).
- **T-SR-CAS-02:** `get_with_revision` on an unknown key returns
  `None` (no exception, mirrors `get` for absent keys).
- **T-SR-CAS-03:** `put_with_revision` succeeds when the
  `expected_revision` matches the live revision.
- **T-SR-CAS-04:** `put_with_revision` raises
  `SchemaRegistryConflictError` when the live revision has advanced
  (concurrent writer landed first). The error carries the observed
  `key`, `expected_revision`, and `actual_revision`.
- **T-SR-CAS-05:** Validation gate 1 (`schema_id` ↔ `$id`) runs
  BEFORE the CAS call; mismatch raises
  `SchemaRegistryValidationError` and the bucket revision does NOT
  advance.
- **T-SR-CAS-06:** Validation gate 2 (`schema_body_sha256`) runs
  BEFORE the CAS call; mismatch raises `SchemaRegistryValidationError`
  and the bucket revision does NOT advance.
- **T-SR-CAS-07:** `put_with_revision` rejects a negative
  `expected_revision` with `ValueError` (defence in depth).
- **T-SR-CAS-08:** Two interleaved CAS-pin loops on the same key:
  exactly one succeeds, the other receives
  `SchemaRegistryConflictError` with `actual_revision >
  expected_revision` (lost-update protection contract).
- **T-SR-CAS-09:** A successful `put_with_revision` followed by a
  non-CAS `put` is observable: the non-CAS `put` wins
  (last-write-wins for the LWW path; CAS-pin and LWW remain orthogonal).
- **T-SR-CAS-10:** A KV adapter without an `update` method falls
  through to `put(key, value, expected_revision=...)`; if the
  adapter does not accept that keyword either, the backend raises
  `SchemaRegistryBackendError` ("CAS-pin not supported"), not a
  silent demotion to LWW.

Auxiliary probes:

- **T-SR-CAS-aux-determinism:** ten back-to-back interleaved CAS-pin
  pairs over a single key yield a deterministic outcome: exactly
  five winners, five conflicts; the final revision is exactly five
  more than the starting revision (one increment per accepted
  writer).
- **T-SR-CAS-aux-conflict-class-detection:** the class-name marker
  detection (`_is_conflict_exception`) recognises
  `KeyWrongLastSequenceError`, `RevisionMismatchError`, and
  `KeyValueConflictError` and rejects unrelated exceptions like
  `ValueError`.

Total Tag-3 test additions: 10 primary CAS-pin tests + 2 auxiliary
probes = 12.

### 6.2 Watch-stream tests (Tag-4, additive over Tag-3)

Phase-1b Sprint-3 Tag-4 ships hermetic watch-stream tests at
`wirelang/tests/test_schema_registry_watch_stream.py`. Inventory
T-SR-WS-01..10 plus T-SR-WS-aux probes:

- **T-SR-WS-01:** `watch()` opens a stream and yields one decoded
  `WatchEvent` per upsert; events carry the correct `op` (`PUT`),
  `key`, `entry`, and `revision`.
- **T-SR-WS-02:** a DELETE on the bucket surfaces a DELETE
  `WatchEvent`; the `entry` field is `None`.
- **T-SR-WS-03:** `LiveSchemaSnapshot.from_backend` bootstraps from
  a full snapshot; subsequent `apply(PUT)` updates the live state.
  An entry present in the bootstrap is preserved.
- **T-SR-WS-04:** `LiveSchemaSnapshot.apply(DELETE)` removes the
  key from the live state.
- **T-SR-WS-05:** A frozen `InMemorySchemaRegistry` returned from
  `as_registry()` does NOT mutate when subsequent `apply()` calls
  arrive. The frozen copy preserves the entry-set at the moment of
  the call. (Determinism contract, the Tag-4 invariant for verifier
  passes.)
- **T-SR-WS-06:** A poisoned watch update (non-JSON `value` on
  `PUT`) raises `SchemaRegistryEnvelopeError` from the iterator and
  terminates the stream.
- **T-SR-WS-07:** An update with an unrecognised `operation` kind
  raises `SchemaRegistryEnvelopeError`.
- **T-SR-WS-08:** `LiveSchemaSnapshot.last_revision` advances
  monotonically with each applied event; an out-of-order earlier-
  revision event does NOT regress the counter.
- **T-SR-WS-09:** A frozen registry from a watch-fed `LiveSchemaSnapshot`
  exposes `lookup` / `lookup_by_triple` / `keys_sorted` consistent
  with a fresh full-bucket snapshot from `backend.snapshot()`. Cross-
  reference T-SR-05 (full snapshot path).
- **T-SR-WS-10:** `open_watch_stream` rejects a non-`NatsKvSchemaRegistry`
  argument with `TypeError`.

Auxiliary probes:

- **T-SR-WS-aux-async-iter:** the watch handle is async-iter
  compatible with the Shape-1 (native `__aiter__` / `__anext__`)
  watcher mock. The nats-py end-of-initial-replay `None` sentinel is
  filtered at the handle layer (consumers do NOT see it).
- **T-SR-WS-aux-purge-removes:** a `WatchOp.PURGE` event removes the
  key from the live state identically to `DELETE`.

Total Tag-4 test additions: 10 primary watch-stream tests + 2
auxiliary probes = 12.

## 7. Cross-references and Open-Items

- V-908 backend pattern source:
  `wirelang/federation/route_registry_nats_kv_backend.py`.
- V-908 conflict-error pattern source:
  `RouteRegistryConflictError` in the same module (Tag-3 mirror).
- V-908 watch-stream pattern source: Tag-6 `WatchOp` / `WatchEvent` /
  `LiveSnapshot.from_backend` / `_MockWatcher` in the same module
  (Tag-4 mirror).
- Bucket inventory source:
  `scripts/init-nats-buckets.py` `PHASE_1_BUCKETS[0]` (`wakir-schemas`).
- **Phase-1c CAS-pin: OI-7-Phase-1c-CAS — CONSUMED in Tag-3.**
- **Phase-1c watch-stream: OI-7-Phase-1c-watch — CONSUMED in Tag-4.**
- Phase-1c publisher CLI: **OI-7-Phase-1c-publisher** (reserved).
- Phase-1c cross-bucket replication: **OI-7-Phase-1c-replication**
  (reserved).
- Phase-2 CAS-quorum: **OI-7-Phase-2-quorum** (reserved).
- Phase-2 envelope signature: **OI-7-Phase-2-sig** (reserved).
- Phase-2 deprecation policy: **OI-7-Phase-2-deprecation** (reserved).
- Phase-2 IPFS schema-hash: **OI-7-Phase-2-ipfs** (reserved).

## 8. Compatibility statement

The Phase-1b registry is purely additive relative to Phase-1a /
Phase-1b Sprint-2: no on-disk loader is removed, no verifier module
is forced to switch to the registry. Verifiers that already load
schemas via `importlib.resources` continue to function unchanged.
The registry is a **production-target substrate** that Phase-2
deployment will switch to; Phase-1b Sprint-3 Tag-1 lands the
substrate, Tag-3 hardens it with the CAS-pin path. The cutover
itself is still Phase-2.

**Tag-3 (v0.2.0) is additive relative to Tag-1 (v0.1.0):**

- All Tag-1 surfaces (`get` / `put` / `delete` / `list_keys` /
  `snapshot` / `get_by_triple`) remain unchanged. Their
  contracts are preserved byte-equal.
- The Tag-3 additions (`get_with_revision` / `put_with_revision` /
  `SchemaRegistryConflictError`) are NEW surfaces. Callers that do
  not need lost-update protection continue to use `put` (LWW); they
  are not forced onto the CAS-pin path.
- M-2 conformance (additive-only schema evolution): Tag-3 adds no
  new envelope fields and modifies no existing field. The on-the-wire
  envelope schema remains `wakir.wirelang.schema-registry-entry/1`.
- M-4 conformance (multi-version-aware registry): Tag-3 is orthogonal
  to the version axis; CAS-pin operates on a single key
  (`schemas/<layer>/<name>/<version>`) and does not depend on whether
  multiple versions are simultaneously active.
- Spec semver bump 0.1.0 → 0.2.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive).

**Tag-4 (v0.3.0) is additive relative to Tag-3 (v0.2.0):**

- All Tag-1 + Tag-3 surfaces remain unchanged. Tag-4 introduces
  no breaking change to `get` / `put` / `delete` / `list_keys` /
  `snapshot` / `get_by_triple` / `get_with_revision` /
  `put_with_revision`. Their contracts are preserved byte-equal.
- The Tag-4 additions (`watch` / `WatchOp` / `WatchEvent` /
  `LiveSchemaSnapshot` / `open_watch_stream`) are NEW surfaces.
  Callers that do not need an incremental view continue to take
  full snapshots; they are not forced onto the watch-stream path.
- M-2 conformance (additive-only schema evolution): Tag-4 adds no
  new envelope fields and modifies no existing field. The on-the-wire
  envelope schema remains `wakir.wirelang.schema-registry-entry/1`.
  Watch events carry the same envelope bytes as a full-snapshot
  read; the decoder is shared (`_envelope_to_entry`).
- M-4 conformance (multi-version-aware registry): Tag-4 is orthogonal
  to the version axis; the watch-stream surfaces `WatchEvent` per
  bucket key (`schemas/<layer>/<name>/<version>`) and does not depend
  on whether multiple versions are simultaneously active. A
  `LiveSchemaSnapshot` materialises the same multi-version-aware
  `InMemorySchemaRegistry` as the full-snapshot path.
- The synchronous verifier surface (`InMemorySchemaRegistry.lookup`
  / `lookup_by_triple` / `keys_sorted`) is unchanged. Verifier
  modules that already consume frozen `InMemorySchemaRegistry`
  views continue to function unchanged when the producer is a
  `LiveSchemaSnapshot.as_registry()` instead of `backend.snapshot()`.
- Spec semver bump 0.2.0 → 0.3.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive).

— End of spec —
