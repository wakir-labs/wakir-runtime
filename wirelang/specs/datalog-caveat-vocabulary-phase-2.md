<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

---
spec: wakir-datalog-caveat-vocabulary
version: 0.2.0
status: ratified
phase: 1b-production
supersedes: datalog-caveat-vocabulary-phase-2-skizze.md (sketch)
companion-to: datalog-caveat-vocabulary.md (v0.1, normative Phase-1a)
date: 2026-05-07
license: CC-BY-4.0
---

# Wakir Datalog Caveat Vocabulary — Phase-2 (v0.2 ratified)

This document is the **normative Phase-2 ratification** of the Wakir
Datalog caveat vocabulary. It supersedes the non-normative sketch
`datalog-caveat-vocabulary-phase-2-skizze.md` and turns its predicate
catalogue into a ratified vocabulary classification, with three
additions that the sketch deliberately deferred:

1. A formal **Caveat-Set Canonicalisation Rule** (§4) — without which
   any "pinned set of caveats" in TV-W-2 (and in any future
   pin-stability guarantee on a Layer-3 token) drifts as soon as
   the producer reorders or reformats its caveats.
2. A **V-908 Federation Caveat Extension** (§5) — `peer_org` and
   `federation_route` are promoted from "candidate" to "Phase-2
   ratified, subject to V-908 backend availability".
3. A **TV-W-2 Pin-Stability Guarantee** (§6) — the spec-level contract
   that lets the Tag-16+ TV-W-2 implementation pin verification-trace
   hashes without re-baselining on every minor producer change.

The Phase-1a vocabulary v0.1 (20 predicates, normative in
`datalog-caveat-vocabulary.md`) remains in force unchanged. Phase-2
is **strictly additive** at the predicate level and **strictly
clarifying** at the canonicalisation level — no Phase-1a producer
becomes invalid under Phase-2.

## 1. Scope and ratification status

**Ratified by this document.**

- The Phase-1b production vocabulary classification (§3): which
  predicates are normative-now, normative-deferred, or reserved.
- The Caveat-Set Canonicalisation Rule (§4) for deterministic
  pin-hashing of caveat-sets.
- The V-908 federation caveat extension (§5): `peer_org` semantics
  and `federation_route` semantics, both ratified as v0.2 vocabulary
  with a `federation_backend_required` operational flag.
- The TV-W-2 pin-stability guarantee (§6): which producer changes
  may trigger a re-baseline of TV-W-2 verification-trace fixtures,
  and which may not.

**Out of scope.**

- Phase-2 predicates that depend on infrastructure not yet built
  (zk-backend `zk_proof_valid` / `zk_reputation_threshold`,
  persona-state registry `persona_state` /
  `persona_attested_after`, distributed quota counter
  `cross_org_quota`, WAT manifest resolver
  `wat_inclusion_proof_valid`). These remain reserved-only; their
  ratification waits for the corresponding substrate.
- Operational semantics of Biscuit-Datalog evaluation beyond what
  v0.1 already specified.
- A v0.3 vocabulary; this document caps at v0.2.

## 2. Forward-compat policy (v0.1 → v0.2)

Per `wirelang-spec-v0-2.md` §8.3, the Wirelang forward-compat
default is **fail-closed on unknown predicates**. A v0.1 verifier
that meets a Phase-2 predicate MUST reject the token. Two
consequences ratified here:

1. **No silent privilege escalation.** A v0.2 producer that issues
   a token with `peer_org(...)` cannot have the caveat ignored by
   a v0.1 verifier; the token is rejected.
2. **Lockstep upgrade.** Producers and verifiers must adopt v0.2
   together. The expected pattern: an organisation gates its v0.2
   producer rollout behind a `vocabulary_version >= 0.2`
   declaration in the AIP document and only enables Phase-2
   predicates once consumers have advertised the same.

The optional `vocabulary_migration_mode` (sketched in the Phase-2
sketch §6) remains **non-ratified**: an ADR is required before the
ignore-unknown-with-audit mode lands in any verifier.

## 3. Phase-1b production vocabulary classification

The Phase-1b production vocabulary partitions all predicates into
four classes. This classification is the canonical reference for
implementers writing Phase-1b production code paths.

### 3.1 Class N1 — Normative-Now (Phase-1a, fully active)

