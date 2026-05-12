# Wirelang NATS Subject Naming Convention and Mapping — v1

**Spec ID:** `wirelang/specs/nats-subject-mapping-v1`
**Status:** Draft (Phase-1b Sprint-2 Tag-1, S2-Item I-1)
**Owner:** Reza Tehrani (Dev-Engineering-2 / Wirelang)
**Cross-Review:** Kai Nakamura (Federation-Substrate-Ops, Zone H)
**Date:** 2026-05-07 (`date -u` 2026-05-07T11:04:32Z)
**Supersedes:** none (formalises the convention sketched in
`specs/wirelang-spec-v0-2.md` §4 and `specs/layer-0-2-overview.md`
§"Layer 0").
**Schema anchor:** `schemas/layer-0-transport.json` v0.1.0
(`subject.pattern` regex remains the single source of normative
truth; this spec narrows usage and documents semantics).

SPDX-License-Identifier: Apache-2.0

---

## 1 / Scope

This spec narrows and documents the NATS subject naming convention
used by the Wirelang transport substrate (Layer 0, ADR-0020 variant
alpha — NATS+JetStream). It addresses three questions that the
Phase-1a `layer-0-transport.json` schema left implicit:

1. **Which subject hierarchies are reserved** for AIP-Frame envelopes
   carrying Identity-Layer payloads (DID/AIP documents), Capability-
   Token-Layer payloads (Biscuit tokens) and Federation V-908 payloads
   (FTDs, federation events)?
2. **Which wildcard / subject-filter rules** are normative for stream
   bindings, consumer subscriptions and account permission grants?
3. **Which mapping** between Wakir org/persona/event identities and
   the dot-separated subject tokens is canonical, deterministic and
   round-trippable?

Out of scope: stream replication, durable-consumer ACK windows,
JetStream cluster topology — all operational concerns owned by
Federation-Substrate-Ops (Kai).

---

## 2 / Normative reference

The schema regex at `schemas/layer-0-transport.json` `subject.pattern`
remains the single source of pattern truth:

```
^wakir\.(dev|staging|prod)\.[a-z][a-z0-9_-]*\.[a-z][a-z0-9_.-]*(\.[a-zA-Z0-9_.-]+)?$
```

This spec MUST NOT widen the regex. It MAY reserve additional `domain`
and `event_type` tokens by enumeration, and it MAY narrow the `sub_id`
slot by sub-format conventions per anchor type. Any widening (e.g.
new env-tier, deeper hierarchy) requires schema `$id` minor-bump and
ADR-0023a-style cross-review.

---

## 3 / Subject Pattern v1

Canonical subject form (4 mandatory tokens, 1 optional):

```
wakir.<env>.<domain>.<event_type>[.<sub_id>]
```

| Token | Cardinality | Form | Example |
|---|---|---|---|
| literal | fixed | `wakir` | `wakir` |
| `<env>` | fixed enum | `dev` \| `staging` \| `prod` | `prod` |
| `<domain>` | reserved enum (§4) | `[a-z][a-z0-9_-]*` | `aip` |
| `<event_type>` | reverse-DNS reduced | `[a-z][a-z0-9_.-]*` (may contain `.`) | `signed.identity.published` |
| `<sub_id>` | optional | `[a-zA-Z0-9_.-]+` | persona slug, frame-id-prefix |

Token rules:

- **R1.** Subject MUST be lowercase ASCII except inside `<sub_id>`.
- **R2.** The literal token `wakir` is the org anchor and MUST NOT
  be rewritten (no `corp` / `wakir-labs` aliases at transport).
- **R3.** `<event_type>` MAY embed dots (reverse-DNS-style); the
  total subject still has 4 mandatory + 1 optional **anchor** tokens
  even though dot-counting differs.
- **R4.** `<sub_id>` length MUST be ≥ 1 character when present and
  MUST NOT exceed 64 octets to keep room for NATS subject limits.
- **R5.** `wirelangversion` (CloudEvents body) and the schema
  `$id`-version (Layer-2) are **not** encoded in the subject.
  Version-skew is a wire-format concern, not a transport routing
  concern.

---

## 4 / Reserved Domain Anchors (Phase-1b)

