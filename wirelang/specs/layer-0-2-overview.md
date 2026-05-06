<!-- SPDX-License-Identifier: Apache-2.0 -->
# Wirelang Layers 0–2 — Overview

Wirelang v0.1.0 ships three layers in this drop. Each layer is enforced by
a JSON Schema 2020-12 document under `wirelang/schemas/` and exercised by
positive and negative tests under `wirelang/tests/`.

## Layer 0 — Transport (NATS + JetStream)

- Subject convention: `wakir.<env>.<domain>.<event-type>[.<sub-id>]`.
- Environments: `dev` / `staging` / `prod`.
- Delivery: at-least-once, per-stream FIFO. Consumers are idempotent
  against duplicate CloudEvents `id` values.
- Retention: 7 days default, 14 days for `wat.*` streams.
- Subject permissions reservation accommodates Phase-1b JWT-SVID claims
  (ADR-0020 variant alpha) without schema break.

## Layer 1 — Wire format (CloudEvents 1.0 + Wakir extensions)

A Wakir frame is a CloudEvent 1.0 envelope with these extension attributes:

| Extension | Required | Purpose |
|---|---|---|
| `wirelangversion` | yes | Wirelang spec semver. |
| `schemaid` | yes | Schema-registry identifier. |
| `schemaversion` | yes | Semver of the referenced schema. |
| `actorrole` | yes | Pseudonymised role string (no clear name). |
| `agentid` | optional | Stable in-org agent identifier (pseudonymisation-compatible). |
| `caprefs` | optional | List of Layer-3 capability-token hashes. |
| `personapin` | optional | Persona pin commitment hash. |
| `personahash` | optional | Persona-markdown content hash (V-907 phase 3). |
| `attestationref` | optional | TEE attestation report hash (V-904 phase 3). |
| `imagedigest` | optional | Container image digest (Phase-1b). |
| `dataschemaref` | optional | Resolved schema document URI when `dataschema` is an alias. |

Frames meant for downstream WAT anchoring MUST be serialised with RFC 8785
JSON Canonicalization. The hash is `SHA-256(JCS(frame_without_signature))`.

## Layer 2 — Semantic (frame envelope)

The semantic envelope distinguishes domain events from meta events by
namespace:

- **Domain events:** `wakir.<domain>.*` for business semantics.
- **Meta events:** `wakir.meta.*` for protocol-level signaling such as
  `wakir.meta.capability.issued` or `wakir.meta.schema.deprecation`.

Both classes are validated by the same envelope schema with conditional
prefix constraints. The envelope also carries:

- A vocabulary anchor (`vocabulary.id`, `vocabulary.version`).
- Validity-window timestamps (`validafter`, `validuntil`).
- Overlapping-validity-window declarations for soft schema migration.
- An optional OTS anchor path under
  `meta/timestamps/wirelang-(schema|vocab)/` (cross-review zone 3 with
  the WAT module; pending WAT-owner consensus stamp).

## Frame example

See `wirelang/examples/frame-domain-event-example.json` for an
`agent.spawn` frame and `frame-meta-event-example.json` for a
`capability.issued` frame. Both validate against the Layer-1 schema and
embed a Layer-2 envelope inside the `data.wirelang_layer_2_envelope`
section.

## Out of scope (Tag-1)

- Layer 3 (capability tokens, AIP+Biscuit).
- Layer 4 (WAT audit anchoring) — owned by the WAT module.
- Identity substrate (secp256k1+Ed25519 two-curve stack) — Tag-2+ scope.