Eighteen predicates from v0.1 plus `not_before` and `not_after`,
all listed in `datalog-caveat-vocabulary.md` §3.1–§3.6. Verifiers
MUST evaluate these predicates per their v0.1 semantics. No
Phase-2 change applies.

```
action            agent_did             allowed_methods
audience          action_count_max      attenuation_depth_max
env               geo_region            nonce
not_after         not_before            operation
parent_token      rate_limit            read_only
spawn_counter_max time                  wat_anchor
```

(20 names total. `attests` and `tee_required` are listed below as
N2 because their evaluator was deferred to Phase-1b per ADR-0023b.)

### 3.2 Class N2 — Normative-Deferred (Phase-1b, evaluator-gated)

Predicates whose **vocabulary** is normative now but whose
**runtime evaluator** is gated on a Phase-1b component. A
verifier without the component MUST fail-closed (reject the
token) when meeting one of these predicates.

| Predicate | Required component | ADR / spec reference |
|---|---|---|
| `attests(hash)` | TEE-attestation evaluator | ADR-0023b |
| `tee_required(flag)` | TEE-attestation context | ADR-0023b |
| `peer_org(aip_id)` | V-908 federation resolver | ADR-0031 D2, §5 below |
| `federation_route(route_id)` | V-908 federation route registry | ADR-0031 D2, §5 below |

A verifier advertises which evaluators it carries through the
AIP-document `verifier_capabilities` extension (Phase-1b proposed
field; finalised in `wirelang/specs/identity-substrate.md` §3.2).

### 3.3 Class R — Reserved (Phase-2-future, no semantics yet)

Predicates whose name is reserved against name-collision but whose
evaluator and/or substrate is not yet in scope. v0.1 and v0.2
verifiers MUST fail-closed on these predicates.

| Predicate | Substrate dependency | Earliest ratification |
|---|---|---|
| `zk_proof_valid` | zk-backend (V-905) | v0.3 |
| `zk_reputation_threshold` | zk-backend + reputation registry | v0.3 |
| `cross_org_quota` | distributed quota counter | v0.3 |
| `persona_state` | persona-state registry (V-907 phase-3) | v0.3 |
| `persona_attested_after` | attestation-event registry | v0.3 |
| `wat_inclusion_proof_valid` | WAT manifest resolver | v0.3 |

### 3.4 Class P — Phase-2 patch-eligible (no new substrate)

Predicates that need no new infrastructure and could be promoted
to N1 in a v0.1.x patch release. Listed here so implementers can
distinguish "blocked by substrate" from "blocked by ADR".

| Predicate | Status | Promotion path |
|---|---|---|
| `persona_pin(pin_hash)` | reserved | v0.1.x patch on Wirelang Layer-1-attribute spec |
| `caveat_hash(self_hash)` | reserved | v0.1.x patch on JCS canonicalisation policy |

Both Class-P predicates are out-of-band candidates: ratification
requires only a clarifying ADR on the verifier behaviour, no
infrastructure rollout. They are **not** ratified by this document.

### 3.5 Reservation extends to obvious aliases

Until v0.3 vocabulary lands, the predicate names listed in §3.3
plus the names listed in §3.4 are **reserved**. v0.2 producers
MUST NOT issue tokens that use any of these names; v0.2 verifiers
fail-closed on encountering any of them.

The reservation extends to obvious aliases: `zk_valid`,
`zk_score`, `org_peer`, `route`, `persona`, `attested_after`,
`wat_proof`, `caveat_self_hash`. Producers needing local
extensions in the meantime SHOULD prefix names with `x_` (e.g.,
`x_org_internal_audit_pass`) to stay clear of the reserved space.
Local-prefix predicates are **not** registered, **not** schema-
admitted, and SHOULD only appear in a token destined for a
verifier that has been explicitly configured to admit them via a
`local_predicate_allowlist` registered out-of-band.

## 4. Caveat-Set Canonicalisation Rule (§4-CSC)

The canonical hash of a caveat-set is a Phase-2 ratification of
behaviour that was previously implementation-defined. It is the
foundation of the TV-W-2 pin-stability guarantee (§6) and of the
future `caveat_hash` self-reference predicate (§3.4).

### 4.1 Definition

Let `C = [c_1, c_2, ..., c_n]` be the caveat-set of an authority
block or an append block, where each `c_i` is a UTF-8 string
admitting the schema in `wirelang/schemas/datalog-caveat.json`.

The **canonical caveat-set** of `C`, written `canonical(C)`, is
the JSON array obtained by applying the following four steps in
order:

