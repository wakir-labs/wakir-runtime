<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

---
spec: wirelang
version: 0.2.0
status: draft
supersedes: 0.1.0
replaced-by: null
date: 2026-05-06
audience: implementers, integrators
license: CC-BY-4.0
---

# Wirelang Specification v0.2

This document is the consolidated specification of the Wirelang
inter-agent messaging stack as it stands at the close of Phase-1a.
It supersedes the per-layer drafts shipped during Phase-1a daily
build (Tag-1 through Tag-9) and references — but does not duplicate —
the JSON-Schema documents and supporting specifications that ship in
the same module.

The intent of v0.2 is **consolidation, not redesign**. The wire
format, the semantic envelope and the trust layer are unchanged
relative to v0.1.0; v0.2 promotes the Layer-3 capability-token
language and the identity substrate from "Phase-1a draft" to
"Phase-1a stable" and integrates the cross-review-zone consensus
markers reached during Phase-1a.

## 1. Versioning and scope

### 1.1 Semver

Wirelang carries a semver-like spec version. The frame attribute
`wirelangversion` (Layer 1) is the on-the-wire indicator.

- **Patch** (`x.y.Z`) — clarifications, typo fixes, additional
  examples. No schema or normative change.
- **Minor** (`x.Y.0`) — additive: new optional fields, new optional
  layers, new optional caveat predicates. Existing v1 frames remain
  valid against v1+ verifiers.
- **Major** (`X.0.0`) — breaking: removed fields, changed semantics,
  reserved-to-required transitions. Requires migration guidance.

v0.2.0 is a minor release relative to v0.1.0: every v0.1.0 frame is
a valid v0.2.0 frame, and every v0.1.0 caveat is a valid v0.2.0
caveat. v0.2.0 verifiers MUST accept frames stamped
`wirelangversion: 0.1.0` without modification.

### 1.2 What v0.2 covers

| Layer | Concern | Substrate | Schema | Spec text |
|---|---|---|---|---|
| 0 | Transport | NATS + JetStream | `schemas/layer-0-transport.json` | §3 + `specs/layer-0-2-overview.md` §"Layer 0" |
| 1 | Wire format | CloudEvents 1.0 + Wakir extensions, RFC 8785 JCS | `schemas/layer-1-wire.json` | §4 + `specs/layer-0-2-overview.md` §"Layer 1" |
| 2 | Semantic | JSON Schema 2020-12 + vocabulary anchor | `schemas/layer-2-semantic.json` | §5 + `specs/layer-0-2-overview.md` §"Layer 2" |
| 3 | Trust | AIP `draft-prakash-aip-00` + Biscuit v3 | `schemas/layer-3-capability-token.json`, `schemas/aip-document.json`, `schemas/datalog-caveat.json` | §6 + `specs/layer-3-capability-token.md`, `specs/datalog-caveat-vocabulary.md` |
| Identity | Persona substrate | secp256k1 BIP-32 + Ed25519 SLIP-0010 | (none — implementation in `wirelang/identity/`) | §7 + `specs/identity-substrate.md` |

Layer 4 (WAT audit anchoring) is out-of-module and owned by the WAT
component. The contract from Wirelang to WAT is documented in
`specs/wat-leaf-projection.md`.

### 1.3 What v0.2 does **not** cover

- TEE attestation evaluation logic (`attests`, `tee_required`
  caveats). The predicates are reserved in v0.2; verifiers MUST
  fail-closed on any token that references them. Phase-1b adoption
  per ADR-0023b.
- Cross-org federation predicates (`peer_org`, `federation_route`).
  Reserved for v0.3 / Phase-2 per ADR-0031 D2.
- A Wakir-native DID method (`did:wakir`). Requires an ADR before
  spec work begins. Until then, `did:web` is canonical.
- Persona-Identity-Registry (V-907) wire format. Depends on
  ADR-0031-D4 resolution.

## 2. Conformance keywords