Phase-1b reserves the following `<domain>` tokens. Adding a new
domain requires this spec's `$id` minor-bump and Kai-acknowledgement.

| Domain | Purpose | Stream-name convention |
|---|---|---|
| `agent` | Agent-task lifecycle (assigned, accepted, completed). | `WAKIR_AGENT_TASK` |
| `wat` | WAT audit-trail anchors and Merkle-root events (Tomás owner). | `WAKIR_WAT_<topic>` |
| `aip` | AIP identity-document publish/rotate/revoke events. | `WAKIR_AIP_<topic>` |
| `cap` | Capability-token issue / append / seal / revoke events. | `WAKIR_CAP_<topic>` |
| `federation` | V-908 FTD publish, peer-org admit, federation-route events. | `WAKIR_FEDERATION_<topic>` |
| `meta` | Protocol-level meta events (schema deprecation, vocabulary bumps). | `WAKIR_META` |
| `treasury` | Treasury operations (DAI/USDC swap/transfer signals). Reserved, not yet wired. | `WAKIR_TREASURY` |
| `comms` | Outbound communications signals. Reserved, not yet wired. | `WAKIR_COMMS` |

Domains `aip`, `cap`, `federation` are introduced by this spec to
host AIP-Frame envelopes carrying the three Phase-1b layers
(Identity / Capability-Token / V-908-Federation).

---

## 5 / Reserved Event-Type Anchors per Domain

The following `<event_type>` enumerations are normatively reserved
under each domain. Producers MUST use these tokens; consumers MUST
treat unknown event-types as forward-compatible (skip with metric).

### 5.1 `aip` (AIP identity-document)

- `aip.document.published` — new AIP doc available at a `did:web:` URL.
- `aip.document.rotated` — issuer-key rotation (next-pubkey activated).
- `aip.document.revoked` — AIP doc revoked (with revocation reason).
- `aip.document.fetched` — observability event for resolver telemetry.

### 5.2 `cap` (Capability-Token)

- `cap.token.issued` — authority-block + initial caveats published.
- `cap.token.appended` — caveat-set narrowing block emitted.
- `cap.token.sealed` — sealing-block emitted, no further append allowed.
- `cap.token.revoked` — token revoked (with revocation reason).
- `cap.token.verified` — observability event from verifiers.

### 5.3 `federation` (V-908)

- `federation.ftd.published` — new FTD doc + DNS-anchor emitted.
- `federation.ftd.rotated` — FTD issuer-key rotation.
- `federation.peer.admitted` — `peer_org` admit event.
- `federation.route.added` — `federation_route` topology change.
- `federation.route.removed` — `federation_route` removal.

### 5.4 `wat` (cross-anchor with Tomás's WAT)

WAT is Tomás-owner; this spec only enumerates the cross-integration
event-types that Wirelang consumers may rely on:

- `wat.audit.anchor.created` — new Merkle-root anchored.
- `wat.leaf.federated.attached` — federation-token leaf projected.

### 5.5 `agent`, `meta`

- `agent.task.assigned`, `agent.task.accepted`, `agent.task.completed`.
- `meta.schema.deprecation`, `meta.vocabulary.bumped`,
  `meta.capability.issued`.

---

## 6 / Subject Hierarchy — Four Anchors

The subject string composes **four conceptual anchors** even though
its dot-token count varies. The mapping module (§9) materialises
each anchor as a typed slot.

### 6.1 Wakir-Org Anchor

Always the literal `wakir`. Single-org Phase-1b. Multi-org future
work is reserved for ADR-0023a-style cross-review (would introduce
a `<org-slug>` second token, breaking the regex at v1).

### 6.2 Persona Anchor

Encoded into the optional `<sub_id>` slot when the event is
attributable to a single persona. Format:

```
<sub_id> ::= <persona-slug>
<persona-slug> ::= [a-z][a-z0-9_-]{0,30}    (Wakir persona slug, e.g. "reza", "tomas", "kai")
```

Examples:

- `wakir.dev.aip.aip.document.published.reza`
- `wakir.prod.cap.cap.token.issued.mira`