1. **Whitespace normalisation.** Within each `c_i`, collapse all
   runs of ASCII space (U+0020) to a single space, strip leading
   and trailing space, and replace any other whitespace character
   (TAB U+0009, CR U+000D, LF U+000A) with a single space before
   collapsing. The grammar in
   `datalog-caveat-vocabulary.md` §4 is whitespace-tolerant; the
   canonical form fixes one specific whitespace shape so the hash
   is stable.
2. **Predicate-call dedup.** If two normalised caveats are
   byte-identical, the second occurrence is removed. (Producers
   that emit duplicate caveats are well-formed under v0.1 grammar
   but produce no semantic gain; canonicalisation removes the
   duplicate so the hash matches a producer that emitted only one.)
3. **Lexicographic sort.** Sort the deduplicated, normalised
   caveats as UTF-8 byte sequences in ascending order. Lexicographic
   sort is the canonical sort order; producers that build caveats
   in semantic groups MAY emit them in any order, but the canonical
   hash is computed over the sorted form.
4. **JCS-array serialisation.** Serialise the resulting array as a
   JSON array of strings using RFC 8785 (JSON Canonical
   Serialization). The `caveat_set_hash` is the SHA-256 of the
   resulting byte sequence.

The four steps compose: `canonical(C) = JCS(sort(dedup(normalise(C))))`.

### 4.2 Why these four steps and not fewer

**Why normalise whitespace?** Without whitespace normalisation, a
producer that emits `"time($t), $t < 2026-12-31T23:59:59Z"` and a
producer that emits `"time($t),$t < 2026-12-31T23:59:59Z"` (no
space after the comma) produce different hashes for the same
semantic content. The grammar in v0.1 §4 admits both. We choose
to make canonical form whitespace-stable rather than prescribe
exact whitespace at production time.

**Why dedup?** Biscuit-Datalog is set-semantic at the caveat
level: a duplicate caveat is a no-op. Pin-hashes that differ on
duplicate caveats would surface a semantic-equivalent state as a
hash-difference, polluting drift detection.

**Why lexicographic sort and not insertion order?** Semantic
producers (especially attenuators) often build caveats in a
group-then-emit pattern. Insertion order is a producer-internal
detail; lexicographic sort is a producer-independent canonical
order.

**Why JCS-array and not raw concatenation?** RFC 8785 is the
existing canonicalisation primitive used everywhere else in
Wirelang (AIP-document signatures, DID-document signatures, frame
hashing). Reusing it keeps the canonicalisation surface small.
Raw concatenation would require a separator-injection-attack
analysis for free-form Datalog strings; JCS-array sidesteps that
because the JSON-array delimiters are unambiguous.

### 4.3 What §4-CSC does NOT change

- **Authority/append-block signatures.** Block signatures continue
  to cover the JCS-canonicalised block payload as defined in
  `layer-3-capability-token.md` §3 — the signature is **not**
  recomputed over the canonical caveat-set. The block payload
  itself contains the caveat array in producer-emitted order; the
  canonical caveat-set is a *hashing* construct, not a *signing*
  construct.
- **Biscuit-Datalog evaluation.** Datalog evaluation continues
  per Biscuit-rs / biscuit-py semantics, which are insertion-
  order-independent at the fact level. §4-CSC affects only the
  pin-hash and the future `caveat_hash` self-reference.
- **Producer freedom.** A producer is free to emit caveats in any
  order; a verifier MUST evaluate them per Biscuit-Datalog
  set-semantics regardless of order. §4-CSC is a third party's
  hashing rule, not a producer or verifier behavioural rule.

### 4.4 The two compatibility cases

The Phase-1a working set (TV-W-1, the existing fixtures in
`wirelang/tests/fixtures/`) was produced **before** §4-CSC was
ratified. Two cases:

**Case I — fixtures with empty or single-element caveat-sets.**
Trivially canonical. No re-baselining needed.

**Case II — fixtures with multi-element caveat-sets where the
producer happened to emit caveats in lexicographic order.** Also
trivially canonical. No re-baselining needed if the existing
ordering coincidentally matches `sort()`.

**Case III — fixtures with multi-element caveat-sets in
semantic-group order that does not coincide with lex-sort.** A
re-baseline is required: the fixture must be regenerated under
§4-CSC and the pin-hash bumped. As of 2026-05-07, no Phase-1a
fixture is in Case III; the migration cost is therefore zero. A
future Phase-1b fixture (TV-W-2) MUST be produced under §4-CSC
from inception.