The keywords MUST, MUST NOT, SHOULD, SHOULD NOT, MAY are used as in
RFC 2119 / RFC 8174.

A **producer** is conformant to v0.2 if every frame it emits
validates against the Layer-1 schema, carries a `wirelangversion`
of `0.1.0` or `0.2.0`, and projects deterministically to a WAT
leaf via `specs/wat-leaf-projection.md`.

A **verifier** is conformant to v0.2 if it accepts every conformant
v0.1.0 and v0.2.0 frame, rejects every frame whose Layer-1 schema
fails, and enforces the Layer-3 caveat semantics defined in §6 and
in `specs/datalog-caveat-vocabulary.md`.

## 3. Layer 0 — Transport

NATS + JetStream is the canonical transport substrate. The schema
constrains subject naming and stream-bind shape; runtime concerns
(durable consumers, replication factor, retention) are operational
and live outside the wire spec.

- **Subject convention:** `wakir.<env>.<domain>.<event-type>[.<sub-id>]`
  with `env ∈ {dev, staging, prod}`.
- **Delivery:** at-least-once with per-stream FIFO. Consumers MUST
  be idempotent against duplicate CloudEvents `id` values.
- **Retention:** 7 days default; 14 days for `wat.*` streams.
- **Subject permissions:** the schema reserves a subject-permission
  shape that accommodates Phase-1b JWT-SVID claims (ADR-0020
  variant alpha) without a schema break.

See `specs/layer-0-2-overview.md` §"Layer 0" and the JSON Schema
at `schemas/layer-0-transport.json` for full normative text.

## 4. Layer 1 — Wire format

A Wakir frame is a CloudEvents 1.0 envelope with the Wakir extension
attributes shown below. Frames intended for downstream WAT anchoring
MUST be serialised with RFC 8785 JCS; the leaf hash is
`SHA-256(JCS(frame_without_signature))`.

| Attribute | Required | Purpose |
|---|---|---|
| `specversion` | yes | Fixed to `"1.0"`. |
| `type` | yes | Reverse-DNS event type, matches the NATS subject's `<event-type>` token. |
| `source` | yes | Sending agent's DID URI (`did:web:` Phase-1). |
| `id` | yes | Event id; Wakir convention is UUIDv7. |
| `wirelangversion` | yes | Wirelang spec semver. |
| `schemaid` | yes | Schema-registry identifier, reverse-DNS. |
| `schemaversion` | yes | Semver of the referenced schema. |
| `actorrole` | yes | Pseudonymised role string. No clear names (Brand-Guide §9). |
| `time` | yes (Wakir) | RFC 3339 UTC timestamp. CloudEvents marks this OPTIONAL; Wakir narrows to required. |
| `agentid` | optional | Stable in-org agent identifier. |
| `caprefs` | optional | Array of Layer-3 token hashes (`sha256:<64-hex>`). |
| `personapin` | optional | Persona pin commitment hash. |
| `personahash` | optional | Persona-markdown content hash (V-907 phase 3). |
| `attestationref` | optional | TEE attestation report hash (V-904 phase 3). |
| `imagedigest` | optional | Container image digest (Phase-1b). |
| `dataschemaref` | optional | Resolved schema document URI when `dataschema` is an alias. |

Cross-references: `schemas/layer-1-wire.json` (JSON Schema 2020-12)
is the normative artefact. `specs/layer-0-2-overview.md` carries
the per-attribute walkthrough.

## 5. Layer 2 — Semantic

The semantic envelope carries the schema-registry binding and the
vocabulary anchor. It distinguishes domain events from meta events
by reverse-DNS namespace:

- **Domain events:** `wakir.<domain>.*` — business semantics.
- **Meta events:** `wakir.meta.*` — protocol-level signaling such
  as `wakir.meta.capability.issued` or
  `wakir.meta.schema.deprecation`.

The envelope additionally carries:

