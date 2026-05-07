<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Wakir Datalog Caveat Vocabulary v0.1

This document specifies the Phase-1a Wakir Datalog vocabulary used inside
Layer-3 capability tokens (Biscuit v3 authority and append blocks). It
extends the eight-predicate working draft from
[`wirelang/specs/layer-3-capability-token.md`](layer-3-capability-token.md)
§4 to a full eighteen-predicate vocabulary suitable for treasury,
inter-agent and TEE-aware capability flows.

The matching JSON Schema is
[`wirelang/schemas/datalog-caveat.json`](../schemas/datalog-caveat.json).

## 1. Scope and non-goals

**In scope.** Predicate name, arity, argument-type expectations,
semantics, typical use, an illustrative example per predicate, and a
formal grammar for the syntax that JSON-Schema validation accepts.

**Out of scope.** Full Biscuit-Datalog operational semantics
(implication, fact ingestion, fixed-point evaluation). Those live with
the Biscuit-rs / biscuit-py implementation. Type-level validation
(e.g. checking that a `time($t)` argument resolves to an RFC 3339
timestamp at evaluation time) is performed by the Biscuit verifier.

## 2. Argument-type primitives

Caveat arguments use the following type tags throughout this document:

| Tag | Meaning |
|---|---|
| `string` | UTF-8 quoted string. |
| `int` | 64-bit signed integer. |
| `bool` | `true` or `false`. |
| `timestamp` | RFC 3339 / ISO 8601 date-time, UTC. |
| `bytes_hex` | Lowercase hex string. |
| `did` | A DID URI (`did:web:...` or AIP identifier `aip:web:` / `aip:key:ed25519:`). |
| `var` | A Datalog variable reference, written `$name`. |

## 3. Predicate vocabulary

### 3.1 Time and validity

#### `time($t: var)`

- **Arity:** 1.
- **Semantics.** Bind the verifier-provided current time to the
  variable `$t`. Used together with comparison operators to express
  validity windows.
- **Typical usage.** `time($t), $t < 2026-12-31T23:59:59Z`.
- **Example.**
  `time($t), $t > 2026-05-06T00:00:00Z, $t < 2026-05-13T00:00:00Z`

#### `not_before(at: timestamp)`

- **Arity:** 1.
- **Semantics.** The token MUST NOT be considered valid before the
  given timestamp. Mirrors the authority-block ``not_before`` field
  but expressible as a caveat for derived/append blocks.
- **Typical usage.** `not_before(2026-05-06T00:00:00Z)`.

#### `not_after(at: timestamp)`

- **Arity:** 1.
- **Semantics.** The token MUST NOT be considered valid after the
  given timestamp. Mirrors authority-block ``not_after``; in append
  blocks this can only further-restrict.
- **Typical usage.** `not_after(2026-05-13T00:00:00Z)`.

### 3.2 Audience and identity

#### `audience(uri: string)`

- **Arity:** 1.
- **Semantics.** Restrict the consumer side. The verifier matches the
  request's audience identity (DID URI or AIP identifier) against
  this string. Wildcards are not supported in v0.1.
- **Typical usage.** `audience("did:web:wakir.dev:personas:treasury-agent")`.

#### `agent_did(did: did)`

- **Arity:** 1.
- **Semantics.** The invoking agent's DID URI. Used by attenuation
  blocks to bind a delegated capability to a specific sub-agent
  identity. Distinct from `audience` in that `audience` is the
  *target* of the action and `agent_did` is the *invoker*.
- **Typical usage.** `agent_did("did:web:wakir.dev:personas:cfo-agent")`.

### 3.3 Operations and actions

#### `action(name: string)`

- **Arity:** 1.
- **Semantics.** Allowed action verb. Wakir convention uses
  dot-separated namespaces (e.g. `treasury.read.balance`,
  `treasury.submit.tx`).
- **Typical usage.** `action("treasury.read.balance")`.

#### `operation(name: string)`