## 5. V-908 Federation Caveat Extension

V-908 (DNS-anchored AIP federation, ratified in
`wirelang/specs/wirelang-spec-v0-2.md` §6.5 and implemented in
Phase-1b Tag-5..Tag-8) provides the substrate for cross-org
capability flows. Two predicates from the Phase-2 sketch are
ratified here as **N2** (Normative-Deferred): vocabulary is
normative; evaluator availability is gated on the V-908
federation-resolver being reachable.

### 5.1 `peer_org(aip_id: did)`

- **Arity:** 1.
- **Argument type:** AIP DID URI (`aip:web:`, `aip:key:`).
- **Semantics.** The invoking persona's AIP document MUST be
  rooted at, or be reachable via a delegation chain that includes,
  the AIP `aip_id`. Used by multi-org capability flows where the
  issuer org delegates signing authority but pins the cross-org
  boundary.
- **Verifier behaviour (N2).**
  1. If the verifier carries the V-908 federation-resolver and
     the resolver advertises `cross_org_resolution=true` in its
     capability advertisement, evaluate the predicate by walking
     the resolved AIP delegation chain.
  2. Otherwise, reject the token with reason
     `peer_org-evaluator-unavailable`. The verifier MUST NOT
     accept the token by ignoring the predicate.
- **Operational flag.** A verifier deployment that needs to
  process tokens with `peer_org` predicates SHOULD set
  `federation_backend_required = true` in its operator
  configuration; the configuration boot-check fails if the V-908
  resolver is not reachable.
- **Typical usage.** `peer_org("aip:web:partner-a.example/personas/treasury-issuer")`.

### 5.2 `federation_route(route_id: string)`

- **Arity:** 1.
- **Argument type:** UTF-8 string identifying a registered
  federation route.
- **Semantics.** Token is valid only along the named federation
  route (e.g., `"wakir->partner-A->treasury"`). The verifier
  consults a federation-route registry; mismatched route is a
  rejection.
- **Verifier behaviour (N2).**
  1. If the verifier carries the V-908 route registry, evaluate
     the predicate by checking the inbound frame's transport
     metadata against the registered route definition.
  2. Otherwise, reject the token with reason
     `federation_route-evaluator-unavailable`.
- **Route registry format.** The route registry is itself a
  V-908-anchored artefact: each route definition is a JCS-
  canonicalised JSON document signed by the issuing org's AIP
  root key. Format spec is deferred to a follow-up document
  `wirelang/specs/federation-route-registry.md` (out of scope
  here); this section ratifies only the predicate-level vocabulary
  and the requirement that the registry exist as a V-908
  artefact.
- **Typical usage.** `federation_route("wakir->partner-a->treasury")`.

### 5.3 Cross-review hook (zone 2 with persona-engine)

Both `peer_org` and `federation_route` semantics overlap with the
persona-engine domain (cross-org persona registration, route
definition issuance). Implementation of the Phase-1b N2 evaluator
requires a cross-review-zone-2-extension consensus marker (HR-
protocolled) covering:

1. AIP-delegation-chain walking semantics.
2. Federation-route registry artefact format (JCS, signed,
   V-908-anchored).
3. Failure-mode catalogue: which `*-evaluator-unavailable`
   reasons surface where, and whether the AIP `verifier_capabilities`
   advertisement is the canonical source of evaluator presence.

This consensus marker is a Phase-2 implementation prerequisite,
not a ratification prerequisite for §5; the vocabulary is ratified
*now* so producers can begin emitting v0.2 tokens against
verifiers that advertise the right `verifier_capabilities`.

### 5.4 Schema implications

The JSON Schema `wirelang/schemas/datalog-caveat.json` is
extended in this ratification to admit the two N2-federation
predicates in its predicate-name pattern. The schema bump is
v0.1.0 → v0.2.0; v0.1.0 schema consumers continue to validate
v0.1 caveats against v0.1 schema, and v0.2.0 schema consumers
admit both v0.1 and v0.2 caveats.

The schema does NOT yet admit Class R reserved predicates (§3.3)
or Class P patch-eligible predicates (§3.4); they are reserved at
the vocabulary level (verifier fail-closed) but not admitted at
the schema level. This is intentional: reserving names without
schema-admission means a producer that accidentally emits a
reserved predicate fails immediately at JCS-validation time, not
later at Datalog-evaluation time.

