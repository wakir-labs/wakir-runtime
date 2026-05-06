<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

---
spec: wakir-datalog-caveat-vocabulary
phase: 2-sketch
companion-to: datalog-caveat-vocabulary.md (v0.1, 18+2 predicates)
status: sketch (non-normative)
date: 2026-05-06
license: CC-BY-4.0
---

# Wakir Datalog Caveat Vocabulary — Phase-2 Sketch

This document is a **non-normative sketch** of the Phase-2 expansion
candidates for the Wakir Datalog caveat vocabulary. The Phase-1a
vocabulary (v0.1, 18+2 predicates) is specified normatively in
`specs/datalog-caveat-vocabulary.md`. The Phase-2 vocabulary will
be a strictly additive minor version — v0.2 — adopted only when
the supporting infrastructure (zk-backend, federation registry,
persona-state probe) lands.

The intent of this sketch is to (a) reserve predicate names so
v0.1 producers do not collide with future predicates by accident,
(b) pre-position the JSON-Schema pattern for additive growth, and
(c) document the cross-review hooks each predicate touches so the
implementation order can be planned across Tomás (WAT/audit) and
Reza (Wirelang/identity) in Phase-2.

## 1. Scope and non-goals

**In scope.** Predicate name, arity, argument-type expectations,
intended semantics, dependency on Phase-2 infrastructure, and the
cross-review hook (which engineering domain owns the verifier
extension).

**Out of scope.** Operational semantics of Biscuit-Datalog beyond
what v0.1 already documents, formal type-system extensions, full
Phase-2 schema regeneration. Those lie inside the Phase-2 v0.2
vocabulary spec; this is a sketch, not that spec.

## 2. Forward-compat policy applied to vocabulary

Per `wirelang-spec-v0-2.md` §8.3, the Wirelang forward-compat
default is **fail-closed on unknown predicates**. A v0.1 verifier
that meets a Phase-2 predicate MUST reject the token. This is the
opposite of the frame-attribute policy (which is ignore-unknown).

Two consequences:

1. **No silent privilege escalation.** A Phase-2 producer that
   issues a token with `zk_proof_valid(...)` cannot have the
   caveat ignored by a v0.1 verifier; the token is rejected.
2. **Lockstep upgrade.** Producers and verifiers must adopt v0.2
   vocabulary together. The expected pattern is that an
   organisation gates its v0.2 producer rollout behind a
   `vocabulary_version >= 0.2` declaration in the AIP document
   and only enables Phase-2 predicates once consumers have
   advertised the same.

A possible mitigation — an "ignore unknown" mode for a defined
migration window — is sketched in §6 below.

## 3. Phase-2 predicate candidates (~10)

### 3.1 zk-Caveat extensions (V-905 ZK-Reputation)

#### `zk_proof_valid(proof_hash: bytes_hex, vk_id: string)`

- **Arity:** 2.
- **Semantics.** Require the verifier to confirm that
  `proof_hash` references a zk-SNARK / zk-STARK proof that has
  been successfully verified against the verification key
  identified by `vk_id` in the Wakir reputation registry.
- **Phase-2 dep.** zk-backend (V-905) reachable; Wakir verifier
  carries a registry-resolver for `vk_id`.
- **Cross-review hook.** WAT (anchor of the proof receipt) +
  Wirelang (caveat semantic). Consensus marker required before
  predicate adoption.

#### `zk_reputation_threshold(score_min: int, scheme: string)`

- **Arity:** 2.
- **Semantics.** Require the invoking persona's zk-attested
  reputation score under `scheme` to be at least `score_min`.
  The actual score is concealed; the proof attests only the
  threshold relation.
- **Phase-2 dep.** Reputation-scheme registry, range-proof
  primitive in the zk-backend.
- **Cross-review hook.** Wirelang (caveat) + persona-engine
  (reputation-scheme registration).

### 3.2 Cross-org federation (ADR-0031 D2)

#### `peer_org(aip_id: did)`

- **Arity:** 1.
- **Semantics.** The invoking persona's AIP document MUST be
  rooted at, or delegated through, the AIP `aip_id`. Used by
  multi-org capability flows where the issuer org delegates
  signing authority but pins the cross-org boundary.
- **Phase-2 dep.** Cross-org federation registry, AIP delegation
  chain validator.
- **Cross-review hook.** Wirelang (delegation chain) + persona-
  engine (cross-org persona registration).