- **Arity:** 1.
- **Semantics.** Synonym for `action` at the protocol-binding layer;
  retained because some upstream protocol bindings (Wirelang frames,
  CloudEvents) carry an ``operation`` field where ``action`` would be
  ambiguous.
- **Typical usage.** `operation("submit_tx")`.

#### `allowed_methods(methods: string)`

- **Arity:** 1.
- **Semantics.** Comma-separated whitelist of HTTP/RPC methods
  allowed on the protected resource.
- **Typical usage.** `allowed_methods("GET,HEAD")`.

#### `read_only(flag: bool)`

- **Arity:** 1.
- **Semantics.** When `true`, the token is restricted to read-only
  operations. The verifier rejects any action whose effect class
  is not ``read``.
- **Typical usage.** `read_only(true)`.

### 3.4 Environment and rate

#### `env(name: string)`

- **Arity:** 1.
- **Semantics.** Environment classifier (``dev``, ``staging``,
  ``prod``). Verifiers reject mismatched environments before
  signature verification.
- **Typical usage.** `env("prod")`.

#### `rate_limit(n: int)`

- **Arity:** 1.
- **Semantics.** Maximum number of invocations per verifier-defined
  window. Caveat does not specify the window length; that lives in
  verifier configuration. Composing two `rate_limit` caveats takes
  the minimum (Biscuit-Datalog attenuation rule).
- **Typical usage.** `rate_limit(100)`.

#### `action_count_max(n: int)`

- **Arity:** 1.
- **Semantics.** Hard upper bound on total invocations across the
  token's validity window, independent of any rate window.
- **Typical usage.** `action_count_max(10)`.

#### `geo_region(region: string)`

- **Arity:** 1.
- **Semantics.** Geographic region restriction, ISO 3166-1 alpha-2
  country codes or regional aggregates (``EU``, ``US``).
- **Typical usage.** `geo_region("EU")`.

### 3.5 Replay and chain integrity

#### `nonce(value: bytes_hex)`

- **Arity:** 1.
- **Semantics.** Per-token nonce as a Datalog fact, primarily for
  replay-cache lookups. The authority-block-level ``nonce`` field is
  the canonical source; this caveat exists so attenuators can add
  *additional* per-block nonces if they need their own replay-domain.
- **Typical usage.** `nonce("a3f1...")`.

#### `parent_token(hash: bytes_hex)`

- **Arity:** 1.
- **Semantics.** SHA-256 hash of the parent capability token. Used
  by append blocks issued for delegation to bind the child
  attenuation to a specific parent token instance. The verifier
  rejects the child if the parent's hash does not match.
- **Typical usage.** `parent_token("c1b2...e9f0")`.

#### `spawn_counter_max(n: int)`

- **Arity:** 1.
- **Semantics.** Maximum BIP-32 spawn counter the invoking agent's
  sub-key may have. Lets a parent token cap how deep along the
  ``m/44'/wakir'/<persona-idx>'/<spawn-counter>'`` path the consumer
  may have derived. Defends against runaway spawn-and-delegate
  patterns.
- **Typical usage.** `spawn_counter_max(8)`.

#### `attenuation_depth_max(n: int)`

- **Arity:** 1.
- **Semantics.** Maximum number of append blocks allowed beyond the
  block carrying this caveat. ``0`` makes the current block the last
  attenuator. ``-1`` is rejected by the verifier.
- **Typical usage.** `attenuation_depth_max(3)`.

### 3.6 Trust anchoring

#### `attests(hash: bytes_hex)`

- **Arity:** 1.
- **Semantics.** Require the verifier to confirm that the invoking
  process attests to a specific TEE-attestation hash before granting
  authority. Phase-1b adoption per ADR-0023b. In Phase 1a the
  predicate is reserved and verifiers MUST reject tokens that
  reference it (fail-closed) until the attestation evaluator lands.
- **Typical usage.** `attests("4f9c...e108")`.

#### `tee_required(flag: bool)`