### 5.5 Phase-1b N2 evaluator implementation note (informative)

Phase-1b Sprint-2 Tag-3 (S2-2) lands the live N2 evaluator for
`peer_org` and `federation_route` in
`wirelang/federation/n2_evaluator.py`. The evaluator is a pure
layer over an already-verified
`wirelang.identity.federation_resolver.FederatedResolveResult`
and a caller-supplied `RouteRegistry`. It does not consult the
network, the wall-clock outside of `eval_now`, or any state
beyond the supplied :class:`FederationContext`.

Module surface:

- `FederationEvaluator(context).evaluate_peer_org(aip_id_arg)`
  raises `PeerOrgMismatchError` /
  `FederationPredicateArgumentError` on rejection, returns
  `True` on accept.
- `FederationEvaluator(context).evaluate_federation_route(route_id_arg)`
  raises `FederationRouteUnknownError` /
  `FederationRouteExpiredError` /
  `FederationPredicateArgumentError` on rejection, returns
  `True` on accept.
- `evaluate_all(peer_org_arg=..., federation_route_arg=...)`
  short-circuits on the first failure (Biscuit-Datalog
  abort-on-failed-caveat semantics).

Phase-1b boundary (informative; the §5 ratification of the
predicates does not depend on these implementation choices):

- The `peer_org` argument is matched against the federation
  context's FTD `id` exactly. Phase-2 will extend this to
  delegation-chain walking (V-908 spec §6, out of scope here).
- The `federation_route` registry is the caller-supplied
  `RouteRegistry` Protocol; the Phase-1b reference is
  `InMemoryRouteRegistry`, the Phase-2 production target is a
  NATS-KV-backed registry (item I-11 vocabulary).
- The evaluator surfaces the registry entry's
  `wat_anchor_manifest_id` unchanged for Z2-cross-review-zone
  consumers; the evaluator itself does NOT anchor route-registry
  versions to WAT.

Determinism contract (T-N2-10): two re-runs of
`evaluate_all(...)` over the same context and registry instance
yield identical verdicts. The freshness of the underlying
FTD-doc is an upstream concern.

Test coverage:
`wirelang/tests/test_federation_n2_evaluator.py` — 14 tests
green (T-N2-01..10 plus 4 sanity probes).

### 5.6 Phase-1b NATS-KV backend implementation note (informative)

Phase-1b Sprint-2 Tag-4 (S2-3) lands the production-target backend
for the V-908 federation-route registry as
`wirelang/federation/route_registry_nats_kv_backend.py`. The Tag-3
N2 evaluator reserved `RouteRegistry` as a Protocol; this backend
supplies the durable form (item I-11 vocabulary). The Tag-3 module
surface is unchanged.

Module surface:

- `BUCKET_NAME = "wakir-federation-routes"` — the Phase-1b NATS-KV
  bucket name. Cross-reference: the orchestrator bucket-init
  inventory (`scripts/init-nats-buckets.py` `PHASE_1_BUCKETS`).
- `BUCKET_CONFIG` — documented configuration mapping (history=5,
  ttl_seconds=0, max_value_size=4096 B, storage=file, replicas=1).
  The drift-policy follows the same contract as the four Phase-1
  buckets: any deviation between the live cluster and these
  values is reported as drift, never auto-corrected.
- `VALUE_SCHEMA = "wakir.federation.route-registry-entry/1"` —
  embedded in every value envelope.
- `NatsKvRouteRegistry(kv, bucket_name=BUCKET_NAME)` — async
  backend with `get` / `put` / `delete` / `snapshot`.
- `RouteRegistryEnvelopeError`, `RouteRegistryConflictError`,
  `RouteRegistryBackendError` — typed errors.

Synchronous-evaluator bridge:

The N2 evaluator's `RouteRegistry` Protocol is synchronous. The
NATS-KV backend is async. The bridge is `snapshot()`: it
materialises the live bucket into an `InMemoryRouteRegistry`
which is then passed into a `FederationContext`. Per token, the
caller takes one snapshot and passes it through a single
evaluator pass; the determinism contract T-N2-10 is preserved
because the evaluator queries a frozen view, not the live KV.

Phase-1b boundary (informative):

- The bucket is single-node (replicas=1). Phase-2 will raise
  this to a multi-node KV with consistency guarantees.