When the event is **not** attributable to a single persona (federation
ratification, schema bump), the `<sub_id>` slot is omitted.

### 6.3 Wirelang-TV Anchor

Pin-pack roundtrip events use a structured `<sub_id>`:

```
<sub_id> ::= tv.w.<n>[.<step>]
n        ::= integer (1, 2, 3, …)
step     ::= [a-z0-9-]+    (e.g. "issued", "appended", "sealed")
```

Examples:

- `wakir.dev.cap.cap.token.issued.tv.w.2.issued`
- `wakir.dev.federation.federation.ftd.published.tv.w.3.replay`

### 6.4 Federation Anchor

V-908 federation events carry a structured `<sub_id>` encoding the
remote host slug:

```
<sub_id> ::= <host-slug>
<host-slug> ::= [a-z0-9-]+(\.[a-z0-9-]+)*
```

The `<host-slug>` is the FTD `domain` field with `.` retained,
because NATS subjects allow `.` inside `<sub_id>` per the schema
regex's last group `(\.[a-zA-Z0-9_.-]+)?`. Whitespace verification:
the regex's last group permits `.` inside `<sub_id>`, so
`wakir.example.com` becomes `wakir.dev.federation.federation.ftd.published.wakir-example-com`
**after slug normalisation** (replace `.` with `-` so the anchor
itself remains a single-token sub-id and does not collide with
event-type dots).

**Decision (R6):** federation host-slugs MUST use `.`-stripped form
(`wakir-example-com`), not the raw FQDN, to keep the four-anchor
abstraction dot-stable. The mapping module enforces this.

---

## 7 / Wildcard and Subject-Filter Rules

NATS supports two wildcards: `*` (single token) and `>` (rest-of-
subject). Wirelang adopts both with the following normative rules.

### 7.1 Stream Subjects (producer-side)

- **W1.** Stream `subjects` arrays MUST be rooted at the org+env
  anchor: `wakir.<env>.<domain>.>` is the canonical full-domain bind.
- **W2.** Cross-env streams are FORBIDDEN. A stream MUST NOT mix
  `dev`, `staging` and `prod`. Operationally enforced by NATS account
  permissions; spec-level recorded here.
- **W3.** Cross-org streams are FORBIDDEN at v1 (single-org).
  When multi-org is introduced, this rule will be revisited.

### 7.2 Consumer Subscriptions

- **W4.** Per-event-type subscriptions use `*` for the persona/sub-id
  slot: `wakir.prod.aip.aip.document.published.*` matches all
  publish events regardless of persona.
- **W5.** Per-domain subscriptions use `>`:
  `wakir.prod.cap.>` matches all capability-token events in prod.
- **W6.** Mixed-event-type subscriptions across the same domain MUST
  use `>` after `<domain>`; using `*` at the event-type level is
  ambiguous because `<event_type>` itself contains dots
  (reverse-DNS form).

### 7.3 Account Permission Reservations

The schema reserves a `permissions.publish[]` and
`permissions.subscribe[]` array. Phase-1b populates these from
JWT-SVID claims (ADR-0020). Spec-level rules:

- **W7.** Each persona's default publish permission is
  `wakir.<env>.<domain>.<event_type>.<persona-slug>`. The
  `<persona-slug>` slot scopes blast radius.
- **W8.** Subscribe permissions are wider by default (read-mostly
  audit posture); a persona MAY subscribe to `wakir.<env>.>`.
- **W9.** Sealed-WAT-anchor streams (`wakir.<env>.wat.>`) require
  explicit publish-grant; default-deny.

---

## 8 / Cross-Reference: Schema-Registry Inventory

The mapping module integrates with the Phase-1a-Tag-15
Schema-Registry (`schemas/registry.py`). Each NATS subject
that carries an AIP-Frame envelope binds — via the CloudEvents
`schemaid` attribute — to one of the eight schemas:

