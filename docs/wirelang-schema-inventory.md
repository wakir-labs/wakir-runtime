# Wirelang Schema Inventory (Phase-1a)

**Status:** Phase-1a Tag-15 baseline. Owner: wirelang-eng
(Wirelang / Capability-Token-Layer / Identity-Substrate-Owner).
Cross-Review-Zone-3 boundary: WAT-Manifest-Spec is **out of
scope** of this inventory and remains under wat-eng's
(Matrix-Lead) owner-right.

This document indexes the seven Wirelang JSON-Schema documents
that ship in `wirelang/schemas/`. It is the input to the
Wirelang-internal schema-registry (`wirelang/schemas/registry.py`).

## Inventory Table

| # | Path                                                | `$id`                                                                          | Draft     | Type   | Description                                                                          |
|---|-----------------------------------------------------|--------------------------------------------------------------------------------|-----------|--------|--------------------------------------------------------------------------------------|
| 1 | `wirelang/schemas/layer-0-transport.json`           | `https://wakir.dev/wirelang/schema/layer-0-transport/0.1.0`                    | 2020-12   | object | Layer-0 transport binding (NATS + JetStream).                                        |
| 2 | `wirelang/schemas/layer-1-wire.json`                | `https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0`                         | 2020-12   | object | Layer-1 wire frame (CloudEvents 1.0 + Wakir extensions).                             |
| 3 | `wirelang/schemas/layer-2-semantic.json`            | `https://wakir.dev/wirelang/schema/layer-2-semantic/0.1.0`                     | 2020-12   | object | Layer-2 semantic frame (domain vs. meta events).                                     |
| 4 | `wirelang/schemas/layer-3-capability-token.json`    | `https://wakir.dev/wirelang/schema/layer-3-capability-token/0.1.0`             | 2020-12   | object | Layer-3 capability-token JSON envelope around Biscuit v3.                            |
| 5 | `wirelang/schemas/datalog-caveat.json`              | `https://wakir.dev/wirelang/schema/datalog-caveat/0.1.0`                       | 2020-12   | array  | Datalog-caveat array (Wakir Phase-1a vocabulary v0.1).                               |
| 6 | `wirelang/schemas/aip-document.json`                | `https://wakir.dev/wirelang/schema/aip-document/0.1.0`                         | 2020-12   | object | AIP document per draft-prakash-aip-00 with Wakir extensions.                         |
| 7 | `wirelang/schemas/aip-frame-envelope.json`          | `https://wakir.dev/wirelang/schema/aip-frame-envelope/0.1.0`                   | 2020-12   | object | Wirelang-internal envelope wrapping Layer-3 token + AIP-document reference.          |

**Count:** 7 schemas. **Consistency-check (Tag-15 baseline):**
all schemas have `$id`, `$schema` (2020-12 in every case),
`title`, `description`, and a top-level `type`. Every `$id` is
unique (URI-form `https://wakir.dev/wirelang/schema/<name>/<semver>`).

## Naming and ID Convention

Every schema's `$id` follows the pattern:

```
https://wakir.dev/wirelang/schema/<schema-name>/<semver>
```

- `wakir.dev` is the project domain (placeholder; not yet
  served at runtime in Phase-1a — `$id`s are identifiers, not
  fetch URLs).
- `<schema-name>` is the schema slug (matches the file name
  modulo the `.json` suffix, with hyphens preserved).
- `<semver>` is `MAJOR.MINOR.PATCH`. Phase-1a baseline is
  `0.1.0` for all seven schemas, indicating a stable but
  pre-1.0 vocabulary.

The conventions for bumping the `<semver>` are documented in
[`docs/wakir-schema-versioning.md`](./wakir-schema-versioning.md).

## Cross-Module Consumers

The seven schemas are consumed by Wirelang sub-packages via
the registry loader (no direct file paths in production code
paths):

| Consumer module                                   | Schemas used                                                  |
|---------------------------------------------------|---------------------------------------------------------------|
| `wirelang/builder/frame_builder.py`               | layer-1-wire, layer-2-semantic                                |
| `wirelang/identity/aip_document.py`               | aip-document                                                  |
| `wirelang/identity/capability_token.py`           | layer-3-capability-token, datalog-caveat, aip-frame-envelope  |
| `wirelang/tests/conftest.py` (fixtures)           | all seven (test-only, fixture-scoped)                         |

Tag-15 ships the registry; **migration of consumers** from
direct file-path loading to registry-lookup is incremental and
**not** part of Tag-15. Phase-1a Tag-16+ may convert
consumers; this inventory is the prerequisite.

## Cross-Review-Zone-3 Boundary

Per the Tag-15 Cross-Review-Zone-3 sync-memo from wirelang-eng
to wat-eng (Matrix-Lead), the following is **out of scope** of
this inventory:

- WAT-Manifest-Spec (`docs/wat-manifest-spec.md`) — wat-eng-owned.
- OTS-Schema-Anker-Format — Phase-1b item, not Tag-15.
- Persona-Definition-Schema (persona-engine-eng) — Phase-1b
  consumer-side.
- Container-Bridge-Schema (container-bridge-eng) — Phase-1b
  tracking item.

These boundary items are **tracked**, not built.

## Phase-1b Bridge (Informative)

The registry is intentionally a **file-system loader** in
Phase-1a. Phase-1b may swap the loader to a NATS-KV-backed
implementation. The public API of `wirelang/schemas/registry.py`
is shaped so consumers see only `get_schema(schema_id) -> dict`
and `list_schema_ids() -> list[str]`; the storage backend can
move without consumer changes.

— wirelang-eng