- The orchestrator must register `BUCKET_NAME` in the
  `init-nats-buckets` driver before any production deployment;
  the backend assumes the bucket exists and is configured per
  `BUCKET_CONFIG`. The backend itself does NOT auto-create or
  auto-correct.
- Snapshot is full-bucket. Phase-2 may add a watch-based
  incremental snapshot; the synchronous-bridge contract makes
  the swap source-compatible.

Test coverage:
`wirelang/tests/test_federation_route_registry_nats_kv_backend.py`
— 13 tests green (T-NKV-01..10 plus 3 sanity probes).

## 6. TV-W-2 Pin-Stability Guarantee

TV-W-2 (`wirelang/specs/wirelang-tv-strategy.md` §2) pins three
verification-trace JSON files for the
α/β/γ-presentation-context test. Without §4-CSC, those pins drift
on every producer-internal change to caveat-emission order. With
§4-CSC, the pins are stable under the following guarantee.

### 6.1 What is pinned by TV-W-2

For each presentation context `X ∈ {α, β, γ}`, the TV-W-2
verification trace contains:

```
{
  "context":           "<one of α/β/γ>",
  "block_hashes":      ["<sha256 of authority-block payload>", ...],
  "caveat_set_hashes": ["<sha256 per §4.1 per block>", ...],
  "verify_status":     "<accept | reject>",
  "verify_reason":     "<canonical reason string | null>",
  "next_pubkeys":      ["<hex>", ...]
}
```

The `caveat_set_hashes` field is computed per §4.1; this is the
load-bearing field that §4-CSC stabilises.

### 6.2 The guarantee

If TV-W-2 fixtures are regenerated by the documented builder
against the same TV-W-1 persona-(0,0) Ed25519 sub-key, the same
ratified caveat-set, the same pinned `not_before` /
`not_after` timestamps, and the same pinned audience role-strings,
then the resulting `verification-trace` JSON hashes MUST match the
checked-in golden files byte-for-byte under both:

- the production CI lane (rfc8785 + cryptography);
- the sandbox CI lane (`_jcs_pure` Pure-Python).

This is a **cross-lane parity** guarantee identical in shape to
the TV-W-1 A2/A3/A4 acceptance criteria.

### 6.3 What may break the guarantee (re-baseline list)

The guarantee MAY be invalidated by one of the following events;
each event requires a workflow-PR re-baseline of the TV-W-2
fixtures:

1. **Vocabulary additions in §3.** A new predicate that becomes
   N1 / N2 may shift schema-pattern validation order; if a TV-W-2
   caveat is constructed using an N2-promotion path, fixture
   regeneration is required.
2. **§4-CSC clarifications.** A future patch to §4 (e.g., refining
   the whitespace-normalisation rule to handle Unicode
   whitespace classes beyond the four ASCII whitespace
   characters) may shift `caveat_set_hashes`. Such a patch is a
   spec event in its own right and triggers re-baseline.
3. **Schema v0.2.0 → v0.3.0 bump.** Promoting Class R predicates
   to N1 / N2 changes the schema pattern and thus fixture validity.
4. **Biscuit-rs/py upstream patch that changes block-payload
   layout.** Block hashes (separate from `caveat_set_hashes`) are
   sensitive to upstream layout. Documented as out-of-our-control
   in `wirelang/specs/layer-3-capability-token.md` §7; a re-
   baseline is required when upstream lands such a patch.

### 6.4 What does NOT break the guarantee

The guarantee explicitly survives the following non-events:

- **Producer-internal caveat-emission-order change.** §4-CSC sorts.
- **Whitespace cosmetic change in producer-side caveat strings.**
  §4-CSC normalises.
- **Duplicate-caveat emission by an over-eager attenuator.** §4-
  CSC dedupes.
- **TV-W-1 persona pin-pack regeneration that does not touch
  persona-(0,0) Ed25519 sub-key bytes.** TV-W-2 inputs are
  pin-pack-key-anchored, not pin-pack-hash-anchored.

### 6.5 Drift surface for TV-W-2

The drift envelope from Phase-1b Tag-12 (`production - sandbox =
144 ±5`) covers TV-W-2 once implemented. Adding the TV-W-2 test
module bumps `EXPECTED_DELTA` per Tag-12 protocol; the workflow-
PR re-baseline is the ratification event.

## 7. Tabular ratification summary