- A vocabulary anchor (`vocabulary.id`, `vocabulary.version`).
- Validity-window timestamps (`validafter`, `validuntil`).
- Overlapping-validity-window declarations for soft schema migration.
- An optional OTS-anchor path under
  `meta/timestamps/wirelang-(schema|vocab)/` (cross-review zone 3
  with the WAT module — consensus marker pending Tomás stamp at
  v0.2 publication time; v0.2 does not depend on the marker for
  validation).

Cross-references: `schemas/layer-2-semantic.json` is normative.
`specs/layer-0-2-overview.md` carries the prefix-conditional
constraints in prose.

## 6. Layer 3 — Trust (capability tokens)

Layer 3 carries the *trust* concern: who is allowed to do what,
on whose behalf, until when. The on-the-wire token is a Biscuit v3
binary; Wirelang carries hashes of the binary in `caprefs` and
documents the JSON projection used inside Wirelang frames and
registries plus the AIP document that anchors the issuer's root key.

### 6.1 Substrate adoption

| Concern | Substrate | Reference |
|---|---|---|
| Token format | Biscuit v3 (default v3.3) | eclipse-biscuit/biscuit `SPECIFICATIONS.md` |
| Identity document | AIP `draft-prakash-aip-00` | IETF datatracker, expires 2026-09-28 |
| Signature algorithm | Ed25519 (RFC 8032) | inherited from Biscuit v3 |
| Canonical JSON | RFC 8785 JCS | inherited from Layer 1 |

### 6.2 Token shape

A capability token in JSON projection has an authority block and
zero or more append blocks; sealing is optional and irrevocable.
The wire-stable hash committed to `caprefs` is
`SHA-256(canonical_token_bytes)`.

The full structural specification is `specs/layer-3-capability-token.md`,
and the JSON Schema is `schemas/layer-3-capability-token.json`. v0.2
adopts both unchanged from v0.1.0.

### 6.3 AIP document anchoring

The issuer's AIP document conforms to `draft-prakash-aip-00` §2.3
with all required fields plus the Wakir `biscuit_root_pubkey`
extension. AIP-document signatures cover the JCS-canonicalised
document body minus the `document_signature` slot, signed with
Ed25519. Schema: `schemas/aip-document.json`.

### 6.4 Datalog caveat vocabulary v0.1

v0.2 ships the full 18+2 Wakir Datalog vocabulary (the eight-
predicate v0.1.0 working draft expanded to the eighteen-predicate
v0.1 vocabulary plus `not_before`/`not_after` carried as caveats
beyond the authority-block fields). Vocabulary spec:
`specs/datalog-caveat-vocabulary.md`. Schema:
`schemas/datalog-caveat.json`. Vocabulary version is independent
of Wirelang spec version: vocabulary v0.1 is bound to Wirelang
v0.1 *and* v0.2.

Future vocabulary growth is tracked in
`specs/datalog-caveat-vocabulary-phase-2-skizze.md` (companion
document to v0.2). Phase-2 vocabulary changes will be additive
under the forward-compat rule (§8).

## 7. Identity substrate

Wirelang Layer 3 names identities (issuer DID, audience DID); the
identity *substrate* — how those identities are rooted in
cryptographic key material, derived for sub-agents, persisted, and
recovered — is specified in `specs/identity-substrate.md` and
implemented in `wirelang/identity/`.

### 7.1 Two-curve stack

A persona is rooted in a single 64-byte seed. Two master keys are
derived from that seed along parallel axes:

| Axis | Curve | Master derivation | Purpose |
|---|---|---|---|
| 1 | secp256k1 | BIP-32 | DID verification methods, OTS-anchor signatures, treasury wallets |
| 2 | Ed25519 | SLIP-0010 | Biscuit authority/append-block signatures, AIP `biscuit_root_pubkey` |

Sub-key derivation path on both axes:

```
m / 44' / WAKIR_COIN_TYPE' / persona_idx' / spawn_counter'
```

with `WAKIR_COIN_TYPE = 0x57414B49` (ASCII `WAKI`). All four levels
hardened.