| Domain × event_type prefix | Schema `$id` | Source file |
|---|---|---|
| `aip.document.*` | `https://wakir.dev/wirelang/schema/aip-document/0.1.0` | `aip-document.json` |
| `cap.token.*` | `https://wakir.dev/wirelang/schema/layer-3-capability-token/0.1.0` | `layer-3-capability-token.json` |
| `cap.token.*` (caveat-set body) | `https://wakir.dev/wirelang/schema/datalog-caveat/0.2.1` | `datalog-caveat.json` |
| `federation.ftd.*` | `https://wakir.dev/wirelang/schema/federation-trust-document/0.1.0` | `federation-trust-document.json` |
| `*.*.*` (Layer-1 frame envelope) | `https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0` | `layer-1-wire.json` |
| `*.*.*` (Layer-2 semantic) | `https://wakir.dev/wirelang/schema/layer-2-semantic/0.1.0` | `layer-2-semantic.json` |
| transport binding metadata | `https://wakir.dev/wirelang/schema/layer-0-transport/0.1.0` | `layer-0-transport.json` |

The mapping module exposes `schema_for_subject(subject) -> Optional[str]`
returning the schema `$id` expected by consumers as an advisory hint.
Producers remain responsible for setting CloudEvents `schemaid`
correctly; the mapping is **advisory, not authoritative**.

---

## 9 / Mapping Module — Public Surface

Module path: `wirelang/nats/subject_mapping.py`. Python (Phase-1b
Bootstrap per ADR-0035 Errata 1).

### 9.1 Types

```python
@dataclass(frozen=True)
class SubjectV1:
    env: str            # one of "dev", "staging", "prod"
    domain: str         # one of the reserved domains (§4)
    event_type: str     # reserved event_type (§5)
    sub_id: Optional[str] = None  # persona-slug, tv-anchor, host-slug
```

### 9.2 Functions

- `build_subject(env, domain, event_type, sub_id=None) -> str`:
  build the canonical subject string; raises `SubjectFormatError`
  on rule violations (R1..R5, W1..W9). Output bytes MUST be
  identical to a hand-written canonical form (determinism
  invariant T-NSM-01).
- `parse_subject(subject) -> SubjectV1`: parse a canonical subject
  string; raises `SubjectFormatError` on regex mismatch or rule
  violations.
- `roundtrip(subject) -> str`: convenience for
  `build_subject(*parse_subject(subject))` returning byte-identical
  output (determinism invariant T-NSM-02).
- `validate_stream_pattern(pattern) -> None`: validate a stream
  `subjects[]` entry against W1..W3.
- `validate_consumer_filter(pattern) -> None`: validate a consumer
  filter against W4..W6.
- `schema_for_subject(subject) -> Optional[str]`: §8 advisory hint.
- `persona_slug(sub_id) -> Optional[str]`: extract persona-slug from
  sub_id if it matches §6.2.
- `tv_anchor(sub_id) -> Optional[Tuple[int, Optional[str]]]`: extract
  TV anchor `(n, step)` if it matches §6.3.
- `federation_host_slug(host_fqdn) -> str`: normalise FQDN to
  `.`-stripped slug per §6.4 R6.

### 9.3 Errors

```python
class SubjectFormatError(ValueError): ...
```

Subclasses are NOT introduced at v1 — the error message string carries
the rule-id (R1..R5, W1..W9) for grep-friendly debugging. Subclassing
may be introduced in a v1.1 errata if log-aggregation requires it.

---

## 10 / Determinism Invariants and Tests

The mapping module MUST satisfy the following invariants. Each gets
a determinism test (8+ tests required for Tag-1 acceptance).

| ID | Invariant | Test slug |
|---|---|---|
| T-NSM-01 | `build_subject(env, domain, event_type, sub_id)` is byte-deterministic across repeats. | `test_build_byte_deterministic` |
| T-NSM-02 | `roundtrip(s) == s` for every canonical subject. | `test_parse_roundtrip` |
| T-NSM-03 | All four reserved-domain × representative-event_type combinations parse and rebuild byte-identically. | `test_reserved_event_types_roundtrip` |
| T-NSM-04 | Persona-slug sub_ids round-trip and are extractable. | `test_persona_anchor_extract` |
| T-NSM-05 | TV-W anchors `tv.w.<n>[.<step>]` round-trip and extract. | `test_tv_anchor_extract` |
| T-NSM-06 | Federation host-slug normalisation is idempotent. | `test_federation_host_slug_idempotent` |
| T-NSM-07 | Cross-env stream pattern is rejected (W2). | `test_stream_pattern_cross_env_rejected` |
| T-NSM-08 | Consumer filter `wakir.prod.cap.*` rejected as ambiguous (W6). | `test_consumer_filter_ambiguous_rejected` |
| T-NSM-09 | `schema_for_subject` returns the eight-schema-inventory hint correctly. | `test_schema_for_subject_advisory` |
| T-NSM-10 | Schema regex compatibility — every `build_subject` output matches `schemas/layer-0-transport.json` `subject.pattern`. | `test_schema_regex_compatibility` |