| Predicate | Class | Phase | Schema admit | Evaluator status |
|---|---|---|---|---|
| `action` | N1 | 1a | yes | active |
| `agent_did` | N1 | 1a | yes | active |
| `allowed_methods` | N1 | 1a | yes | active |
| `audience` | N1 | 1a | yes | active |
| `action_count_max` | N1 | 1a | yes | active |
| `attenuation_depth_max` | N1 | 1a | yes | active |
| `env` | N1 | 1a | yes | active |
| `geo_region` | N1 | 1a | yes | active |
| `nonce` | N1 | 1a | yes | active |
| `not_after` | N1 | 1a | yes | active |
| `not_before` | N1 | 1a | yes | active |
| `operation` | N1 | 1a | yes | active |
| `parent_token` | N1 | 1a | yes | active |
| `rate_limit` | N1 | 1a | yes | active |
| `read_only` | N1 | 1a | yes | active |
| `spawn_counter_max` | N1 | 1a | yes | active |
| `time` | N1 | 1a | yes | active |
| `wat_anchor` | N1 | 1a | yes | active |
| `attests` | N2 | 1b | yes | TEE-evaluator-gated |
| `tee_required` | N2 | 1b | yes | TEE-evaluator-gated |
| `peer_org` | N2 | 1b (NEW v0.2) | yes (NEW) | V-908-resolver-gated |
| `federation_route` | N2 | 1b (NEW v0.2) | yes (NEW) | V-908-route-registry-gated |
| `zk_proof_valid` | R | 2 | no | reserved |
| `zk_reputation_threshold` | R | 2 | no | reserved |
| `cross_org_quota` | R | 2 | no | reserved |
| `persona_state` | R | 2 | no | reserved |
| `persona_attested_after` | R | 2 | no | reserved |
| `wat_inclusion_proof_valid` | R | 2 | no | reserved |
| `persona_pin` | P | 1a-patch (deferred) | no | reserved |
| `caveat_hash` | P | 1a-patch (deferred) | no | reserved |

Counts: N1 = 18, N2 = 4 (2 from Phase-1b, 2 NEW in v0.2), R = 6,
P = 2, total = 30 names registered. Schema-admitted = N1 ∪ N2 = 22.

## 8. Implementation hooks

### 8.1 Hooks for the wirelang-eng implementation

- `wirelang/schemas/datalog-caveat.json` — pattern bumps to admit
  `peer_org` and `federation_route`. Schema `$id` bumps to
  `https://wakir.dev/wirelang/schema/datalog-caveat/0.2.0`.
- `wirelang/canonical/caveat_set.py` (NEW module) — implementation
  of §4 with both `_jcs_pure` and rfc8785 backends, exposing
  `canonical_caveat_set_hash(caveats: list[str]) -> bytes`.
