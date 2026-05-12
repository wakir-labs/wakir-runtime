# `revocation-event-filter` — Operator Manpage

**Module:** `wirelang.schemas.capability_policy_nats_kv_backend`
**Public surface:** `RevocationEventKind`, `ClassifiedRevocationEvent`,
`RevocationEventClassifier`, `filter_revocation_events`
**Sprint:** Phase-2 Sprint-6 Tag-3 (consumer-side symmetry to the
Sprint-6 Tag-1 backend revocation-axis and the Sprint-6 Tag-2
publisher-CLI `revoke` subcommand)
**Bucket observed:** `wakir-capability-policies` (read-only watch-stream
consumer; this surface does NOT write)

---

## Purpose

This surface is the **consumer side** of the Phase-2 Sprint-6
capability-policy revocation axis. The earlier two halves of the axis
are write-side:

- **Sprint-6 Tag-1 (backend):** `CapabilityPolicy.revoked_at` +
  `revocation_reason` fields; `CapabilityPolicyRevocationConflict` on
  the CAS-pin write path; gate decisions of source
  `DecisionSource.POLICY_REVOKED` for `as_of >= revoked_at`.
- **Sprint-6 Tag-2 (publisher-CLI):** `wakir-schema-registry revoke`
  subcommand operator surface for applying a revocation (see
  `docs/publisher-cli-revoke.md`).

Tag-3 closes the asymmetry on the **audit-consumer side**. A downstream
observer watches the `wakir-capability-policies` bucket and needs to
answer **"WHICH watch-event was a revocation, and what kind?"** without
re-implementing the prior-state comparison logic per consumer. The
classifier owns that logic; this manpage describes its operator surface.

Three operator use-cases motivate the surface:

1. **BREACH-detection:** A `REVOCATION_MONOTONIC_BREACH` on the
   watch-stream is a witness of substrate corruption or out-of-band
   tampering (the backend-write invariants from Sprint-6 Tag-1 forbid
   apparent un-revokes and forbid advanced / retreated `revoked_at`
   instants on CAS-pin writes). Operators want an explicit signal, not
   a per-consumer ad-hoc comparison.
2. **Lineage-severing resilience after restart:** A consumer restarting
   from a backend snapshot needs the classifier's prior-state map
   seeded so the first watch-event for each pre-seeded key is NOT
   misclassified as a `REVOCATION_TRANSITION` (it would be, against an
   empty prior). The `seed_from_records(...)` bootstrap closes this.
3. **Audit-trail-narrow consumption:** Operators want to watch only
   the revocation-axis kinds (transitions, refreshes, breaches) and
   skip not-revocation-related PUTs and DELETE/PURGE removals. The
   async generator `filter_revocation_events` handles the filter
   without leaking state from the consumer.

---

## API surface

### `RevocationEventKind` (enum)

Five members, none ordered. Equality checks should be explicit
(`kind is RevocationEventKind.REVOCATION_TRANSITION`, not `==` to a
string).

| Member                          | Meaning                                                                                                                                                                    |
|---------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `NOT_REVOCATION_RELATED`        | PUT with `revoked_at=None` against an absent prior or an unrevoked prior. No revocation-axis content; filtered out by default.                                             |
| `REVOCATION_TRANSITION`         | PUT carrying `revoked_at != None` against an absent prior or an unrevoked prior. The *first* time the key carries a revocation instant.                                    |
| `REVOCATION_REFRESH`            | PUT carrying the same `revoked_at` instant as the prior revoked state (e.g. `revocation_reason` refreshed, `registered_at` advanced). Verifier-side gating unchanged.      |
| `REVOCATION_MONOTONIC_BREACH`   | PUT against a prior-revoked key that drops `revoked_at` to `None` (apparent un-revoke) OR carries a strictly different `revoked_at` instant (advance/retreat). Witness.    |
| `KEY_REMOVED`                   | DELETE or PURGE event. Classifier drops the key from its map; revocation lineage is severed by substrate-level hard removal. Filtered out by default.                      |