(Implementation will deliver ≥ 10 tests; floor for acceptance is 8.)

### 10.1 Negative-control tests

In addition, the test module exercises six negative controls:

- Uppercase env (`Wakir.DEV.aip.…`) → reject (R1).
- Missing literal `wakir` token → reject (R2).
- Empty sub_id → reject (R4).
- Sub_id > 64 octets → reject (R4).
- Unknown domain (e.g. `foobar`) → reject (warn-list at v1, hard
  reject at v1.1; v1 implementation chooses **soft warn + accept**
  to preserve forward-compat per R5 spirit; test asserts the warn).
- Cross-env stream pattern `wakir.*.>` → reject (W2).

---

## 11 / Open Items (Sprint-2-Folge)

- **OI-1.** Persona-slug-Registry binding: §6.2 currently reads slugs
  from the `wirelang/identity/aip_document.py` slug derivation. A
  V-907 Persona-Identity-Registry handover (Selin-Lead, S2-4) will
  formalise this. Until then, the mapping module accepts any
  `[a-z][a-z0-9_-]{0,30}` slug.
- **OI-2.** Multi-org subject-prefix introduction (post-v1) requires
  schema `$id` bump and ADR-0023a-style cross-review.
- **OI-3.** JetStream replay-token reservation (e.g. `tv.replay.<id>`)
  is reserved for Phase-1c.

---

## 12 / Cross-Review Hooks

### 12.1 Zone H (Federation-Substrate-Ops, Kai)

- **Hook H-1.** §7 wildcard rules — Kai must confirm that NATS
  account-permission templates accommodate W7..W9.
- **Hook H-2.** §6.4 federation host-slug rule R6 (.→- stripping)
  — Kai must confirm that DNS-anchor compute path is unaffected
  (FTD `domain` field stays raw FQDN; only NATS subject token uses
  the slug).
- **Hook H-3.** §10.1 negative-control "unknown domain → soft warn
  + accept" — Kai-veto-window if SubOps prefers hard reject in
  Phase-1b (would tighten R5 spirit to fail-closed).

### 12.2 Zone Z2 (WAT × Wirelang Frame-Integration, Tomás)

- **Hook Z2-Subject.** §5.4 reserves `wat.*` event-types as a
  read-only listening contract for Wirelang consumers. No producer
  side here. Tomás review optional but recommended at next
  weekly cross-review.

### 12.3 Zone Z3 (OTS-Schema-Anker, Tomás)

- **Hook Z3-Schema-Inventory.** §8 inventory list includes
  `federation-trust-document.json` and the `datalog-caveat.json`
  v0.2.0 bump. Both are already Z3-K1/K2/K3-acknowledged
  (Phase-1b Tag-15). No new Z3 burden from this spec.

---

## 13 / Verification Stamp

- `date -u` 2026-05-07T11:04:32Z (`date` command run before this
  stamp).
- Schema regex at `schemas/layer-0-transport.json` `subject.pattern`
  inspected by hand (line 23): `^wakir\.(dev|staging|prod)\.[a-z][a-z0-9_-]*\.[a-z][a-z0-9_.-]*(\.[a-zA-Z0-9_.-]+)?$`.
  This spec narrows but does not contradict.
- Schema-Registry inventory cross-checked against
  `wirelang/schemas/__init__.py` and the eight on-disk schema files.
- Brand-Guide §9 sweep: no clear-name violations
  (only Wakir persona slugs in normative slug positions; "Wakir Labs"
  and "Wakir" are brand-permitted).

— Reza