#### `federation_route(route_id: string)`

- **Arity:** 1.
- **Semantics.** Token is valid only along the named federation
  route (e.g., `"wakir->partner-A->treasury"`). Verifier consults
  a route registry; mismatched route is a rejection.
- **Phase-2 dep.** Federation route registry; route definition
  format.
- **Cross-review hook.** Wirelang + persona-engine + WAT
  (anchoring the route registry version).

#### `cross_org_quota($n: var, $org: var)`

- **Arity:** 2.
- **Semantics.** Bind the cross-org quota counter `$n` for the
  org `$org` for the verifier to compose with `$n < <int>`
  comparisons. Per-org rate limit.
- **Phase-2 dep.** Distributed quota counter; consistency model
  (best-effort vs strict).
- **Cross-review hook.** Wirelang + WAT (quota-counter snapshot
  anchored as audit evidence).

### 3.3 Persona-state caveats

#### `persona_state(state: string)`

- **Arity:** 1.
- **Semantics.** Restrict the token to invocations where the
  invoking persona is in `state` (e.g., `"active"`,
  `"suspended"`, `"revoked"`, `"under-audit"`). Verifier consults
  the persona-state registry (V-907 phase-3) for the current
  state.
- **Phase-2 dep.** Persona-state registry online and reachable
  from the verifier path.
- **Cross-review hook.** Wirelang + persona-engine + WAT
  (persona-state transitions are audited).

#### `persona_pin(pin_hash: bytes_hex)`

- **Arity:** 1.
- **Semantics.** The invoking persona's `personapin` (Layer-1
  attribute) MUST equal `pin_hash`. Lets a token bind itself to
  a specific persona deployment instance and reject any token
  use after a re-pinning event.
- **Phase-2 dep.** None at the verifier; Phase-1a Layer-1 already
  carries `personapin`. Predicate is logically v0.2 because v0.1
  verifiers do not know how to reject mismatches consistently.
- **Cross-review hook.** Wirelang only. Could be promoted to v0.1
  in a patch release if Phase-2 timing is far out.

#### `persona_attested_after(at: timestamp)`

- **Arity:** 1.
- **Semantics.** The invoking persona's most recent attestation
  event (TEE attestation, persona-pin commitment, audit
  signature) MUST be after `at`. Forces "fresh" persona evidence.
- **Phase-2 dep.** Attestation-event registry timestamps
  reachable from verifier.
- **Cross-review hook.** Wirelang + WAT.

### 3.4 WAT-aware caveats (Tomás cross-review)

#### `wat_inclusion_proof_valid(leaf_hash: bytes_hex, manifest_id: string)`

- **Arity:** 2.
- **Semantics.** Require the verifier to confirm that
  `leaf_hash` is included in the WAT manifest identified by
  `manifest_id` (manifest hash or hour-stamp). Used by tokens
  that depend on a previously-anchored event having been
  successfully audit-anchored.
- **Phase-2 dep.** Verifier carries a manifest-resolver for the
  WAT manifest registry; the `leaf_hash`+`manifest_id` pair is
  resolvable offline against a WAT export.
- **Cross-review hook.** **WAT (Tomás-owned)** — the verifier
  extension lives at the WAT-Wirelang boundary. Cross-review
  zone 2 follow-up.

#### `caveat_hash(self_hash: bytes_hex)`

- **Arity:** 1.
- **Semantics.** Self-referential: declares the SHA-256 hash of
  the canonical caveat-set this predicate is part of. The
  verifier rejects the token if the declared hash does not
  match the recomputed hash of the surrounding caveat-set
  (excluding the `caveat_hash` predicate itself). Defends
  against split-caveat-block attacks where an attenuator removes
  caveats but keeps the signature.
- **Phase-2 dep.** None new; the canonicalisation rule is
  already JCS. Could be a v0.1.x patch.
- **Cross-review hook.** **WAT × Wirelang** — Tomás review for
  the `caveat_hash → WAT-leaf` projection. The intent is that
  the leaf-tuple `capability_token_hash` plus the in-token
  `caveat_hash` predicate together let an offline auditor verify
  that the audit-anchored token-hash and the in-token
  caveat-set-hash are consistent without re-fetching the binary
  Biscuit token.

## 4. Tabular summary