The classifier does NOT raise on `REVOCATION_MONOTONIC_BREACH`. It is
an **observation layer, not an enforcement layer**: it surfaces the
kind and advances its state to the new value; the consumer decides
the response (alert, halt, recovery).

### `ClassifiedRevocationEvent` (frozen dataclass)

Five fields:

| Field                          | Type                                          | Meaning                                                                                                                                                          |
|--------------------------------|-----------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `event`                        | `CapabilityPolicyWatchEvent`                  | The underlying watch event. NOT mutated or replaced; consumers can still apply it to a `LiveCapabilityPolicySnapshot` for the live-registry axis (orthogonal).   |
| `kind`                         | `RevocationEventKind`                         | The classification.                                                                                                                                              |
| `prior_revoked_at`             | `Optional[datetime]`                          | The `revoked_at` instant observed for this key BEFORE this event, or `None` if no prior state. Useful for audit consumers logging full state transitions.        |
| `current_revoked_at`           | `Optional[datetime]`                          | The `revoked_at` instant carried by THIS event's record. `None` for DELETE/PURGE, or for PUTs whose record has `revoked_at=None`.                                |
| `current_revocation_reason`    | `Optional[str]`                               | The `revocation_reason` carried by THIS event's record. `None` for DELETE/PURGE, or for PUTs whose record has `revocation_reason=None`.                          |

Frozen: a classifier returns a stable value per event; consumers can put
`ClassifiedRevocationEvent` into sets and use them as dict keys without
surprise.

### `RevocationEventClassifier` (stateful)

Per-key last-seen-`revoked_at` map. The map is the minimum state needed
to classify a new event: only the last-observed `revoked_at` instant
per key is retained, not the full record history.

| Method                                              | Returns                       | Effect                                                                                                                          |
|-----------------------------------------------------|-------------------------------|---------------------------------------------------------------------------------------------------------------------------------|
| `__init__()`                                        | —                             | Empty per-key map. Pure-Python value object; owns no async resources, performs no IO, safe without a running event loop.        |
| `seed_from_records(records: list)`                  | `None`                        | Seed the per-key map from a list of `CapabilityPolicyRecord` (e.g. `await backend.snapshot()`). Idempotent.                     |
| `classify(event: CapabilityPolicyWatchEvent)`       | `ClassifiedRevocationEvent`   | Classify one event. Side-effect: per-key map updated to reflect the event's effect.                                             |
| `known_keys()`                                      | `list[str]` (sorted)          | Keys the classifier has observed (membership probe).                                                                            |
| `last_revoked_at(key: str)`                         | `Optional[datetime]`          | Last-observed `revoked_at` instant for `key`, or `None`. NOTE: `None` is ambiguous between "never observed" and "unrevoked".    |

**Decision table** (the canonical specification of `classify`):

| `event.op`     | prior state      | incoming `revoked_at`  | resulting `kind`                  |
|----------------|------------------|------------------------|-----------------------------------|
| PUT            | absent           | `None`                 | `NOT_REVOCATION_RELATED`          |
| PUT            | absent           | non-`None`             | `REVOCATION_TRANSITION`           |
| PUT            | `None`           | `None`                 | `NOT_REVOCATION_RELATED`          |
| PUT            | `None`           | non-`None`             | `REVOCATION_TRANSITION`           |
| PUT            | non-`None`       | `None`                 | `REVOCATION_MONOTONIC_BREACH`     |
| PUT            | non-`None` X     | non-`None` X           | `REVOCATION_REFRESH`              |
| PUT            | non-`None` X     | non-`None` Y (Y ≠ X)   | `REVOCATION_MONOTONIC_BREACH`     |
| DELETE         | any              | N/A                    | `KEY_REMOVED`                     |
| PURGE          | any              | N/A                    | `KEY_REMOVED`                     |