- `wirelang/tests/test_datalog_vocabulary_phase_2.py` (NEW) —
  determinism tests for §4 and §6 (this document's §10 catalogue).

### 8.2 Hooks for the wat-eng cross-review

- `wat-leaf-projection.md` v2 work (out of scope here): consider
  whether a leaf-tuple should additionally carry the
  `caveat_set_hash` from §4.1 alongside the `capability_token_hash`
  it already records. The Phase-2 sketch §7 raises this question;
  ratification of the answer is wat-eng-owned and lives in a
  cross-review-zone-2 follow-up.
- The N2 `peer_org` / `federation_route` predicates do not change
  WAT leaf shape directly; they affect verifier behaviour, which
  is separately audit-anchored as a meta-event when an
  `*-evaluator-unavailable` rejection fires.

### 8.3 Hooks for the persona-engine cross-review

- AIP-document `verifier_capabilities` extension: an array of
  evaluator-presence advertisements (e.g.,
  `["v908-federation-resolver", "tee-attestation"]`). Producers
  consult the consumer's AIP document before emitting v0.2 tokens
  with N2 caveats.
- Persona-engine cross-org-registration semantics: how a persona
  becomes resolvable by `peer_org` evaluation. Out of scope here;
  in scope for `wirelang/specs/identity-substrate.md` §3.2 plus
  the persona-engine substrate spec.

## 9. Migration path from sketch to ratified

The Phase-2 sketch (`datalog-caveat-vocabulary-phase-2-skizze.md`)
is **superseded** by this document. The sketch remains in the
repository as historical reference until the next housekeeping
sweep removes it; verifiers and producers MUST cite this document
(not the sketch) in any normative reference.

Concrete migration steps for an implementer that previously
referenced the sketch:

1. Replace any reference to "Phase-2 sketch §X" with "Phase-2
   ratified §Y" using the §-correspondence table:

   | Sketch § | Ratified § | Notes |
   |---|---|---|
   | sketch §3.1 (zk-Caveat) | §3.3 (Class R) | unchanged status |
   | sketch §3.2 (peer_org / federation_route) | §3.2 (Class N2) + §5 | promoted to ratified |
   | sketch §3.2 (cross_org_quota) | §3.3 (Class R) | unchanged status |
   | sketch §3.3 (persona-state) | §3.3 (Class R) | unchanged status |
   | sketch §3.3 (persona_pin) | §3.4 (Class P) | promotion-path documented |
   | sketch §3.4 (WAT-aware) | §3.3 (Class R) + §3.4 (Class P) | wat_inclusion_proof_valid stays R; caveat_hash moves to P |
   | sketch §6 (ignore-unknown) | §2 last paragraph | non-ratified, requires ADR |
   | sketch §7 (WAT cross-review) | §8.2 | unchanged content |

2. Update verifier evaluator-table to include `peer_org` and
   `federation_route` as N2.
3. Implement §4-CSC for any pin-stability use case.
4. Bump schema `$id` to `0.2.0` and add the two N2-federation
   predicates to the pattern.

## 10. Conformance test catalogue

This section enumerates the determinism tests that
`wirelang/tests/test_datalog_vocabulary_phase_2.py` MUST carry.
Each test is a determinism probe for one ratified clause.

1. **T-CSC-01 — empty caveat-set is canonical.** `canonical([])`
   produces the JCS-empty-array byte sequence
   `b"[]"` and SHA-256
   `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.
2. **T-CSC-02 — single-caveat canonicalisation.** `canonical(["action(\"x\")"])`
   produces a stable hash; recompute from the function and from
   a hand-canonicalised JCS string and compare.
3. **T-CSC-03 — whitespace normalisation.** Two semantically
   identical caveat-sets that differ only in interior whitespace
   produce identical `caveat_set_hash` values.
4. **T-CSC-04 — dedup preserves single occurrence.** A caveat-set
   `[c, c]` produces the same hash as `[c]`.
5. **T-CSC-05 — sort produces order-independence.**
   `canonical([a, b])` == `canonical([b, a])` for all admissible
   `a, b`.
6. **T-CSC-06 — JCS-array stability.** Round-tripping the
   canonical JCS-array byte sequence through `json.loads` and
   re-canonicalising produces the same bytes (idempotence).
7. **T-V0.2-01 — schema admits `peer_org`.** A caveat
   `peer_org("aip:web:example/personas/issuer")` validates against
   the v0.2 schema.
8. **T-V0.2-02 — schema admits `federation_route`.** A caveat
   `federation_route("wakir->partner-a->treasury")` validates
   against the v0.2 schema.
9. **T-V0.2-03 — schema rejects Class R predicates.** A caveat
   `zk_proof_valid("...", "...")` is rejected by the v0.2 schema
   (reserved-but-not-admitted).
10. **T-V0.2-04 — schema rejects Class P predicates.** A caveat
    `persona_pin("...")` is rejected by the v0.2 schema until the
    promotion-path patch lands.

The catalogue is intentionally minimal-coverage (10 tests) at
ratification time. TV-W-2 implementation in Tag-16+ adds the
trace-pin-stability tests on top of this base.

## 11. Out of scope

- ADR work for the optional `vocabulary_migration_mode`
  ignore-unknown-with-audit pattern. Operational risk model,
  migration-window length, alert thresholds, audit-event schema
  belong in a separate ADR not yet drafted.
- Concrete federation-route-registry artefact format (deferred to
  `wirelang/specs/federation-route-registry.md`).
- Promotion of Class P (`persona_pin`, `caveat_hash`) to Class N1
  via v0.1.x patch. Each promotion is its own ratification event.
- Class R substrate roll-out (zk-backend, persona-state registry,
  WAT manifest resolver, distributed quota counter). Each is its
  own engineering programme.

## 12. Brand-Guide §9 compliance

This ratification uses only role-strings and abstract identifiers
in its illustrative material (`treasury-issuer`, `partner-a`,
`role=consumer-A`, etc.). No personal clear names appear.

— *role: wirelang-spec-owner*