### 7.2 Identity documents — DID and AIP

Each persona produces two binding documents:

- **DID document** (`did:web`): published under
  `https://wakir.dev/.well-known/did/<role>/v<N>.json`. Carries both
  curve verification methods. Self-signature (proof block) under
  `EcdsaSecp256k1Signature2019` is a Wakir extension on top of the
  HTTPS-publication integrity inherited from `did:web`.
- **AIP document**: conforms to `draft-prakash-aip-00` §2.3, bound
  to the DID document via `verification_methods[].controller`.
  Signed with Ed25519 over JCS-canonicalised body minus
  `document_signature`.

### 7.3 Cold-storage and recovery

Cross-Review Zone 1 consensus marker D-2 (Phase-1a default):
**SLIP-39 2-of-3 single-group split**, no passphrase. Quarterly
recovery drill. Side-channel-hardened SLIP-39 is gated by an ADR
before any online deployment. See `specs/identity-substrate.md` §3
for normative text.

### 7.4 Integration into Layer 3

- The Layer-3 token's `aip_document_ref` resolves to the persona's
  AIP document under §7.2.
- The token's authority-block `signature` is verified against the
  AIP document's `biscuit_root_pubkey` (or, fallback, a
  `public_keys` entry with `purpose: "biscuit-root"`).
- The token's `issuer_did` MUST match the AIP document's `id`.
- The token's `audience_pattern` resolves against the audience DID
  using the identifier-scheme rules of AIP §2.2.

## 8. Forward compatibility and migration

### 8.1 Additive minor releases

v0.2 demonstrates the additive-minor pattern. Specifically:

- v0.2 introduces no new mandatory frame attributes.
- v0.2 introduces no new caveat predicates (the eighteen+two
  predicates of vocabulary v0.1 land in v0.2 from Phase-1a Tag-3
  rather than from v0.1.0; the JSON Schema accepted them in v0.1.0
  already).
- v0.2 documents the identity substrate and the WAT leaf projection
  as integral parts of the spec rather than as out-of-scope
  Tag-N memos.

### 8.2 Migration v0.1.0 → v0.2.0

Producers and verifiers MAY upgrade independently. Recommended
sequence:

1. **Verifier upgrade.** Verifiers add support for v0.2.0
   frames. Since v0.2.0 frames are also valid v0.1.0 frames, this
   is a no-op at the schema level; the upgrade is a
   `wirelangversion` whitelist extension.
2. **Producer upgrade.** Producers may bump `wirelangversion` to
   `0.2.0` once their integration tests pass against a v0.2.0
   verifier. There is no behaviour change at the wire level.
3. **Documentation.** Update internal integration docs to reference
   `specs/wirelang-spec-v0-2.md` rather than per-Tag memos.

There is no requirement to upgrade. v0.1.0 frames remain valid
against v0.2 verifiers indefinitely.

### 8.3 Reserved fields and forward-compat policy

A v1-class verifier (i.e., any verifier conformant to v0.x for
`x ≥ 1`) MUST tolerate unknown top-level frame attributes and
unknown caveat predicates that follow the syntax of
`schemas/datalog-caveat.json`. Specifically:

- Unknown frame attributes: ignore.
- Unknown caveat predicates: the verifier MAY enforce a fail-closed
  policy *if* the predicate is not in the verifier's vocabulary;
  but a verifier that has a documented "ignore unknown predicates"
  mode (e.g., for migration) is conformant. The default for
  Phase-1a is **fail-closed on unknown predicates** — a v0.2
  verifier that encounters a predicate it does not know MUST
  reject the token.

This means future Wakir vocabulary growth (Phase-2 predicates per
the v0.2 sketch) cannot be silently ignored; producers and
verifiers MUST upgrade in lockstep at vocabulary boundaries.
Frame-attribute growth, by contrast, is silently tolerable.