After classification, the per-key map is updated:

- **PUT:** prior state := `record.policy.revoked_at`
- **DELETE / PURGE:** key removed from the map (severs the lineage).

**Concurrency:** single-consumer pattern in one asyncio task.
`classify` and `seed_from_records` are synchronous and mutate the
internal map; cross-task sharing requires caller-side locking.

**Defensive invariants:**

- `classify(non-CapabilityPolicyWatchEvent)` raises `TypeError`.
- `classify(PUT)` with `event.record is None` raises
  `CapabilityPolicyEnvelopeError` (this would not normally occur — the
  decoder rejects it earlier — but is re-asserted for defense in depth).
- `seed_from_records(non-CapabilityPolicyRecord-element)` raises
  `CapabilityPolicyValidationError`.

### `filter_revocation_events(stream, classifier=None, kinds=None)` (async generator)

Wraps an async iterator of `CapabilityPolicyWatchEvent` and yields only
the `ClassifiedRevocationEvent` instances whose `kind` is in `kinds`.

| Parameter      | Default                                                                                          | Meaning                                                                                                                       |
|----------------|--------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| `stream`       | required                                                                                         | Any async iterator yielding `CapabilityPolicyWatchEvent`. The `_CapabilityPolicyWatchStreamHandle` from `backend.watch()` is canonical. |
| `classifier`   | fresh `RevocationEventClassifier()`                                                              | Pass an existing classifier to preserve per-key state across calls or share with another consumer.                            |
| `kinds`        | `frozenset({REVOCATION_TRANSITION, REVOCATION_REFRESH, REVOCATION_MONOTONIC_BREACH})`            | The three revocation-axis kinds. Pass `frozenset(RevocationEventKind)` to surface every classified event (full-audit).        |

**Important:** the classifier sees EVERY event in the stream so its
state map stays consistent; only the kinds matching the filter are
yielded. A consumer that processes only the yielded events (default
filter) will STILL observe correct prior-state for the next yielded
event because the classifier has consumed the in-between
`NOT_REVOCATION_RELATED` and `KEY_REMOVED` events.

**Closing semantics:** when the underlying stream ends, this generator
completes naturally. The classifier remains usable for further calls
after the generator returns.

**Defensive invariants:**

- `classifier` of wrong type raises `TypeError`.
- `kinds` of wrong type (not a set/frozenset) or containing non-`RevocationEventKind`
  members raises `TypeError`.

---

## Worked examples

### Example 1 — Audit-log narrow filter (default kinds, fresh classifier)

The simplest pattern: tail the bucket and log only revocation-axis
events. `NOT_REVOCATION_RELATED` and `KEY_REMOVED` events are suppressed.

```python
from wirelang.schemas.capability_policy_nats_kv_backend import (
    filter_revocation_events,
)

async with await backend.watch() as stream:
    async for classified in filter_revocation_events(stream):
        # Default kinds: TRANSITION + REFRESH + MONOTONIC_BREACH.
        audit_log.record(
            kind=classified.kind.value,
            key=classified.event.key,
            prior_revoked_at=classified.prior_revoked_at,
            current_revoked_at=classified.current_revoked_at,
            reason=classified.current_revocation_reason,
        )
```

### Example 2 — Resume-after-restart with `seed_from_records`

A consumer that restarted from a backend snapshot MUST seed the
classifier with the snapshot records, otherwise the first watch-event
for each pre-seeded key would be misclassified as a
`REVOCATION_TRANSITION` (it would be, against an empty prior).

```python
from wirelang.schemas.capability_policy_nats_kv_backend import (
    RevocationEventClassifier,
    filter_revocation_events,
)

# Bootstrap classifier from the snapshot the consumer also uses to
# seed its LiveCapabilityPolicySnapshot.
snapshot = await backend.snapshot()
classifier = RevocationEventClassifier()
classifier.seed_from_records(snapshot)

# Now consume the watch-stream with the seeded classifier; the first
# PUT for each pre-seeded key is classified against its snapshot
# revoked_at value, NOT against empty prior.
async with await backend.watch() as stream:
    async for classified in filter_revocation_events(
        stream, classifier=classifier,
    ):
        audit_log.record(classified)
```