- **Arity:** 1.
- **Semantics.** When `true`, the verifier MUST observe an active
  TEE-attestation context for the invoking principal. Coarser-grained
  than `attests`: it does not bind a specific attestation hash, only
  presence. Phase-1b adoption.
- **Typical usage.** `tee_required(true)`.

#### `wat_anchor(id: string)`

- **Arity:** 1.
- **Semantics.** Cross-reference into the Wakir Audit Trail. ``id``
  resolves against the WAT module to a specific anchor (Bitcoin-OTS
  attestation in Phase 1b). Verifiers MAY consult the WAT to confirm
  that an event burst tied to this token has been anchored before
  authorising irreversible actions. Cross-review zone 2 with the WAT
  module owner.
- **Typical usage.** `wat_anchor("anchor-2026-05-06-w19")`.

## 4. Formal grammar (BNF)

The JSON-Schema pattern in
[`datalog-caveat.json`](../schemas/datalog-caveat.json) admits the
following subset of Biscuit-Datalog. The full Biscuit-Datalog grammar
is more permissive; this subset is what the Wakir Phase-1a registry
recognises for static-analysis tooling.

```
caveat        ::= predicate-call ( "," WS clause )*

predicate-call::= predicate-name "(" arg-list? ")"

predicate-name::= "action" | "env" | "time" | "audience" | "operation"
                | "action_count_max" | "read_only" | "attests"
                | "wat_anchor" | "rate_limit" | "agent_did"
                | "parent_token" | "nonce" | "spawn_counter_max"
                | "attenuation_depth_max" | "tee_required"
                | "allowed_methods" | "geo_region"
                | "not_before" | "not_after"

arg-list      ::= arg ( "," WS arg )*
arg           ::= variable | literal
variable      ::= "$" identifier
identifier    ::= [A-Za-z_][A-Za-z0-9_]*

literal       ::= string | integer | boolean | timestamp | hex-string
string        ::= '"' <UTF-8 chars except '"' and '\'> '"'
integer       ::= [-+]? [0-9]+
boolean       ::= "true" | "false"
timestamp     ::= ISO-8601-UTC-DATE-TIME    ; e.g. 2026-12-31T23:59:59Z
hex-string    ::= '"' [0-9a-f]+ '"'

clause        ::= comparison | predicate-call
comparison    ::= variable WS comparator WS literal
comparator    ::= "<" | "<=" | ">" | ">=" | "=" | "!="

WS            ::= " "+
```

Predicate-name extension to the grammar requires a vocabulary version
bump (see §6). The JSON-Schema pattern MUST be regenerated in lockstep.

## 5. Vocabulary-version mapping

| Vocabulary version | Wirelang version | Predicate count | Notes |
|---|---|---|---|
| v0.1 (this document) | wirelang/0.1 | 18 + 2 (`not_before`, `not_after`) | Phase-1a working set |
| v0.2 (Phase-2 ratified) | wirelang/0.2 | 22 schema-admitted (N1 + N2) | `datalog-caveat-vocabulary-phase-2.md`, Tag-15 |

Future revisions:

- v0.2 (Phase-1b ratified, Tag-15 2026-05-07):
  `datalog-caveat-vocabulary-phase-2.md` adds the Caveat-Set
  Canonicalisation Rule (§4-CSC), promotes `peer_org` and
  `federation_route` to schema-admitted N2-federation predicates,
  pins the TV-W-2 pin-stability guarantee, and ratifies the
  N1/N2/R/P predicate classification. The schema bumps to
  `https://wakir.dev/wirelang/schema/datalog-caveat/0.2.0`.
- v0.3 (Phase 2): zk-backend predicates, persona-state predicates,
  WAT-manifest-resolver predicates per ADR-0031 D2 — currently
  Class R reserved.

## 6. Brand-Guide §9 compliance

All examples in this document use role-strings (`treasury-issuer`,
`treasury-agent`, `cfo-agent`). No personal clear names appear in this
spec, the schema, or the example fixtures.

— *role: wirelang-spec-owner*