The asymmetry is intentional: a token's authority is a contract;
silently relaxing a caveat by ignoring it would be a privilege
escalation. A frame attribute is metadata; ignoring an unknown
attribute does not change the frame's semantic meaning.

## 9. Cross-review-zone integration

Three cross-review zones from ADR-0009 had explicit checkpoints
during Phase-1a:

| Zone | Outcome at Phase-1a close |
|---|---|
| Zone 1 — Identity-Substrate | Consensus reached; markers A1, B2, C1, D2 documented in `specs/identity-substrate.md`. |
| Zone 2 — WAT × Wirelang Frame integration | Consensus reached on four-tuple leaf projection; documented in `specs/wat-leaf-projection.md` (commit `338e007`, OTS `918a79b`). |
| Zone 3 — OTS-Schema-Anchor | Anchor format documented at Layer 2; consensus stamp pending at v0.2 publication time. v0.2 does not depend on the marker for validation. |

Zone 3 closure is a Phase-1b deliverable. v0.2 is correct without
it; the only change a Zone 3 closure would induce is the addition
of a mandatory anchor reference for schemas published into the
Wakir-controlled registry, which is a vocabulary-growth event and
follows §8 forward-compat rules.

## 10. Brand-Guide §9 compliance

This document, the schemas it references, and the example fixtures
under `wirelang/examples/` use only role-strings (`treasury-issuer`,
`treasury-agent`, `cfo-agent`, `audit-specialist`,
`treasury-operator`). No personal clear names appear in any
Wirelang artefact. All v0.2 examples are inherited from the per-
layer specs and have been checked against `projects/comms/brand-
guide.md` §9 at v0.2 publication.

## 11. References

### 11.1 Wakir specs (this module)

- `specs/layer-0-2-overview.md` — Layer-0–2 walkthrough.
- `specs/layer-3-capability-token.md` — Layer-3 trust concerns.
- `specs/datalog-caveat-vocabulary.md` — vocabulary v0.1 (18+2
  predicates).
- `specs/datalog-caveat-vocabulary-phase-2-skizze.md` — Phase-2
  candidate predicates.
- `specs/identity-substrate.md` — persona substrate.
- `specs/wat-leaf-projection.md` — Wirelang→WAT bridge contract.
- `specs/recovery-drill-leaf-projection.md` — recovery-drill
  leaf projection.

### 11.2 JSON-Schema files

- `schemas/layer-0-transport.json`
- `schemas/layer-1-wire.json`
- `schemas/layer-2-semantic.json`
- `schemas/layer-3-capability-token.json`
- `schemas/aip-document.json`
- `schemas/datalog-caveat.json`

### 11.3 External

- RFC 2119 / RFC 8174 — conformance keywords.
- RFC 3339 — date-time format.
- RFC 8032 — Ed25519 signatures.
- RFC 8785 — JSON Canonicalization Scheme (JCS).
- BIP-32 — hierarchical deterministic wallets.
- SLIP-0010 — Ed25519 derivation.
- SLIP-39 — Shamir secret sharing.
- IETF `draft-prakash-aip-00` — Agent Identity Protocol; expires
  2026-09-28 (verified 2026-05-06 P7-stamp).
- eclipse-biscuit `SPECIFICATIONS.md` — Biscuit v3 (verified
  2026-05-06 P7-stamp).
- W3C DID Core 1.0 — decentralised identifiers.
- CloudEvents 1.0 — event envelope.
- JSON Schema 2020-12 — schema language.

## 12. Acknowledgements

This consolidation is the product of Phase-1a daily build (Tag-1
through Tag-9) and the cross-review sessions moderated by HR
(consensus markers A1, B2, C1, D2 for Zone 1; commit `338e007`
for Zone 2). Implementation lives in `wirelang/identity/` and
`wirelang/schemas/`. Test coverage at v0.2 publication: 274/274
public + 4 gated tests, with 172 of those covering Wirelang
sub-modules.

— *role: wirelang-spec-owner*