This is the canonical resume-after-restart pattern. The `seed_from_records`
call is idempotent: calling it again with the same input produces the
same internal state.

### Example 3 — Alerting on `REVOCATION_MONOTONIC_BREACH`

A breach is a witness of substrate corruption or out-of-band tampering
(both transitions — apparent un-revoke and `revoked_at` advance/retreat
— are forbidden by the Sprint-6 Tag-1 backend write invariants on the
CAS-pin path). Operators typically want a separate alert path for this
kind:

```python
from wirelang.schemas.capability_policy_nats_kv_backend import (
    RevocationEventKind,
    filter_revocation_events,
)

# Surface only the breach kind.
alert_kinds = frozenset({RevocationEventKind.REVOCATION_MONOTONIC_BREACH})

async with await backend.watch() as stream:
    async for classified in filter_revocation_events(
        stream, kinds=alert_kinds,
    ):
        alert.fire(
            severity="critical",
            key=classified.event.key,
            prior_revoked_at=classified.prior_revoked_at,
            incoming_revoked_at=classified.current_revoked_at,
            reason=classified.current_revocation_reason,
        )
        # The classifier surfaces the kind and advances its state to
        # the new value. The consumer decides whether to halt the
        # downstream pipeline, page the on-call, or both.
```

Note that the classifier does NOT raise on a breach. The decision to
halt belongs to the consumer.

### Example 4 — Full-audit consumer (all five kinds)

A full-audit consumer that wants every classified event (including
`NOT_REVOCATION_RELATED` and `KEY_REMOVED`) passes
`frozenset(RevocationEventKind)` as `kinds`:

```python
from wirelang.schemas.capability_policy_nats_kv_backend import (
    RevocationEventKind,
    filter_revocation_events,
)

async with await backend.watch() as stream:
    async for classified in filter_revocation_events(
        stream, kinds=frozenset(RevocationEventKind),
    ):
        full_audit_log.record(classified)
```

### Example 5 — Driving classifier + LiveCapabilityPolicySnapshot in parallel

The classifier and `LiveCapabilityPolicySnapshot` are **orthogonal
observer objects**. The split keeps each one's concern narrow: the
live snapshot tracks the *current registry*, the classifier tracks the
*revocation-axis transitions*. A consumer can drive both from the same
event sequence to get independent annotated views, without
`filter_revocation_events` (which would otherwise short-circuit on
filtered-out events for the snapshot).

```python
from wirelang.schemas.capability_policy_nats_kv_backend import (
    LiveCapabilityPolicySnapshot,
    RevocationEventClassifier,
)

# Bootstrap both observers from the same snapshot.
records = await backend.snapshot()
live = await LiveCapabilityPolicySnapshot.bootstrap_from_backend(backend)
classifier = RevocationEventClassifier()
classifier.seed_from_records(records)

async with await backend.watch() as stream:
    async for event in stream:
        # Drive both observers from each event.
        await live.apply(event)
        classified = classifier.classify(event)

        # Live-registry-axis consumers read from `live`.
        # Revocation-event-axis consumers read from `classified`.
        if classified.kind is RevocationEventKind.REVOCATION_TRANSITION:
            audit_log.record_first_revocation(classified)
```

---

## Operational notes

### Default-filter rationale

The default `kinds` set surfaces three revocation-axis kinds and
filters out `NOT_REVOCATION_RELATED` + `KEY_REMOVED`. This matches the
typical "audit-log narrow" use-case where the operator wants to record
revocation activity and ignore noise.

Operators who want DELETE/PURGE in the audit log should override the
default with `kinds=frozenset({..., RevocationEventKind.KEY_REMOVED})`.
Operators who want every event should pass `frozenset(RevocationEventKind)`.