| Predicate | Arity | Phase-2 dep | Cross-review hook | Earliest practical adoption |
|---|---|---|---|---|
| `zk_proof_valid` | 2 | zk-backend | Wirelang × WAT | v0.2 |
| `zk_reputation_threshold` | 2 | zk-backend, registry | Wirelang × persona-engine | v0.2 |
| `peer_org` | 1 | federation registry | Wirelang × persona-engine | v0.2 |
| `federation_route` | 1 | route registry | Wirelang × persona-engine × WAT | v0.2 |
| `cross_org_quota` | 2 | distributed quota counter | Wirelang × WAT | v0.2 |
| `persona_state` | 1 | persona-state registry | Wirelang × persona-engine × WAT | v0.2 |
| `persona_pin` | 1 | none new | Wirelang | v0.1.x patch (optional) |
| `persona_attested_after` | 1 | attestation registry | Wirelang × WAT | v0.2 |
| `wat_inclusion_proof_valid` | 2 | WAT manifest resolver | **Tomás (WAT)** | v0.2 |
| `caveat_hash` | 1 | none new | **Tomás × Reza (WAT × Wirelang)** | v0.1.x patch (optional) |

Two candidates (`persona_pin`, `caveat_hash`) require no new
infrastructure and could move forward as v0.1.x patches if the
v0.2 timeline slips. The other eight need a Phase-2 substrate
component each.

## 5. Reserved-name registry

Until v0.2 vocabulary lands, the predicate names listed in §3
are **reserved**. v0.1 producers MUST NOT issue tokens that use
any of these names; v0.1 verifiers fail-closed on encountering
any of them under §2.1 of the v0.1 vocabulary spec.

The reservation extends to obvious aliases: `zk_valid`,
`zk_score`, `org_peer`, `route`, `persona`, `attested_after`,
`wat_proof`, `caveat_self_hash`. Producers needing local
extensions in the meantime SHOULD prefix names with `x_` (e.g.,
`x_org_internal_audit_pass`) to stay clear of the reserved space.

## 6. Optional ignore-unknown migration mode

The default fail-closed policy is operationally safe but
operationally awkward at vocabulary upgrade boundaries. A
controlled migration window is sketched here for future ADR
consideration:

1. The verifier configuration adds a `vocabulary_migration_mode`
   field with values `strict` (default; current behaviour) and
   `ignore-unknown-with-audit`.
2. In `ignore-unknown-with-audit` mode, the verifier accepts a
   token that contains an unknown predicate, but emits a
   meta-event `wakir.meta.vocabulary.unknown_predicate` carrying
   the predicate name and the token hash. The audit trail
   captures the event; an alert fires if the verifier sees any
   `ignore-unknown` in production for more than the configured
   window.
3. The mode is per-verifier-deployment, never per-token. A
   producer cannot opt the verifier into ignore-unknown.

ADR work (out of scope for this sketch): operational risk model,
migration-window length, alert thresholds, audit-event schema.

## 7. Cross-review note for Tomás

Two items in §3 explicitly cross into Tomás's domain:

1. **`wat_inclusion_proof_valid`** — the verifier extension is
   most cleanly built at the WAT side, since the manifest-
   resolver code already lives there. Reza writes the predicate
   spec; Tomás builds the resolver and the WAT-side caveat
   evaluator hook. Cross-review-zone 2 follow-up.
2. **`caveat_hash`** — Reza spec, but the WAT leaf-projection
   (`specs/wat-leaf-projection.md`) currently records
   `capability_token_hash` only at the four-tuple level. If the
   token additionally carries `caveat_hash` self-reference, an
   auditor can verify caveat-set integrity offline against the
   anchored leaf. Tomás cross-review for whether the leaf-
   projection v2 should hash the caveat-set into a separate
   leaf-tuple field, or whether the caveat-hash being inside
   the token-binary (and thus already covered by the token-
   hash that the leaf records) is sufficient.

Operative coordination via Tomás-first escalation path
(ADR-0033) when Phase-2 vocabulary work begins.

## 8. Brand-Guide §9 compliance

This sketch uses only role-strings and abstract identifiers in
its illustrative material. Where concrete examples are needed in
the eventual v0.2 vocabulary spec, the `treasury-issuer`,
`treasury-agent`, `cfo-agent`, `audit-specialist` convention from
v0.1 carries over. No personal clear names appear.

— *role: wirelang-spec-owner*