### State semantics under DELETE / PURGE

DELETE/PURGE drops the key from the classifier's map. A subsequent PUT
for the same key is classified against fresh no-prior state — so a
key re-introduced after DELETE is a `REVOCATION_TRANSITION` if it
carries `revoked_at` (NOT a `REVOCATION_REFRESH`). The classifier
preserves no revocation history beyond the event because DELETE is a
hard substrate-level removal; the revocation lineage is severed by
definition.

### Out-of-band tampering: what `REVOCATION_MONOTONIC_BREACH` does NOT do

The classifier surfaces the kind and advances its state to the new
value. It does NOT raise. It does NOT halt the watch-stream. It does
NOT roll back its internal map. Operators expecting a raise-on-breach
should wrap the classifier in their own enforcement layer
(`if classified.kind is REVOCATION_MONOTONIC_BREACH: raise SubstrateCorruption(...)`).

The deliberate design choice: a classifier is an observation layer,
not an enforcement layer. An enforcement layer that raises kills the
watch-stream consumer, which loses observation of subsequent events —
exactly the wrong response in an incident-investigation context.

### Concurrency caveat

`classify` and `seed_from_records` mutate the per-key map and are NOT
thread-safe or task-safe by themselves. The intended usage is a
single-consumer asyncio task. If multiple consumers must share a
classifier instance, wrap calls in an `asyncio.Lock` or instantiate
per-task classifiers.

---

## Cross-references

### Tag-1 / Tag-2 / Tag-3 pattern lineage

This Tag-3 consumer-side filter is the third side of the Sprint-6
revocation triangle. The other two sides are write-side and are
documented separately:

- **Sprint-6 Tag-1 backend revocation axis:**
  `wirelang/schemas/capability_policy_nats_kv_backend.py` —
  `CapabilityPolicyRevocationConflict`, `put_with_revision` Gate 3
  (revocation-monotonic). Spec: `wirelang/specs/schema-registry-spec.md`
  v0.16.0 entry.
- **Sprint-6 Tag-2 publisher-CLI revoke:** see `docs/publisher-cli-revoke.md`
  (operator manpage for the `wakir-schema-registry revoke` subcommand).

### Sprint-5 Tag-5 watch-stream foundation

The async generator pattern of `filter_revocation_events` mirrors the
Sprint-5 Tag-5 `CapabilityPolicyWatchEvent` async-iter contract.
`filter_revocation_events` is a pure-wrapping consumer of that contract
— it does NOT replace it. Operators who need the raw event stream
(without classification) should use `backend.watch()` directly.

### Implementation cross-references

- `wirelang/schemas/capability_policy_nats_kv_backend.py` — the
  `RevocationEventKind`, `ClassifiedRevocationEvent`,
  `RevocationEventClassifier`, `filter_revocation_events` definitions.
- `wirelang/tests/test_revocation_event_filter.py` — Sprint-6 Tag-3
  hermetic tests (T-CPP-REVF-01..12 + 2 aux probes).
- `wirelang/specs/schema-registry-spec.md` v0.18.0 — canonical
  spec-text surface entry for Tag-3.

### V-907 and SPIFFE-ID-Binding cross-context

This surface is **not** touched by the Z-A SPIFFE/SPIRE-track
container-identity-substrate work. Revocation-event classification is
a consumer-side observation contract on the capability-policy bucket;
it is independent of SPIFFE-ID-binding and of V-907 persona-hash
audit-anker semantics. The Z-A consensus protocol and the
SPIFFE-ID-Binding spec-section (Sprint-6 Tag-4 Item 2) live on a
parallel axis.

---

*Sprint-6 Tag-3 (implementation) + Sprint-6 Tag-4 (this manpage) —
Reza Tehrani (dev-engineering-2 / wirelang). Spec v0.18.0
capability-policy revocation-event-filter consumer-side surface.*
