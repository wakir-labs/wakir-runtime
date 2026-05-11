<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

---
spec: wirelang-schema-registry
version: 0.8.0
status: draft
date: 2026-05-11
audience: implementers, integrators, operators
license: CC-BY-4.0
---

# Wirelang Schema Registry — NATS-KV Backend Specification (v0.8.0)

**Change log**

| Version | Date       | Change                                                 |
|---------|------------|--------------------------------------------------------|
| 0.1.0   | 2026-05-07 | Initial draft (Phase-1b Sprint-3 Tag-1).               |
| 0.2.0   | 2026-05-07 | Phase-1c CAS-pin contract reclassified from Phase-2 to Phase-1c and lands in Tag-3 (`put_with_revision` / `get_with_revision` / `SchemaRegistryConflictError`); §5.3 Phase-1c-Slot consumed; §5.4 added. Additive-only change relative to v0.1.0; M-2 / M-4 conformance preserved. |
| 0.3.0   | 2026-05-07 | Phase-1c watch-stream surface lands in Tag-4 (`watch()` / `WatchOp` / `WatchEvent` / `LiveSchemaSnapshot` / `open_watch_stream`); §5.3 OI-7-Phase-1c-watch slot CONSUMED; §5.5 added (watch-stream operational contract); §6.2 added (T-SR-WS-01..10 + 2 aux probes test inventory). Additive-only change relative to v0.2.0; M-2 / M-4 conformance preserved. |
| 0.4.0   | 2026-05-07 | Phase-1c publisher CLI lands in Tag-5 (`wirelang.schemas.publisher_cli`: `wakir-schema-registry publish` / `dry-run` argparse surface, `PublishReceipt`, `ExitCode` matrix); §5.3 OI-7-Phase-1c-publisher slot CONSUMED; §5.6 added (publisher CLI operational contract); §6.3 added (T-SR-PUB-01..12 test inventory). Additive-only change relative to v0.3.0; M-2 / M-4 conformance preserved. The CLI is a thin operator-input layer over the Tag-3 CAS-pin and Tag-1 LWW backends; it introduces no new on-the-wire envelope and no new validation gate. |
| 0.5.0   | 2026-05-07 | Phase-1c cross-bucket replication lands in Tag-6 (`wirelang.schemas.replication`: `SchemaReplicator`, `bootstrap_target_from_source`, `ReplicationConflictPolicy`, `ReplicationFilter`, `ReplicationMetrics`); §5.3 OI-7-Phase-1c-replication slot CONSUMED; §5.7 added (replication operational contract); §6.4 added (T-SR-REP-01..12 test inventory). Additive-only change relative to v0.4.0; M-2 / M-4 conformance preserved. The replication layer is a thin composition of Tag-1 LWW + Tag-3 CAS-pin + Tag-4 watch-stream surfaces; it introduces no new on-the-wire envelope, no new validation gate, and no new method on `NatsKvSchemaRegistry`. **Phase-1c is now feature-complete.** |
| 0.8.0   | 2026-05-11 | Phase-2 Sprint-4 Tag-4 lands the AIP-document transport-fetch composition layer (`wirelang.identity.aip_document_transport_fetch`: `fetch_aip_document`, `aip_web_to_https_url`, `AipFetchResult`, `AipDocumentTransportError`, `AipUrlSchemeError`, `AipDnsAnchorMismatchError`); §5.10 added (transport-fetch operational contract); §6.7 added (T-AIP-FT-01..12 test inventory). The module is a pure composition of the V-908 Phase-1b HTTPS-transport (`HTTPSDocumentTransport`) and the V-908 §3.4 DNS-anchor pattern, extended from FTD-doc to AIP-doc via the parallel TXT-record prefix `_wakir-aip.<host>` (same `v=1; sha256=<64-hex>` format). The transport-fetch layer is byte-orthogonal to AIP-document signature verification (`wirelang.identity.verify_aip_signature` is unchanged), the kid-resolver (Tag-3, §5.9) and the schema-registry backend (no method added to `NatsKvSchemaRegistry`); it closes the Sprint-4 Tag-3 §5.9 boundary item "AIP-document transport-fetch" so the Phase-2 canonical verifier flow is now end-to-end composable from an `aip:web:` identifier through to `verify_entry_signature`. Additive-only change relative to v0.7.0; M-2 / M-4 conformance preserved. Cross-Review-Zone-1 non-touched (the four Z-1-K-Sprint-4 consensus points remain byte-identical; `anchor_required` is an orthogonal Tag-4 hard-vs-soft toggle, not the Z-1-K-Sprint-4-4 STRICT-mode toggle). |
| 0.7.0   | 2026-05-11 | Phase-2 Sprint-4 Tag-3 lands the kid → Ed25519 public-key resolver (`wirelang.identity.kid_resolver`: `resolve_kid`, `list_resolvable_kids`, `ResolvedPublicKey`, `KidResolverError`); §5.9 added (kid-resolver operational contract); §6.6 added (T-KID-RES-01..12 test inventory); §5.8 `kid` resolution forward-reference linked. Z-1-K-Sprint-4-1 (kid-Resolver-Shape) closed by this module — `kid` matches `public_keys[i].kid` (the byte-accurate AIP-document JSON-Schema field; the Z-1-Sprint-4-Anhang consensus marker's "public_keys[i].id" wording refers to the same identifier slot). Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519) reinforced: the resolver filters out `alg == "secp256k1"` entries (those belong to the Biscuit capability-token-burst layer per the two-curve-stack consensus). The resolver does NOT fetch the AIP document over transport, does NOT validate the AIP-document signature, and does NOT mutate the schema-registry backend surface (no new method on `NatsKvSchemaRegistry`). Additive-only change relative to v0.6.0; M-2 / M-4 conformance preserved. |
| 0.6.0   | 2026-05-11 | Phase-2 entry-signing layer lands in Sprint-4 Tag-1 (`wirelang.schemas.entry_signing`: `SignedSchemaRegistryEntry`, `sign_entry`, `verify_entry_signature`, `envelope_with_signature`, `envelope_to_signed_entry`, `SchemaRegistrySignatureError`, `VerifyMode`); §5.3 OI-7-Phase-2-sig slot CONSUMED (Phase-2 hardening begins); §5.8 added (entry-signing operational contract); §6.5 added (T-SR-SIG-01..12 test inventory). Envelope schema **additive only**: optional `signature` slot on the existing `wakir.wirelang.schema-registry-entry/1` envelope (no `/2` envelope; backward-compatible with v0.5.0 readers). Tag-1 codec is unchanged; new `envelope_with_signature` / `envelope_to_signed_entry` helpers ship the round-trip for the optional slot. M-2 conformance preserved (additive-only field; absent slot is valid under permissive Phase-2-transition verify mode); M-4 conformance preserved (orthogonal to version axis). Cross-Review-Zone-1 (Identity-Substrate) **TRIGGERED**: signing reuses `wirelang.identity.aip_signing` Ed25519 + JCS + SHA-256 primitive byte-identical; the kid binds the signature to an AIP-document `public_keys` entry. `NatsKvSchemaRegistry` surface remains zero-new-method (signing happens at envelope-build time before `put` / `put_with_revision`). |

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

**Phase-1b Sprint-3 Tag-5 (this revision, additive over Tag-4):**

- The publisher CLI (`wirelang/schemas/publisher_cli.py`) exposing a
  `wakir-schema-registry` argparse surface with two subcommands:
  `publish` (operator publish flow with LWW / CAS-pin / create-only
  modes over the Tag-1 + Tag-3 backends) and `dry-run` (validate
  inputs and print the canonical receipt without touching the bucket).
- The CLI is a *thin* operator-input layer: it derives the canonical
  KV key (`schemas/<layer>/<name>/<version>`) and body-hash from
  operator input, runs two CLI-side gates (body has a non-empty
  `$id`; `--registered-by` is non-empty), then routes the entry into
  `NatsKvSchemaRegistry.put` (LWW) or `put_with_revision` (CAS / create-only).
- A stable `ExitCode` matrix (`OK=0`, `USAGE_ERROR=2`,
  `INPUT_ERROR=3`, `VALIDATION_ERROR=4`, `CAS_CONFLICT=5`,
  `BACKEND_ERROR=6`) for CI / pipeline gating.
- A canonical JSON receipt (`PublishReceipt`) on stdout for success
  and a JSON error envelope on stderr for failure; both are single
  lines of stable JSON for downstream tools.
- 12 hermetic determinism tests (T-SR-PUB-01..12) over an in-memory
  CAS-aware KV mock; the live-cluster connect path is the
  `_default_connect_factory`, which is never exercised at the test
  layer.
- This slot consumes **OI-7-Phase-1c-publisher**.

**Phase-1b Sprint-3 Tag-6 (this revision, additive over Tag-5):**

- The cross-bucket replication layer (`wirelang/schemas/replication.py`)
  exposing `SchemaReplicator` (one-way source → target replicator
  composing Tag-4 source-side watch-stream with Tag-1 / Tag-3
  target-side write paths), `bootstrap_target_from_source` (initial
  full-snapshot pass), `ReplicationConflictPolicy`
  (`SOURCE_WINS` LWW vs `CAS_PIN` CAS-pinned target writes),
  `ReplicationFilter` (curated-subset replication), and
  `ReplicationMetrics` (per-run counters surfacing bootstrap /
  live-tail / filter / conflict / envelope-error counts).
- The replicator is a *thin composition*: it adds no new method on
  `NatsKvSchemaRegistry`, no new field on `SchemaRegistryEntry`, and
  no new on-the-wire envelope. It is a separate module that consumes
  the existing Tag-1 + Tag-3 + Tag-4 surfaces.
- Tag-6 covers two production scenarios: multi-org federation (one
  upstream registry replicated into a downstream org's local cluster
  for offline lookup) and cross-cluster mirror (active-cluster →
  hot-standby tracking for fail-over readiness).
- 12 hermetic determinism tests (T-SR-REP-01..12) over the same
  in-memory CAS-aware KV mock used by Tag-3 / Tag-4 / Tag-5.
- This slot consumes **OI-7-Phase-1c-replication**. **Phase-1c is
  now feature-complete: all four Phase-1c slots (CAS, watch,
  publisher, replication) are consumed.**

**Phase-1c (out of scope, all slots now consumed):**

- ~~OI-7-Phase-1c-CAS~~ (CONSUMED in Tag-3).
- ~~OI-7-Phase-1c-watch~~ (CONSUMED in Tag-4).
- ~~OI-7-Phase-1c-publisher~~ (CONSUMED in Tag-5).
- ~~OI-7-Phase-1c-replication~~ (CONSUMED in Tag-6).

**Phase-2 Sprint-4 Tag-1 (this revision, additive over Tag-6):**

- The entry-signing layer (`wirelang/schemas/entry_signing.py`)
  exposing `SignedSchemaRegistryEntry` (wrapper dataclass for
  `SchemaRegistryEntry` + signature block), `sign_entry`,
  `verify_entry_signature`, `envelope_with_signature`,
  `envelope_to_signed_entry`, `SchemaRegistrySignatureError` (typed
  exception for malformed signature blocks), and `VerifyMode` enum
  (`PERMISSIVE` for Phase-2-transition, `STRICT` for Phase-2-end).
- The signing primitive is **Ed25519 over SHA-256 of the
  JCS-canonicalised entry envelope minus the `signature` slot** —
  byte-identical to the AIP-document signing convention
  (`wirelang.identity.aip_signing`). The signed pre-image is the
  same JSON envelope the Tag-1 codec emits, with the `signature`
  field stripped before canonicalisation.
- The envelope schema gains an **optional** `signature` slot of
  shape `{alg: "Ed25519", kid: <string>, signature: <128-hex>}`
  on the existing `wakir.wirelang.schema-registry-entry/1`
  envelope. No new envelope schema (`/2`) is introduced — v0.5.0
  readers see an unknown optional field and tolerate it. The
  Tag-1 envelope codec (`_entry_to_envelope` / `_envelope_to_entry`)
  is unchanged in Sprint-4 Tag-1; the new `envelope_with_signature`
  / `envelope_to_signed_entry` helpers in
  `wirelang.schemas.entry_signing` provide the signed round-trip
  while the Tag-1 codec stays bit-equal on unsigned envelopes.
- The `kid` references a `public_keys` entry on the registering
  agent's AIP document; the verification path resolves the kid
  to a 32-byte Ed25519 public key. Phase-2-Sprint-4 Tag-1 does
  NOT bundle a kid → key resolver (the resolver lives in
  `wirelang.identity`; the signing layer treats the public key as
  caller-supplied).
- **VerifyMode** policy:
  - `PERMISSIVE` (Phase-2-transition default): entries without a
    `signature` slot verify as `True` (legacy v0.5.0 entries pass).
  - `STRICT` (Phase-2-end): entries without a `signature` slot
    raise `SchemaRegistrySignatureError`. Phase-2-end activation
    is operator-controlled; Sprint-4 Tag-1 ships only the policy
    surface, not the activation switch.
- **`NatsKvSchemaRegistry` surface remains UNCHANGED** in Sprint-4
  Tag-1. Signing happens at envelope-build time: caller signs the
  entry, then `put` / `put_with_revision` accepts the signed
  envelope bytes opaquely (the backend transports the bytes
  unchanged through the NATS-KV layer). The backend's existing
  codec (`_entry_to_envelope` / `_envelope_to_entry`) is left
  unchanged in this slot; callers that need the round-trip with
  the optional `signature` slot use the new
  `envelope_with_signature` / `envelope_to_signed_entry` helpers
  in `wirelang.schemas.entry_signing` directly on the raw envelope
  bytes (the helpers parse and emit the same
  `wakir.wirelang.schema-registry-entry/1` envelope shape with the
  optional slot added).
- 12 hermetic determinism tests (T-SR-SIG-01..12) over Ed25519
  test vectors and the in-memory mock KV.
- This slot consumes **OI-7-Phase-2-sig**.
- **Cross-Review-Zone-1 (Identity-Substrate) TRIGGERED:** signing
  reuses the `wirelang.identity.aip_signing` JCS+SHA-256+Ed25519
  primitive byte-identical; the kid → AIP-document binding is the
  Identity-Substrate consumer touch-point. Tomás-side WAT
  Merkle-leaf builder is the natural downstream consumer of the
  signed envelope (signed envelope is byte-anchored to the WAT
  leaf via `schema_body_sha256`; the new `signature` slot extends
  the anchored byte-string). Cross-Review-Memo to Tomás recorded
  in Sprint-4 Tag-1 outbox §2.

**Phase-2 Sprint-4 Tag-3 (this revision, additive over Sprint-4 Tag-1):**

- The kid → Ed25519 public-key resolver
  (`wirelang/identity/kid_resolver.py`) exposing the pure functions
  `resolve_kid(aip_doc, kid, *, as_of=None, require_purpose=None)` and
  `list_resolvable_kids(aip_doc, *, as_of=None, require_purpose=None)`,
  the frozen dataclass `ResolvedPublicKey` (`kid` / `public_key` /
  `validafter` / `validuntil` / `purpose`), and the typed exception
  `KidResolverError`.
- The resolver lives in `wirelang.identity` (Reza-Default per
  Z-1-K-Sprint-4-1: "resolver-layer in `wirelang.identity` separat";
  the module is consumed by `wirelang.schemas.entry_signing` callers,
  not imported from it — the schema-registry module stays decoupled
  from the AIP-document trust layer).
- **Byte-accurate AIP-document field**: the resolver matches the
  caller-supplied `kid` argument against the `kid` field of each
  `public_keys` entry (the AIP-document JSON-Schema
  `wirelang/schemas/aip-document.json` defines the identifier field
  as `kid`, not `id`). The Z-1-Sprint-4-Anhang consensus marker's
  Reza-Default phrasing "public_keys[i].id" refers to the same
  identifier slot; §5.9 captures the byte-accuracy note explicitly so
  future implementations cannot drift on the field name.
- **Curve-Choice filter** per Z-1-K-Sprint-4-3 (Identity-Document-
  layer is Ed25519-only; secp256k1 entries belong to the capability-
  token-burst layer per the two-curve-stack consensus): the resolver
  filters out `alg != "Ed25519"` entries. A `kid` whose only
  matching entry is `secp256k1` raises `KidResolverError` rather than
  resolving across curves.
- **Validity-window enforcement** (caller-driven): if the caller
  supplies an `as_of` `datetime`, the resolver enforces
  `validafter <= as_of < validuntil` (open-ended `validuntil`
  treated as `+inf`). When `as_of` is omitted, no window check
  runs (historical-signature use-case). Production verifier paths
  SHOULD pass `as_of`.
- **Duplicate-kid policy**: a duplicate kid in `public_keys` is a
  structural failure of the AIP document; the resolver raises
  `KidResolverError` rather than silently selecting one entry. The
  AIP-document JSON-Schema does not forbid duplicates at write time;
  the resolver enforces single-match at read time.
- **Purpose filter**: optional `require_purpose` argument lets
  callers narrow to a purpose tag (`"biscuit-root"`,
  `"aip-signing"`, `"frame-signing"`, `"wat-anchor"`). Entries
  without a `purpose` field do not match when `require_purpose` is
  set.
- 12 hermetic determinism tests (T-KID-RES-01..12) over hand-built
  AIP-document fragments and a cross-layer test that ties the
  resolver end-to-end into `verify_entry_signature`.
- This slot closes **Z-1-K-Sprint-4-1** (kid-Resolver-Shape) and
  **Z-1-K-Sprint-4-3** (Curve-Choice reinforcement). Z-1-K-Sprint-4-2
  (JCS-Resolver-Lock) and Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-
  Owner) remain non-touched here (the resolver does not canonicalise
  and is policy-agnostic).
- **`NatsKvSchemaRegistry` surface remains UNCHANGED**. The resolver
  is a pure function over the AIP document the caller supplies; no
  backend method is added, no new envelope schema introduced, no new
  validation gate at write time. The resolver is invoked by callers
  who already hold an AIP document and a `SignedSchemaRegistryEntry`;
  they feed `resolved.public_key` into `verify_entry_signature`.
- **Boundary**: this slot does NOT fetch the AIP document over
  transport (`did:web` / `aip:web`); it does NOT validate the
  AIP-document `document_signature` (caller responsibility); it does
  NOT plumb the resolver into the schema-registry backend read path
  (verification stays caller-driven, consistent with Sprint-4 Tag-1
  Phase-2 boundary).

**Phase-2 Sprint-4 Tag-4 (this revision, additive over Sprint-4 Tag-3):**

- The AIP-document transport-fetch composition layer
  (`wirelang/identity/aip_document_transport_fetch.py`) exposing the
  pure function `fetch_aip_document(aip_id, *, transport,
  dns_resolver=None, anchor_required=False, dns_timeout_s=3.0)` and
  the URL-mapping helper `aip_web_to_https_url(aip_id) -> (url, host)`,
  the frozen dataclass `AipFetchResult` (`aip_id` / `url` / `host` /
  `aip_doc` / `body_bytes` / `jcs_sha256_hex` / `dns_anchor` /
  `anchor_matched`), and the typed exception tree
  `AipDocumentTransportError` → {`AipUrlSchemeError`,
  `AipDnsAnchorMismatchError`}.
- **URL mapping**: `aip:web:host[:port]/path` →
  `https://host[:port]/.well-known/aip/<path>.json` (RFC 8615
  well-known namespace; the `aip` subspace is the Wakir convention
  paralleling `_wakir-ftd` for FTD). A pre-resolved `https://...` URL
  passes through verbatim. Plaintext `http://` is rejected — V-908
  §3.3 is HTTPS-only end-to-end.
- **Transport delegation**: HTTPS fetch is delegated wholesale to the
  Phase-1b V-908 `HTTPSDocumentTransport` (Tag-8 PS-6 module); no
  transport invariants re-implemented at this layer. Transport-level
  failures (`HTTPSStatusError`, `HTTPSSchemeError`, etc.) propagate
  unwrapped so callers retain typed access to the V-908 §3.3
  invariants. The Tag-4 layer is therefore byte-thin over the existing
  transport.
- **DNS-anchor cross-check (Wakir-AIP variant of V-908 §3.4)**: the
  optional `dns_resolver` argument enables a TXT-record lookup at
  `_wakir-aip.<host>` returning a payload of shape
  `v=1; sha256=<64-hex>`. The format is byte-identical to V-908 §3.4's
  FTD-doc anchor; only the prefix differs (`_wakir-aip` vs
  `_wakir-ftd`). The fingerprint is compared against
  `SHA-256(JCS(body without document_signature))` computed locally
  (the same canonicalisation used by `wirelang.identity.aip_signing`).
- **Hard-vs-soft toggle**: `anchor_required` controls failure
  semantics:
  - `anchor_required=False` (default): DNS lookup is best-effort.
    Missing / malformed / mismatching TXT surfaces as `dns_anchor=None`
    or `anchor_matched=False` on the result; never raises from the
    anchor layer. The caller decides what to do.
  - `anchor_required=True`: any of {missing TXT, malformed TXT,
    fingerprint mismatch} raises `AipDnsAnchorMismatchError` with
    `expected` (the local JCS-anchor hex) and `observed` (the wire
    fingerprint hex when available) attributes. Calling with
    `dns_resolver=None` raises eagerly (the contract is unambiguous:
    requiring an anchor without a resolver is a caller bug).
- **JCS byte-anchor**: every successful fetch returns
  `result.jcs_sha256_hex` — the canonical AIP-doc fingerprint —
  computed via the same resolver-indirected JCS canonicaliser used by
  `wirelang.identity.aip_signing` (`rfc8785` when present;
  `_jcs_pure` fallback otherwise). This byte-anchor is the natural
  consumer surface for downstream WAT-leaf builders and cache tiers.
- 12 hermetic determinism tests (T-AIP-FT-01..12) over the URL
  mapping (canonical + edge-cases + rejected shapes), the HTTPS
  composition (happy path + 404 propagation + structural body
  failure), the DNS-anchor cross-check (soft-match / soft-absent /
  hard-mismatch / hard-absent), the eager-raise when
  `anchor_required=True` with `dns_resolver=None`, and the
  cross-layer composition with the Tag-3 `kid_resolver` plus a
  determinism / passthrough probe.
- This slot closes the Sprint-4 Tag-3 §5.9 boundary item
  "AIP-document transport-fetch (`did:web` / `aip:web` HTTPS bridge)
  for the kid-resolver"; the Phase-2 canonical verifier flow is now
  composable end-to-end from an `aip:web:` identifier through the
  fetch → resolve → verify chain without caller-side transport glue.
- **`NatsKvSchemaRegistry` surface remains UNCHANGED**. No backend
  method added, no new envelope schema introduced, no new validation
  gate at write time. The transport-fetch layer is orthogonal to the
  schema-registry backend; it sits at the Identity-Substrate boundary
  between the V-908 HTTPS-transport and the kid-resolver / signing
  verify path.
- **Cross-Review-Zone-1 (Identity-Substrate) non-touched**: the four
  Z-1-K-Sprint-4 consensus points remain byte-identical. The
  `anchor_required` toggle is an orthogonal Tag-4 hard-vs-soft policy,
  NOT the Z-1-K-Sprint-4-4 STRICT-mode signing toggle. JCS
  canonicalisation reuses the Z-1-K-Sprint-4-2 resolver-indirection
  byte-identical. Curve-choice is non-touched (the fetch layer is
  curve-agnostic — it fetches a document, not a key). Kid-Resolver
  surface is non-touched (the fetch layer feeds the resolver, does
  not modify its API).
- **Boundary**: this slot does NOT validate the AIP-document
  `document_signature` (caller composes with
  `wirelang.identity.verify_aip_signature`); does NOT validate the
  body against the JSON-Schema (Phase-1a `aip_resolver` ships that,
  sandbox-restricted to `rfc8785` + `jsonschema`); does NOT cache the
  result (the V-908 `HTTPSAipResolverCache` lives one layer up for
  the federation pipeline); does NOT mutate the schema-registry
  backend surface.

**Phase-2 (remaining reserved, out of scope here):**

- CAS-quorum upserts on top of multi-replica clusters
  (**OI-7-Phase-2-quorum** reserved).
- Schema-deprecation policy with overlapping-validity windows
  (**OI-7-Phase-2-deprecation** reserved).
- IPFS-anchored schema-document hashes
  (**OI-7-Phase-2-ipfs** reserved).
- Bidirectional replication with conflict-free CRDT-style merges
  (**OI-7-Phase-2-bidir-replication** reserved).
- Watch-stream resume-from-revision policy
  (**OI-7-Phase-2-resume** reserved).
- ~~AIP-document transport-fetch (`did:web` / `aip:web` HTTPS
  bridge)~~ (**CONSUMED in Sprint-4 Tag-4** by
  `wirelang.identity.aip_document_transport_fetch`; see §5.10).
- AIP-document signature-verification cache tier for the
  transport-fetch layer (the Tag-4 module is stateless; production
  callers compose with the V-908 `HTTPSAipResolverCache` or an outer
  tier). Phase-3 Identity-Substrate slot.
- STRICT-mode operator-activation toggle (Z-1-K-Sprint-4-4 remains
  open — the resolver is policy-agnostic; the toggle question is
  a Phase-2-roadmap consensus decision).

The Phase-1c slots are all consumed: Tag-3 consumed
**OI-7-Phase-1c-CAS**, Tag-4 consumed **OI-7-Phase-1c-watch**, Tag-5
consumed **OI-7-Phase-1c-publisher**, Tag-6 consumes
**OI-7-Phase-1c-replication**. Phase-2 Sprint-4 Tag-1 consumes
**OI-7-Phase-2-sig**; Sprint-4 Tag-3 closes the Z-1-Sprint-4-Anhang
follow-up `kid → public-key resolver`; Sprint-4 Tag-4 closes the
Sprint-4 Tag-3 §5.9 boundary item `AIP-document transport-fetch`.
The Phase-2 reserved slots are tracked as **OI-7-Phase-2-quorum /
-deprecation / -ipfs / -bidir-replication / -resume** plus the
STRICT-toggle follow-up slot noted above.

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

### 5.3 What Phase-1b Sprint-3 Tag-1 + Tag-3 + Tag-4 + Tag-5 + Tag-6 + Phase-2 Sprint-4 Tag-1 + Tag-3 + Tag-4 covers, and what Phase-2 still does NOT do

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

**Tag-5 (v0.4.0) lands (additive over Tag-4):**

- The publisher CLI module `wirelang.schemas.publisher_cli` with two
  argparse subcommands:
  - `publish`: operator publish flow with three modes:
    *last-write-wins* (default; routes through `put`),
    *CAS-pin* (`--expected-revision N`; routes through
    `put_with_revision`), and *create-only* (`--create-only`,
    equivalent to `put_with_revision` with revision 0; succeeds only
    if the entry is absent on the bucket).
  - `dry-run`: validate inputs and emit the canonical receipt without
    touching the bucket.
- A stable `ExitCode` matrix (`OK=0`, `USAGE_ERROR=2`,
  `INPUT_ERROR=3`, `VALIDATION_ERROR=4`, `CAS_CONFLICT=5`,
  `BACKEND_ERROR=6`) so CI / pipeline integrators can gate on
  specific failure classes.
- A `PublishReceipt` JSON object emitted on stdout for success
  (single line, `mode` / `key` / triple / `schema_id` / `schema_body_sha256`
  / `revision` / `expected_revision` / `registered_by` /
  `registered_at` / `supersedes`); a JSON error envelope on stderr
  for failure (`error` / `exit_code` / `message`).
- 8-12 additional hermetic determinism tests (T-SR-PUB-01..12) that
  pin the parser shape, exit-code matrix, receipt schema, error
  envelope, validation gate ordering, and bucket-state invariants
  on conflict.
- A `connect_factory` injection point so tests exercise the CLI
  end-to-end against an in-memory CAS-aware KV mock without a live
  NATS cluster. The default factory wires `nats.aio.client.Client`
  plus `js.key_value(BUCKET_NAME)` for production operators.
- **OI-7-Phase-1c-publisher slot consumed.**

**Tag-6 (v0.5.0) lands (additive over Tag-5):**

- The cross-bucket replication module
  `wirelang.schemas.replication` exposing `SchemaReplicator` (one-way
  source → target replicator), `bootstrap_target_from_source` (initial
  full-snapshot pass), and the supporting types
  `ReplicationConflictPolicy`, `ReplicationDecision`,
  `ReplicationFilter`, `ReplicationMetrics`.
- Composition contract: source-side reads use Tag-4 watch-stream
  surfaces (`open_watch_stream`, `WatchEvent`, `LiveSchemaSnapshot`
  via `snapshot()` for bootstrap); target-side writes use Tag-1 LWW
  (`put`) under `SOURCE_WINS` policy or Tag-3 CAS-pin
  (`put_with_revision`) under `CAS_PIN` policy.
- Two production scenarios covered: **multi-org federation** (a
  curated subset of an upstream registry mirrored into a downstream
  org's local cluster) and **cross-cluster mirror** (active-cluster →
  hot-standby tracking for fail-over readiness).
- Bootstrap is idempotent: a re-run on a byte-equal target advances
  the `bootstrap_skipped_idempotent` counter without touching the
  bucket. Idempotency is byte-comparison via the envelope codec
  (`_entry_to_envelope(a) == _entry_to_envelope(b)`).
- 12 additional hermetic determinism tests (T-SR-REP-01..12).
- A poisoned envelope on the source watch-stream halts replication
  with `SchemaRegistryEnvelopeError`; the metrics counter
  `envelope_errors` is incremented before re-raise. The target
  state is NOT corrupted (the poisoned event never reaches the
  target write path).
- **OI-7-Phase-1c-replication slot consumed. Phase-1c is now
  feature-complete.**

**Phase-1c is feature-complete; all four Phase-1c slots are
consumed (Tag-3 / Tag-4 / Tag-5 / Tag-6).**

**Phase-2 Sprint-4 Tag-1 (v0.6.0) lands (additive over Tag-6):**

- The entry-signing module `wirelang.schemas.entry_signing` exposing
  the `SignedSchemaRegistryEntry` wrapper dataclass, the pure
  functions `sign_entry` / `verify_entry_signature`, the envelope
  helpers `envelope_with_signature` / `envelope_to_signed_entry`,
  the typed exception `SchemaRegistrySignatureError`, and the
  `VerifyMode` enum (`PERMISSIVE` / `STRICT`).
- Signing reuses the Wakir AIP-document convention byte-identical:
  Ed25519 over SHA-256 of the JCS-canonicalised envelope minus the
  `signature` slot. The `signature` block is shaped
  `{alg: "Ed25519", kid: <string>, signature: <128-hex>}` and is
  byte-equal to the AIP-document signature block.
- The on-the-wire envelope schema is **additive only**: the existing
  `wakir.wirelang.schema-registry-entry/1` value-schema gains an
  **OPTIONAL** `signature` slot. No `/2` envelope is introduced; v0.5.0
  readers tolerate the new optional field (the Tag-1 backend codec is
  extended to round-trip the slot but does NOT validate the signature
  at read time).
- The `kid` references a `public_keys` entry on the registering
  agent's AIP document; resolving the kid to a 32-byte Ed25519
  public key is the caller's responsibility (Sprint-4 Tag-1 does
  not bundle a kid → key resolver; the resolver belongs in
  `wirelang.identity`).
- Verification policy is governed by `VerifyMode`:
  - `PERMISSIVE` (Phase-2-transition default): entries WITHOUT a
    `signature` slot verify as `True` (legacy v0.5.0 entries pass);
    entries WITH a signature slot are checked end-to-end.
  - `STRICT` (Phase-2-end): entries without a `signature` slot
    raise `SchemaRegistrySignatureError`. Phase-2-end activation
    is operator-controlled; Sprint-4 Tag-1 ships the policy
    surface only, NOT the activation switch.
- 12 additional hermetic determinism tests (T-SR-SIG-01..12) over
  Ed25519 test vectors and the in-memory mock KV.
- `NatsKvSchemaRegistry` surface is UNCHANGED. Signing happens at
  envelope-build time before `put` / `put_with_revision`; the
  signed envelope flows through the existing surfaces transparently.
- **OI-7-Phase-2-sig slot consumed. Phase-2 hardening begins.**

**Phase-2 Sprint-4 Tag-3 (v0.7.0) lands (additive over Sprint-4 Tag-1):**

- The kid → Ed25519 public-key resolver module
  `wirelang.identity.kid_resolver` exposing the pure functions
  `resolve_kid` and `list_resolvable_kids`, the frozen dataclass
  `ResolvedPublicKey`, and the typed exception `KidResolverError`.
- The resolver walks `aip_doc["public_keys"]` and matches on the
  `kid` field (byte-accurate per the AIP-document JSON-Schema).
  Filters: `alg == "Ed25519"`, optional validity-window (`as_of`),
  optional `require_purpose`.
- 12 hermetic determinism tests (T-KID-RES-01..12) including a
  cross-layer test that wires `resolve_kid` end-to-end into
  `verify_entry_signature`.
- The `wirelang.schemas.entry_signing` surface is UNCHANGED in this
  slot; the resolver is consumed by callers, not invoked from within
  the signing module (Reza-Default per Z-1-K-Sprint-4-1 places the
  resolver in `wirelang.identity` and keeps schema-registry signing
  decoupled from the AIP-document trust layer).
- **Z-1-K-Sprint-4-1 (kid-Resolver-Shape) CLOSED.** Z-1-K-Sprint-4-3
  (Curve-Choice = Ed25519 for the Identity-Document layer) is
  reinforced by the resolver's alg filter.

**Phase-2 Sprint-4 Tag-4 (v0.8.0) lands (additive over Sprint-4 Tag-3):**

- The AIP-document transport-fetch composition module
  `wirelang.identity.aip_document_transport_fetch` exposing the pure
  function `fetch_aip_document(aip_id, *, transport,
  dns_resolver=None, anchor_required=False)`, the URL helper
  `aip_web_to_https_url`, the frozen dataclass `AipFetchResult`, and
  the typed exception tree `AipDocumentTransportError` → {
  `AipUrlSchemeError`, `AipDnsAnchorMismatchError` }.
- The module is a pure composition over the Phase-1b V-908
  `HTTPSDocumentTransport` (Tag-8 PS-6) and the V-908 §3.4 DNS-anchor
  pattern (`dns_anchor.fetch_anchor`); it does not re-implement any
  transport invariants and does not introduce any new envelope or
  bucket-config surface.
- URL mapping: `aip:web:host[:port]/path` →
  `https://host[:port]/.well-known/aip/<path>.json` (Wakir
  RFC-8615 well-known convention). Pre-resolved `https://...` URLs
  pass through verbatim; plaintext `http://` is rejected (V-908 §3.3).
- DNS-anchor cross-check uses a Wakir-AIP TXT record at
  `_wakir-aip.<host>` (V-908 §3.4 pattern; same `v=1; sha256=<64-hex>`
  format) compared against `SHA-256(JCS(body without
  document_signature))`. The cross-check is toggled by
  `anchor_required`; soft mode surfaces a missing/malformed/
  mismatching anchor as `dns_anchor=None` or `anchor_matched=False`;
  hard mode raises `AipDnsAnchorMismatchError`.
- 12 hermetic determinism tests (T-AIP-FT-01..12) covering URL
  mapping (canonical + edge cases + rejected shapes), transport
  composition (happy path + 404 propagation + structural body
  failure), DNS-anchor (soft-match / soft-absent / hard-mismatch /
  hard-absent), eager-raise on missing resolver, cross-layer with
  the Tag-3 `kid_resolver`, and a determinism / passthrough probe.
- This slot closes the Sprint-4 Tag-3 §5.9 boundary item
  "AIP-document transport-fetch (`did:web` / `aip:web` HTTPS
  bridge)"; the Phase-2 canonical verifier flow is now end-to-end
  composable from an `aip:web:` identifier through fetch → resolve →
  verify.
- Cross-Review-Zone-1 (Identity-Substrate) **non-touched**: the four
  Z-1-K-Sprint-4 consensus points remain byte-identical (the
  `anchor_required` toggle is an orthogonal Tag-4 hard-vs-soft
  policy, NOT the Z-1-K-Sprint-4-4 STRICT-mode signing toggle).

**Phase-2 still does NOT include:**

- No CAS-quorum upserts on top of multi-replica clusters (Tag-3
  CAS-pin assumes the operator's `replicas: 1` Phase-1 setup; the
  contract holds bit-equally on a multi-replica bucket but is not
  exercised at the test layer).
- No deprecation policy (`OI-7-Phase-2-deprecation` reserved).
- No IPFS-anchored schema hashes (`OI-7-Phase-2-ipfs` reserved).
- No bidirectional replication (`OI-7-Phase-2-bidir-replication`
  reserved).
- No watch-stream resume-from-revision policy
  (`OI-7-Phase-2-resume` reserved).
- ~~No kid → public-key resolver in the signing layer~~
  (**CONSUMED in Sprint-4 Tag-3** by
  `wirelang.identity.kid_resolver`; see §5.9).
- No automatic signature verification on the backend read path
  (verification stays caller-driven; backend codec is pass-through
  for the optional slot).
- ~~No AIP-document transport-fetch (`did:web` / `aip:web` HTTPS
  bridge) — the kid-resolver assumes the caller has already fetched
  the AIP document; transport-fetch is a separate Identity-Substrate
  slot.~~ (**CONSUMED in Sprint-4 Tag-4** by
  `wirelang.identity.aip_document_transport_fetch`; see §5.10.)
- No AIP-document signature-verification cache tier (the Tag-4
  transport-fetch is stateless; production callers compose with
  the V-908 `HTTPSAipResolverCache` or an outer cache tier).
  Phase-3 Identity-Substrate slot.
- No STRICT-mode activation toggle (Z-1-K-Sprint-4-4 still open;
  the resolver is policy-agnostic).

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

### 5.6 Publisher CLI operational contract (Tag-5)

The publisher CLI is the canonical operator-input layer onto the
`wakir-schemas` bucket. It is a thin shell: every gate the CLI
applies is either an operator-input shape gate (so a malformed
JSON file is rejected at the file-read layer) or a routing decision
into the existing Tag-1 / Tag-3 backend gates.

**Subcommand surface:**

```text
wakir-schema-registry publish    \
    --schema-body PATH            \
    --layer {identity,wire,federation}  \
    --name NAME                   \
    --version VERSION             \
    --registered-by ACTOR         \
    [--registered-at RFC3339Z]    \
    [--supersedes SCHEMA_ID]      \
    [(--expected-revision N | --create-only)]  \
    [--connect-url URL]

wakir-schema-registry dry-run    \
    --schema-body PATH            \
    --layer {identity,wire,federation}  \
    --name NAME                   \
    --version VERSION             \
    --registered-by ACTOR         \
    [--registered-at RFC3339Z]    \
    [--supersedes SCHEMA_ID]
```

**Mode resolution:**

- No CAS flag → mode `lww`; routes through `NatsKvSchemaRegistry.put`.
- `--expected-revision N` (N ≥ 0) → mode `cas`; routes through
  `NatsKvSchemaRegistry.put_with_revision(entry, expected_revision=N)`.
- `--create-only` → mode `create-only`; routes through
  `put_with_revision(entry, expected_revision=0)`. Succeeds only if
  the entry is absent.
- `--expected-revision` and `--create-only` are mutually exclusive
  at the argparse layer (USAGE_ERROR / exit 2).

**Subject-mapping pattern (mirror of V-908 NATS-subject mapping):**

The CLI mirrors the V-908 federation NATS-subject-to-route_id
convention applied at the operator-input layer: the user supplies
the canonical identity triple (`--layer / --name / --version`) plus
a schema-body file. The CLI derives:

- The canonical KV key (`schemas/<layer>/<name>/<version>`) via
  `key_for_triple`; identity-triple validation runs eagerly so a
  malformed triple cannot reach the bucket.
- The canonical body-hash (`schema_body_sha256(body)` over JCS-canonical
  bytes) as the entry's `schema_body_sha256` field.
- The entry's `schema_id` from `body['$id']`; the backend's gate 1
  (`schema_id ↔ schema_body.$id`) therefore always matches by
  construction. The CLI does NOT permit operator-supplied
  `schema_id` overrides; the body is the canonical source.

There is no intermediate "subject" namespace; the triple is the
subject and the key derivation is the mapping. Mirror principle
preserved without introducing a parallel namespace.

**Gate ordering (REQUIRED):**

1. argparse parse → USAGE_ERROR (exit 2) for bad flag combinations.
2. File read of `--schema-body` → INPUT_ERROR (exit 3) for missing
   file, permission error, non-UTF-8 bytes, malformed JSON, or
   non-object root.
3. CLI-side validation gates → VALIDATION_ERROR (exit 4):
   - `schema_body['$id']` is a non-empty string.
   - `--registered-by` is a non-empty string after whitespace strip.
4. Identity-triple key derivation (`key_for_triple`) → INPUT_ERROR
   (exit 3) on a malformed triple component (this surfaces as
   `ValueError`).
5. Backend write gates (only on `publish`):
   - Tag-1 gates 1-3 (`schema_id ↔ $id`, body-hash match, key↔triple
     match) → VALIDATION_ERROR (exit 4).
   - Tag-3 CAS-pin call (only for `cas` and `create-only` modes) →
     CAS_CONFLICT (exit 5) on a `SchemaRegistryConflictError`.
   - Any other backend / transport exception → BACKEND_ERROR (exit 6).
6. Receipt emission on stdout for success; exit 0.

Gates 1-4 run BEFORE any NATS connect; on `dry-run`, gate 5 is
skipped entirely. The CLI is therefore safe to gate a CI pipeline:
a `dry-run` that returns OK guarantees that a subsequent `publish`
will not fail at gates 1-4.

**Receipt schema (success on stdout, single JSON line):**

```json
{
  "mode": "lww" | "cas" | "create-only" | "dry-run",
  "key": "schemas/<layer>/<name>/<version>",
  "layer": "<layer>",
  "name": "<name>",
  "version": "<version>",
  "schema_id": "<schema-body $id>",
  "schema_body_sha256": "<hex digest>",
  "revision": <int> | null,
  "expected_revision": <int> | null,
  "registered_by": "<actor>",
  "registered_at": "<RFC 3339 UTC>",
  "supersedes": "<schema_id>" | null
}
```

`revision` is the new live KV revision after a successful publish;
`null` for `dry-run`. `expected_revision` echoes the operator's
input (or 0 for `create-only`, `null` for LWW / dry-run).

**Error envelope (failure on stderr, single JSON line):**

```json
{
  "error": "<ExitCode name>",
  "exit_code": <int>,
  "message": "<human-readable message>"
}
```

`exit_code` matches the process exit status; `error` is one of
`USAGE_ERROR` / `INPUT_ERROR` / `VALIDATION_ERROR` / `CAS_CONFLICT` /
`BACKEND_ERROR`.

**Determinism contract (Tag-5 invariant):**

- Stdout and stderr are disjoint per invocation. On success, stderr
  is empty; on failure, stdout is empty.
- A failed publish (any non-OK exit code) leaves the bucket state
  byte-equal to the pre-call state. CAS conflicts are observable but
  non-mutating; validation errors abort BEFORE the network call;
  input errors abort BEFORE entry construction.
- Two identical `dry-run` invocations on the same `--schema-body`
  file produce byte-equal receipts (modulo `registered_at` if the
  operator omits the override flag). Test paths supply
  `--registered-at` explicitly so the receipt is byte-stable.

**Phase-1c boundary:**

- The publisher CLI is a *write-side* surface; it does NOT consume
  the watch-stream and does NOT post-verify the publish through the
  Tag-4 watch surface. Operators who want post-publish observability
  compose the CLI with a separate `LiveSchemaSnapshot` consumer (see
  §5.5).
- Multi-replica rollout sequencing is an integrator concern; the
  CLI publishes one entry per invocation.
- Authentication / capability enforcement is not in scope for
  Phase-1c; the CLI runs with whatever NATS credentials the
  operator's environment provides. Capability-token enforcement at
  the publisher boundary is an OI-7-Phase-2-sig hardening item.

### 5.7 Replication operational contract (Tag-6)

The replication layer is the canonical one-way (source → target)
mirror substrate for the `wakir-schemas` bucket. It is a thin
composition of three Phase-1c surfaces (Tag-1 LWW, Tag-3 CAS-pin,
Tag-4 watch-stream); the replicator itself adds no new method on
`NatsKvSchemaRegistry`, no new envelope field, and no new
validation gate.

**Composition contract:**

- **Source side (Tag-4):** the replicator opens a watch-stream over
  the source backend via `open_watch_stream(source)` and consumes
  decoded `WatchEvent` instances. Bootstrap is taken from
  `source.snapshot()` so the target starts from a complete,
  self-consistent view; the watch-stream then fills in the live tail.
- **Target side (Tag-3 CAS-pin or Tag-1 LWW):** writes go through
  `target.put` (under `SOURCE_WINS`) or
  `target.put_with_revision` (under `CAS_PIN`), depending on the
  configured `ReplicationConflictPolicy`.
- **Operator-input side (Tag-5):** the publisher CLI is the
  *separate* operator-driven write path; an operator can use it
  against the target bucket to forcibly re-apply a divergent entry
  from the source. The replicator does NOT itself bake an
  operator-override into the event loop.

**Conflict policy:**

```python
class ReplicationConflictPolicy(enum.Enum):
    SOURCE_WINS = "source-wins"  # target.put (LWW)
    CAS_PIN     = "cas-pin"      # target.put_with_revision
```

- `SOURCE_WINS` (default): source-of-truth is the source bucket;
  whatever the source emits lands on the target unconditionally.
  Concurrent target-side mutations are silently overwritten on the
  next source emit.
- `CAS_PIN`: target writes carry the target's currently-observed
  revision (read via `target.get_with_revision` just before the
  write). A target-side concurrent mutation between the read and
  the write surfaces as `SchemaRegistryConflictError` from the
  underlying backend; the replicator catches it, increments
  `metrics.cas_conflicts`, and continues with the next event by
  default. `halt_on_conflict=True` re-raises on first conflict.

**Filter contract:**

```python
ReplicationFilter = Callable[[WatchEvent], ReplicationDecision]

class ReplicationDecision(enum.Enum):
    APPLY = "apply"
    SKIP  = "skip"
```

The optional `filter_fn` is invoked on every observed event
(bootstrap synthetic events and live tail events alike). A `SKIP`
decision means the event is NOT applied to the target; the relevant
`*_skipped_by_filter` counter advances. Filters are pure (no I/O)
by contract.

**Metrics contract:**

```python
@dataclass
class ReplicationMetrics:
    bootstrap_applied: int
    bootstrap_skipped_by_filter: int
    bootstrap_skipped_idempotent: int
    events_applied_put: int
    events_applied_delete: int
    events_skipped_by_filter: int
    cas_conflicts: int
    envelope_errors: int
```

The replicator updates these counters synchronously inside its
event loop. Tests assert against the final shape; production
operators expose them via a metrics-pull endpoint (out of scope
for Tag-6).

**Bootstrap idempotency:**

`bootstrap_target_from_source` is byte-comparison-idempotent: if the
target already holds an entry that round-trips to the same envelope
bytes as the source-side entry (`_entry_to_envelope(a) ==
_entry_to_envelope(b)`), the bootstrap pass treats it as a no-op
(`bootstrap_skipped_idempotent` counter advances). Re-running the
bootstrap on a partially-replicated target is therefore safe.

Bootstrap ordering: source entries are written in `keys_sorted()`
order (lexicographic) for log-replay determinism in tests; nats-py
KV does not guarantee cross-key ordering anyway.

**Run loop:**

```python
replicator = SchemaReplicator(
    source=source_backend,
    target=target_backend,
    conflict_policy=ReplicationConflictPolicy.SOURCE_WINS,
    filter_fn=only_wire_layer,  # optional
)
metrics = await replicator.run()  # bootstrap + watch-tail
```

By default, `run()` runs the bootstrap pass then opens the source
watch-stream and consumes events until the stream terminates.
`run(bootstrap=False)` skips the bootstrap pass for callers that
have already seeded the target.

**Halt policy:**

- `halt_on_envelope_error` (default `True`): a poisoned source
  watch-stream event terminates `run` with a re-raised
  `SchemaRegistryEnvelopeError`. The metrics counter
  `envelope_errors` is incremented to 1 before re-raise.
- `halt_on_conflict` (default `False`): under `CAS_PIN`, a target
  CAS conflict terminates `run` with a re-raised
  `SchemaRegistryConflictError`. The metrics counter
  `cas_conflicts` is incremented before re-raise.

**Determinism contract (Tag-6 invariants):**

1. A bootstrap-only run leaves the target's keysets byte-equal to
   the source's keysets (modulo entries filtered out). Re-running
   the bootstrap on the same source state is a no-op for entries
   already byte-equal on the target.
2. A poisoned envelope on the source watch-stream raises
   `SchemaRegistryEnvelopeError` from the run loop and terminates
   replication. The target state is NOT corrupted because the
   poisoned event never reaches the target write path.
3. A target-side CAS conflict (under `CAS_PIN`) is observable
   through `metrics.cas_conflicts`; the replicator continues with
   the next event by default.
4. Source==target is rejected at construction with `ValueError`
   (no self-replication; the constructor enforces distinct backend
   instances).

**Phase-1c boundary:**

- Tag-6 is **one-way**: source → target. Bidirectional replication
  with conflict-free CRDT-style merges is `OI-7-Phase-2-bidir-replication`
  reserved.
- Tag-6 is **single-source / single-target** per replicator. Multi-source
  fan-in is achieved by running multiple `SchemaReplicator` instances
  against one target backend.
- Tag-6 has **no resume-from-revision policy**: a connection drop
  forces a full bootstrap-and-tail restart. Resume policies are
  `OI-7-Phase-2-resume` reserved.
- Tag-6 has **no envelope-side capability-token enforcement**; the
  replicator inherits whatever NATS credentials the operator's
  environment provides on each backend. Capability-token enforcement
  at the replication boundary is `OI-7-Phase-2-sig` reserved.

### 5.8 Entry-signing operational contract (Phase-2 Sprint-4 Tag-1)

The entry-signing layer is the canonical Ed25519 signature substrate
for schema-registry entries. It is a thin composition over the Tag-1
envelope codec and the existing `wirelang.identity.aip_signing`
JCS + SHA-256 + Ed25519 primitive; it adds no new method on
`NatsKvSchemaRegistry`, no new validation gate at the backend write
path, and no new envelope schema URI (the existing
`wakir.wirelang.schema-registry-entry/1` envelope gains an OPTIONAL
`signature` slot only).

**Signing primitive (byte-identical to AIP-document signing):**

1. **Strip** the `signature` slot from a deep copy of the envelope
   payload. The signature value cannot be part of its own pre-image.
2. **Canonicalise** with RFC 8785 JCS (resolver indirection: `rfc8785`
   when importable, the pure-Python fallback in
   `wirelang.identity._jcs_pure` otherwise; the two paths produce
   byte-identical output for the registry-entry envelope shape).
3. **Hash** with SHA-256 of the JCS bytes; sign the digest with
   Ed25519. Verification runs the same procedure in reverse.

**Signature block shape:**

```json
{
  "alg": "Ed25519",
  "kid": "biscuit-root-1",
  "signature": "<128-hex-char Ed25519 signature>"
}
```

`alg` is fixed at `"Ed25519"` in v0.6.0; other algorithms are
out of scope. `kid` references an AIP-document `public_keys` entry
identifier (caller-supplied; the registry layer does NOT resolve
kids to public keys). `signature` is the lowercase hex of the
64-byte Ed25519 signature.

**Wrapper dataclass:**

```python
@dataclass(frozen=True)
class SignedSchemaRegistryEntry:
    entry: SchemaRegistryEntry
    signature: Mapping[str, Any]  # signature block, frozen at construct time
```

A `SignedSchemaRegistryEntry` is the in-memory pair of a Tag-1
`SchemaRegistryEntry` and its detached signature block. The signature
block is stored on the envelope under the optional `signature` slot;
the wrapper makes the in-memory representation explicit.

**Public API:**

```python
def sign_entry(
    entry: SchemaRegistryEntry,
    ed25519_priv_key: bytes,
    *,
    kid: str,
) -> SignedSchemaRegistryEntry: ...

def verify_entry_signature(
    signed: SignedSchemaRegistryEntry | SchemaRegistryEntry,
    ed25519_pub_key: bytes | None = None,
    *,
    mode: VerifyMode = VerifyMode.PERMISSIVE,
    signature_block: Optional[Mapping[str, Any]] = None,
) -> bool: ...

def envelope_with_signature(
    signed: SignedSchemaRegistryEntry,
) -> bytes: ...

def envelope_to_signed_entry(
    blob: bytes,
) -> SignedSchemaRegistryEntry | SchemaRegistryEntry: ...
```

`envelope_with_signature` emits the canonical envelope bytes
(`wakir.wirelang.schema-registry-entry/1`) with the optional
`signature` slot populated. `envelope_to_signed_entry` is its inverse:
when the envelope carries a `signature` slot, it returns
`SignedSchemaRegistryEntry`; otherwise it returns the unsigned
`SchemaRegistryEntry` (parity with the Tag-1 codec).

**Verify-mode policy:**

```python
class VerifyMode(enum.Enum):
    PERMISSIVE = "permissive"  # Phase-2 transition default
    STRICT     = "strict"      # Phase-2 end
```

- `PERMISSIVE`: an unsigned entry (no `signature` slot, or a
  `SchemaRegistryEntry` passed to `verify_entry_signature` without
  a `signature_block` argument) verifies as `True`. A signed entry
  is verified end-to-end; a tampered signature raises
  `SchemaRegistrySignatureError` for structural failures and returns
  `False` for cryptographic failures.
- `STRICT`: an unsigned entry raises `SchemaRegistrySignatureError`
  with a missing-signature message. Phase-2-end activation is
  operator-controlled (out of scope for Sprint-4 Tag-1).

**Typed exception:**

`SchemaRegistrySignatureError` is the structural-failure error
class. It is raised on: missing `signature` slot under `STRICT`
mode, missing `alg` / `kid` / `signature` fields in the signature
block, unsupported `alg`, malformed signature hex, wrong signature
length, and wrong public-key length. A *cryptographic* mismatch
(valid structure, signature does not verify) returns `False` from
`verify_entry_signature`. The distinction matches the AIP-document
signing convention.

**Determinism contract (Phase-2 Sprint-4 Tag-1 invariants):**

1. **Byte-identical pre-image:** for any two `SchemaRegistryEntry`
   instances `a` and `b` such that `_entry_to_envelope(a) ==
   _entry_to_envelope(b)`, the SHA-256 of the JCS-canonicalised
   envelope-minus-signature is byte-identical. Signing is therefore
   deterministic with respect to entry content.
2. **Self-reference exclusion:** the `signature` slot is removed
   from the pre-image before canonicalisation. A signature can
   never sign over itself.
3. **Optional-slot backward compatibility:** envelopes WITHOUT a
   `signature` slot round-trip through the Tag-1 codec unchanged.
   v0.5.0 readers see v0.6.0 unsigned envelopes as byte-equal.
4. **Signature block schema rigidity:** the signature block MUST
   carry `alg == "Ed25519"`, a non-empty `kid`, and a 128-hex-char
   `signature`. Any deviation raises
   `SchemaRegistrySignatureError`. The block is the same shape as
   the AIP-document `document_signature` block.

**Cross-Review-Zone-1 (Identity-Substrate) touch:**

- The signing primitive is byte-identical to
  `wirelang.identity.aip_signing` (Ed25519 + JCS + SHA-256). The
  schema-registry signing module re-uses the same JCS resolver
  indirection (`rfc8785` with pure-Python fallback) for surface
  consistency.
- The `kid` field is a free-form string in Sprint-4 Tag-1; binding
  it to an AIP-document `public_keys` entry is the kid → key
  resolver's responsibility (out of scope for this slot). Cross-
  Review-Memo to Tomás (WAT-side) is recorded in Sprint-4 Tag-1
  outbox §2.

**Phase-2 Sprint-4 Tag-1 boundary:**

- Sprint-4 Tag-1 ships the signing primitive and verify-mode policy;
  it does NOT ship the kid → key resolver.
- Sprint-4 Tag-1 does NOT plumb signature verification into the
  backend read path; verification is caller-driven.
- Sprint-4 Tag-1 ships the `STRICT` mode policy surface but NOT
  the activation switch (operator-controlled toggle is a future
  Phase-2 slot).
- Capability-token gating on `registered_by` (mapping `kid` to
  an issuer-policy bundle) is reserved for a follow-up Phase-2
  slot; the current `registered_by` field stays free-form.
- The Tag-1 backend codec is extended to round-trip the optional
  `signature` slot; it does NOT validate the signature at read
  time (consistent with the design that verification is a separate
  caller-driven step).

**Forward reference (Sprint-4 Tag-3):** the `kid` referenced in
`signature.kid` is resolved to a 32-byte Ed25519 public key by
`wirelang.identity.kid_resolver.resolve_kid(aip_doc, kid)`. See §5.9
for the resolver operational contract.

### 5.9 kid-resolver operational contract (Phase-2 Sprint-4 Tag-3)

The kid-resolver layer binds the free-form `kid` string carried on a
signature block (§5.8) to a concrete 32-byte raw Ed25519 public key
read from an AIP document. It is a pure function in
`wirelang.identity.kid_resolver`; it does NOT mutate the
schema-registry backend, does NOT add a method to
`NatsKvSchemaRegistry`, and does NOT introduce a new envelope schema.

**Module location and rationale:**

The resolver lives in `wirelang.identity`, not in
`wirelang.schemas.entry_signing`. This placement reflects the
Z-1-K-Sprint-4-1 consensus marker default ("resolver-layer in
`wirelang.identity` separat"): the schema-registry signing module
treats the public key as caller-supplied, and the AIP-document trust
layer is the natural home for the kid → key binding. Callers compose
the two modules: read an AIP document, call `resolve_kid`, feed the
resolved public key into `verify_entry_signature`.

**Byte-accurate AIP-document field**

The Reza-Default phrasing in the Z-1-Sprint-4-Anhang consensus marker
("`kid` matched AIP-doc `public_keys[i].id` string") refers to the
identifier slot on each `public_keys` entry. The AIP-document JSON
Schema (`wirelang/schemas/aip-document.json` v0.1.0) defines this
field as `kid`, not `id`. The resolver matches on the `kid` field
byte-accurately; the consensus marker's `id` wording was a colloquial
reference to "the identifier" and is reconciled here by this byte-
accuracy note. Future implementations MUST match on `kid` to stay
schema-compliant.

**Public API:**

```python
@dataclass(frozen=True)
class ResolvedPublicKey:
    kid: str
    public_key: bytes                # 32-byte raw Ed25519
    validafter: Optional[datetime]
    validuntil: Optional[datetime]
    purpose: Optional[str]

def resolve_kid(
    aip_doc: Mapping[str, Any],
    kid: str,
    *,
    as_of: Optional[datetime] = None,
    require_purpose: Optional[str] = None,
) -> ResolvedPublicKey: ...

def list_resolvable_kids(
    aip_doc: Mapping[str, Any],
    *,
    as_of: Optional[datetime] = None,
    require_purpose: Optional[str] = None,
) -> list[str]: ...

class KidResolverError(Exception): ...
```

**Resolver filters (in order of application):**

1. **Required field** `aip_doc["public_keys"]` is a non-empty
   sequence of mappings; `kid` is a non-empty string. Violations
   raise `KidResolverError`.
2. **Kid match**: linear scan over `public_keys`, matching on
   `entry["kid"] == kid`. Zero matches → `kid not found`.
   ≥ 2 matches → `duplicate kid` (structural failure of the AIP
   document; the resolver refuses to silently pick a winner).
3. **Algorithm filter (Z-1-K-Sprint-4-3 reinforcement)**: the
   matched entry MUST have `alg == "Ed25519"`. A `secp256k1` entry
   raises `KidResolverError` — those keys belong to the Biscuit
   capability-token-burst layer (two-curve-stack consensus).
4. **Key-length validation**: `key_hex` MUST be a 64-char lowercase
   hex string decoding to 32 raw bytes.
5. **Validity-window enforcement (caller-driven)**: when `as_of` is
   supplied, the resolver enforces
   `validafter <= as_of < validuntil`. Open-ended `validuntil`
   (`None` or `null`) is treated as `+infinity`. Naive `as_of`
   datetimes are promoted to UTC. Production verifier paths SHOULD
   pass `as_of` to bind signatures to a point in time.
6. **Purpose filter (caller-driven)**: when `require_purpose` is
   supplied, the matched entry MUST have a `purpose` field byte-
   equal to the argument. Entries without a `purpose` field do not
   match. Default: no purpose filter.

**Determinism contract (Phase-2 Sprint-4 Tag-3 invariants):**

1. **Pure function**: `resolve_kid` does not mutate its input
   `aip_doc`. The frozen `ResolvedPublicKey` is the only output.
2. **Reproducible**: repeated calls on a byte-equal `aip_doc` and
   the same arguments produce equal `ResolvedPublicKey` instances
   (frozen-dataclass equality).
3. **Structural-vs-cryptographic split**: structural failures of
   the AIP document raise `KidResolverError`. A successfully-
   resolved key may still fail signature verification downstream —
   that crypto-failure surfaces as `False` from
   `verify_entry_signature`, not as `KidResolverError`. The split
   matches the entry-signing module's exception convention.
4. **Order-deterministic `list_resolvable_kids`**: returns a sorted
   list. Repeated calls produce byte-equal lists.

**Cross-Review-Zone-1 (Identity-Substrate) closure:**

- **Z-1-K-Sprint-4-1 (kid-Resolver-Shape) CLOSED** by this module.
- **Z-1-K-Sprint-4-3 (Curve-Choice for Schema-Registry-Sigs)
  reinforced**: `alg == "Ed25519"` filter enforced. The resolver
  cannot bridge from a secp256k1 entry to the Identity-Document
  signing layer.
- **Z-1-K-Sprint-4-2 (JCS-Resolver-Lock) non-touched**: the
  resolver does not canonicalise — it is a pure structural read.
- **Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-Owner) non-touched**:
  the resolver is policy-agnostic. The caller drives `VerifyMode`
  and decides when to require resolution.

**Phase-2 Sprint-4 Tag-3 boundary:**

- The resolver does NOT fetch the AIP document over transport
  (`did:web` / `aip:web` HTTPS bridge). Transport-fetch lives in a
  follow-up Identity-Substrate slot.
- The resolver does NOT validate the AIP-document
  `document_signature` slot. Establishing AIP-document trust is the
  caller's responsibility — `wirelang.identity.verify_aip_signature`
  is the natural companion.
- The resolver does NOT plumb into the schema-registry backend read
  path. Verification stays caller-driven (consistent with Sprint-4
  Tag-1 entry-signing boundary).
- The resolver does NOT bind `kid` to the schema-registry
  `registered_by` field. Capability-token gating on `registered_by`
  remains a future Phase-2 slot.

**Composition pattern (canonical end-to-end verifier flow):**

```python
# 1. Fetch and (caller-side) trust the AIP document.
aip_doc = fetch_aip_document_for(entry.registered_by)  # caller path

# 2. Resolve the signing kid to a public key.
from wirelang.identity import resolve_kid
resolved = resolve_kid(
    aip_doc,
    signed.signature["kid"],
    as_of=now_utc(),
    require_purpose="aip-signing",  # optional narrowing
)

# 3. Verify the schema-registry-entry signature end-to-end.
from wirelang.schemas.entry_signing import verify_entry_signature, VerifyMode
ok = verify_entry_signature(
    signed, resolved.public_key, mode=VerifyMode.STRICT,
)
```

This composition is the recommended Phase-2 verifier pattern.
Sprint-4 Tag-3 test T-KID-RES-03 exercises it end-to-end against the
RFC-8032 Ed25519 test-vector seeds.

### 5.10 AIP-document transport-fetch operational contract (Phase-2 Sprint-4 Tag-4)

The transport-fetch layer plugs the §5.9 boundary item "AIP-document
transport-fetch": the kid-resolver (§5.9) presumes the caller has
already obtained the AIP document, but does not specify how. Sprint-4
Tag-4 ships that step as a pure composition of two existing Phase-1b
primitives — the V-908 HTTPS-transport (`HTTPSDocumentTransport`) and
the V-908 §3.4 DNS-anchor pattern — extended in shape from the FTD
document to the AIP document. The module is
`wirelang.identity.aip_document_transport_fetch`; it does NOT mutate
the schema-registry backend, does NOT add a method to
`NatsKvSchemaRegistry`, and does NOT introduce a new envelope.

**Module location and rationale:**

The fetcher lives in `wirelang.identity` alongside the kid-resolver
(§5.9), `aip_document.py`, `aip_signing.py`, and the V-908 transport
primitives (`aip_https_backend.py`, `dns_anchor.py`). This placement
keeps the AIP-document trust layer self-contained: the schema-
registry signing module (§5.8) sees only the resolved public key,
and the resolver (§5.9) sees only the parsed AIP-document body. The
transport step is upstream of both and is the natural concern of the
Identity-Substrate module.

**Public API:**

```python
@dataclass(frozen=True)
class AipFetchResult:
    aip_id: str                  # input identifier (aip:web: or https://)
    url: str                     # canonical HTTPS URL fetched
    host: str                    # lower-cased host (for the DNS-anchor lookup)
    aip_doc: dict                # parsed JSON body, ready for resolve_kid
    body_bytes: bytes            # raw HTTPS response bytes (for re-canonicalisation)
    jcs_sha256_hex: str          # SHA-256(JCS(body without document_signature))
    dns_anchor: Optional[DnsAnchor]
    anchor_matched: bool

def aip_web_to_https_url(aip_id: str) -> tuple[str, str]: ...

def fetch_aip_document(
    aip_id: str,
    *,
    transport: HTTPSDocumentTransport,
    dns_resolver: Optional[TxtResolver] = None,
    anchor_required: bool = False,
    dns_timeout_s: float = 3.0,
) -> AipFetchResult: ...

class AipDocumentTransportError(Exception): ...
class AipUrlSchemeError(AipDocumentTransportError): ...
class AipDnsAnchorMismatchError(AipDocumentTransportError): ...

WELL_KNOWN_AIP_PREFIX: str = "/.well-known/aip/"
DNS_ANCHOR_PREFIX: str = "_wakir-aip."
```

**URL mapping rules:**

| Input | Output URL | Output host |
|---|---|---|
| `aip:web:host/persona-path` | `https://host/.well-known/aip/persona-path.json` | `host` (lower-cased) |
| `aip:web:host` (no path) | `https://host/.well-known/aip/index.json` | `host` (lower-cased) |
| `aip:web:host/foo.json` | `https://host/.well-known/aip/foo.json` (trailing `.json` is stripped from path then added back so the canonical form is single-source) | `host` (lower-cased) |
| `https://host/...` (pre-resolved) | unchanged | `host` parsed from URL |
| `http://...` | (raises `AipUrlSchemeError`) | — |
| empty / malformed | (raises `AipUrlSchemeError`) | — |

The `aip:web:` shape is the Wakir Phase-2 convention paralleling the
W3C `did:web:` shape; the canonical resolution under the `.well-known`
namespace (RFC 8615) keeps AIP documents portable across any web host
without a custom registry.

**Transport delegation:**

HTTPS fetch is delegated wholesale to the Phase-1b V-908
`HTTPSDocumentTransport` (Tag-8 PS-6 module). The Tag-4 layer:

- Adds no transport invariants on top of the V-908 §3.3 set
  (HTTPS-only, TLS 1.2+, max redirect = 0, body size cap, JSON
  Content-Type, parseable JSON object root). The V-908 transport
  enforces them.
- Does NOT wrap V-908 transport-level exceptions. `HTTPSStatusError`
  (with `.status == 404` etc.), `HTTPSSchemeError`,
  `HTTPSTransportError`, `HTTPSBodySizeError`, `HTTPSPayloadError`,
  `HTTPSRedirectError`, `HTTPSDocumentNotModified`, and the base
  `HTTPSBackendError` propagate verbatim. Callers retain typed
  access to the V-908 §3.3 invariants and can implement
  cache-revalidation strategies (`If-None-Match`) without going
  through the Tag-4 surface.

The result is that Tag-4 is byte-thin over the existing transport:
no double-parsing, no transport-error-renaming, no JSON re-decode.

**DNS-anchor cross-check (Wakir-AIP variant of V-908 §3.4):**

The optional `dns_resolver` parameter enables an out-of-band TXT-record
lookup at `_wakir-aip.<host>` (prefix `DNS_ANCHOR_PREFIX`). The
TXT-record format is byte-identical to the V-908 §3.4 FTD-document
anchor:

```
v=1; sha256=<64-hex>
```

Parsing reuses `wirelang.identity.dns_anchor.parse_anchor` verbatim.
Only the prefix differs between the AIP variant (`_wakir-aip`) and the
FTD variant (`_wakir-ftd`) — same trust model, same on-wire shape.

The local fingerprint is computed as
`SHA-256(JCS(body without document_signature))` using the resolver-
indirected `_jcs_canonicalize` from `wirelang.identity.aip_signing`
(the same canonicaliser the AIP-document signing path uses; the
`document_signature` slot is removed from a deep-copy so the caller's
body is not mutated).

**Hard-vs-soft toggle (`anchor_required`):**

| `anchor_required` | DNS TXT outcome | Result |
|---|---|---|
| `False` (default) | matches local JCS-anchor | `dns_anchor` set, `anchor_matched=True` |
| `False` (default) | missing / malformed | `dns_anchor=None`, `anchor_matched=False`, no raise |
| `False` (default) | mismatches | `dns_anchor` set, `anchor_matched=False`, no raise |
| `False` (default) | no resolver supplied | `dns_anchor=None`, `anchor_matched=False`, no raise |
| `True` | matches local JCS-anchor | `dns_anchor` set, `anchor_matched=True` |
| `True` | missing / malformed | **`AipDnsAnchorMismatchError`** (with `expected` set, `observed=None`) |
| `True` | mismatches | **`AipDnsAnchorMismatchError`** (with `expected` + `observed` set) |
| `True` | no resolver supplied | **`AipDnsAnchorMismatchError`** ("dns_resolver is None") — eager raise contract |

The `anchor_required` toggle is **orthogonal to** the Sprint-4 Tag-1
`VerifyMode.STRICT` signature-policy toggle (Z-1-K-Sprint-4-4) — it
governs the transport-trust step, not the signature-verification step.
A production deployment composes both:

- `VerifyMode.STRICT` for signature presence + cryptographic validity
  on the schema-registry envelope.
- `anchor_required=True` for DNS-anchored AIP-document trust.

**Determinism contract (Phase-2 Sprint-4 Tag-4 invariants):**

1. **Pure composition**: `fetch_aip_document` does not cache; it does
   not mutate the transport or the resolver; the result dataclass is
   frozen. Production callers compose with the existing V-908
   `HTTPSAipResolverCache` or a separate caching tier if memoisation
   is required.
2. **Reproducible URL mapping**: `aip_web_to_https_url` is byte-
   deterministic on its input. Repeated calls with the same `aip_id`
   produce equal `(url, host)` tuples.
3. **Reproducible byte-anchor**: `result.jcs_sha256_hex` is byte-equal
   across repeated fetches of the same body (the JCS canonicaliser
   is deterministic; the SHA-256 digest is deterministic).
4. **Structural-vs-network split**: structural failures (URL scheme,
   anchor mismatch in hard mode) raise the typed `AipDocument*`
   errors; network-level failures propagate as V-908
   `HTTPSBackendError` subclasses unchanged. Callers can branch on
   exception type without parsing messages.

**Phase-2 Sprint-4 Tag-4 boundary:**

The transport-fetch layer deliberately does NOT:

- Validate the AIP document's `document_signature` slot. Establishing
  AIP-document signing-trust is the caller's responsibility — see
  `wirelang.identity.verify_aip_signature`. The fetch layer returns
  the parsed body unchanged and lets the caller drive signature-check.
- Validate the AIP document against the JSON Schema
  (`wirelang/schemas/aip-document.json`). Schema-validation lives in
  Phase-1a `aip_resolver`; Tag-4 is shape-agnostic.
- Mutate the schema-registry backend surface. `NatsKvSchemaRegistry`
  is unchanged; no new method, no new envelope.
- Cache the result. Tag-4 is a stateless pure composition. The V-908
  `HTTPSAipResolverCache` exists in the HTTPS backend for the
  federation pipeline; production callers compose with the cache or
  layer their own tier on top.
- Bind the resolved `aip_id` to a schema-registry capability
  envelope (`registered_by` gating remains a future Phase-2 slot).

**Cross-Review-Zone-1 (Identity-Substrate) — non-touched:**

- **Z-1-K-Sprint-4-1 (kid-Resolver-Shape)** non-touched; Sprint-4
  Tag-3 closed it. Tag-4 feeds the resolver, does not modify it.
- **Z-1-K-Sprint-4-2 (JCS-Resolver-Lock)** non-touched; this module
  consumes `aip_signing._jcs_canonicalize` byte-identical via a
  lazy import. No new JCS path introduced.
- **Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519)** non-touched;
  transport-fetch is curve-agnostic (it fetches a document, not a
  key).
- **Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-Owner)** non-touched;
  `anchor_required` is a Tag-4-local hard-vs-soft toggle and is
  semantically independent of the schema-registry signing STRICT
  toggle.

**Composition pattern (canonical end-to-end Phase-2 verifier flow):**

```python
from wirelang.identity import (
    fetch_aip_document,
    resolve_kid,
)
from wirelang.identity.aip_https_backend import HTTPSDocumentTransport
from wirelang.identity.dns_anchor import StdlibDoHResolver
from wirelang.schemas.entry_signing import verify_entry_signature, VerifyMode

# 1. Fetch and (optionally) DNS-anchor-cross-check the AIP document.
transport = HTTPSDocumentTransport()
dns = StdlibDoHResolver()
fetched = fetch_aip_document(
    "aip:web:wakir.dev/personas/treasury-issuer",
    transport=transport,
    dns_resolver=dns,
    anchor_required=True,        # hard-trust path
)

# 2. Resolve the signing kid to an Ed25519 public key.
resolved = resolve_kid(
    fetched.aip_doc,
    signed.signature["kid"],
    as_of=now_utc(),
    require_purpose="aip-signing",
)

# 3. Verify the schema-registry-entry signature end-to-end.
ok = verify_entry_signature(
    signed, resolved.public_key, mode=VerifyMode.STRICT,
)
```

Sprint-4 Tag-4 test `T-AIP-FT-11` exercises steps 1-2 against the
RFC-8032 Ed25519 test-vector seeds; the resolver feed-through to
`verify_entry_signature` is covered by Sprint-4 Tag-3 test
`T-KID-RES-03`. The two tests together pin the end-to-end Phase-2
verifier pattern.

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

### 6.3 Publisher CLI tests (Tag-5, additive over Tag-4)

Phase-1b Sprint-3 Tag-5 ships hermetic publisher-CLI tests at
`wirelang/tests/test_schema_registry_publisher_cli.py`. Inventory
T-SR-PUB-01..12:

- **T-SR-PUB-01:** parser shape — `publish` and `dry-run` are both
  registered subcommands; required flags missing → exit 2; the
  `--create-only` / `--expected-revision` mutual-exclusion is
  enforced at the argparse layer.
- **T-SR-PUB-02:** `dry-run` happy path — receipt JSON has the stable
  schema; `mode` is "dry-run"; `key` is `schemas/<layer>/<name>/<version>`;
  `schema_body_sha256` matches a fresh `schema_body_sha256` over the
  body; `revision` is `null`; stderr is empty.
- **T-SR-PUB-03:** `publish` (LWW) — no CAS flags; the bucket gains
  exactly one entry; receipt `mode` is "lww"; `revision >= 1`;
  `expected_revision` is `null`; stderr is empty.
- **T-SR-PUB-04:** `publish --expected-revision N` (CAS-pin) — the
  supplied `N` matches live revision; CAS publish succeeds; receipt
  `mode` is "cas"; `expected_revision` echoes `N`; the new
  `revision` is exactly `N + 1`.
- **T-SR-PUB-05:** `publish --expected-revision N` (CAS-pin conflict)
  — `N` is stale; exit 5 (CAS_CONFLICT); error envelope on stderr;
  bucket state is byte-equal to the pre-call snapshot (no mutation
  on a failed CAS).
- **T-SR-PUB-06:** `publish --create-only` (success) — entry absent;
  bucket gains revision 1; receipt `mode` is "create-only";
  `expected_revision` is `0`; `revision` is `1`.
- **T-SR-PUB-07:** `publish --create-only` (conflict) — entry already
  present; exit 5; error envelope on stderr; bucket revision NOT
  advanced past the seed.
- **T-SR-PUB-08:** input error — `--schema-body` path does not exist;
  exit 3 (INPUT_ERROR); error envelope on stderr; bucket untouched.
- **T-SR-PUB-09:** input error — `--schema-body` is not valid JSON;
  exit 3; error envelope mentions the JSON parse failure; bucket
  untouched.
- **T-SR-PUB-10:** validation error — `schema_body` has no `$id`
  field; CLI gate raises `SchemaRegistryValidationError`; exit 4
  (VALIDATION_ERROR); bucket untouched.
- **T-SR-PUB-11:** validation error — `--registered-by` is whitespace-
  only; CLI gate raises `SchemaRegistryValidationError`; exit 4;
  bucket untouched.
- **T-SR-PUB-12:** stdout / stderr separation — on success, stdout
  carries exactly one line of valid JSON and stderr is empty; on
  failure, stderr carries exactly one line of valid JSON and stdout
  is empty.

Total Tag-5 test additions: 12 hermetic determinism tests
(T-SR-PUB-01..12). The CLI's `_default_connect_factory` is NOT
exercised at the test layer (it would require a live NATS cluster);
production operators verify it manually against their local cluster.

### 6.4 Replication tests (Tag-6, additive over Tag-5)

Phase-1b Sprint-3 Tag-6 ships hermetic replication tests at
`wirelang/tests/test_schema_registry_replication.py`. Inventory
T-SR-REP-01..12:

- **T-SR-REP-01:** bootstrap copies every source entry onto an empty
  target in keys-sorted order; `bootstrap_applied` advances by the
  number of source entries; the target's keyset is byte-equal to
  the source's keyset post-bootstrap.
- **T-SR-REP-02:** a second bootstrap pass on a byte-equal target
  is a no-op via the `bootstrap_skipped_idempotent` counter
  (idempotency contract; the second-pass `bootstrap_applied` is 0
  because the new metrics object starts fresh).
- **T-SR-REP-03:** a `ReplicationFilter` skips entries that do not
  match a layer constraint during the bootstrap pass; the
  filtered-out entry is NOT written to the target;
  `bootstrap_skipped_by_filter` advances.
- **T-SR-REP-04:** live PUT events on the source land on the target
  via the watch-stream tail; `events_applied_put` advances per event.
- **T-SR-REP-05:** a live DELETE on the source removes the entry
  from the target via the watch-stream tail; `events_applied_delete`
  advances.
- **T-SR-REP-06:** under `ReplicationConflictPolicy.CAS_PIN`, a
  target-side mutation that lands between the replicator's
  read-revision and CAS-pinned-write surfaces as a CAS conflict
  on the underlying backend; the replicator catches it, increments
  `cas_conflicts`, and continues with subsequent events. The
  replicator does NOT overwrite the target's out-of-band state.
- **T-SR-REP-07:** `halt_on_conflict=True` re-raises
  `SchemaRegistryConflictError` on the first CAS conflict;
  `cas_conflicts` is incremented before re-raise.
- **T-SR-REP-08:** a poisoned envelope on the source watch-stream
  (non-JSON `value` on a PUT update) halts `run` with
  `SchemaRegistryEnvelopeError`; `envelope_errors` is 1.
- **T-SR-REP-09:** a `ReplicationFilter` that returns `SKIP` on a
  live PUT event prevents the event from reaching the target;
  `events_skipped_by_filter` advances.
- **T-SR-REP-10:** the `SchemaReplicator` constructor rejects
  source==target with `ValueError` (no self-replication contract).
- **T-SR-REP-11:** a malformed PUT `WatchEvent` arriving with
  `entry=None` (handcrafted, bypassing the decoder) is rejected at
  the replicator's apply boundary as
  `SchemaRegistryEnvelopeError` (defence-in-depth).
- **T-SR-REP-12:** `run(bootstrap=False)` skips the bootstrap pass;
  the pre-existing source entry is NOT pre-loaded onto the target,
  but the live tail events still land. Bootstrap counters stay 0
  while live counters advance.

Total Tag-6 test additions: 12 hermetic determinism tests
(T-SR-REP-01..12). The replication module does NOT establish NATS
connections itself; tests inject the same in-memory `_MockKv` shape
used by Tag-3 / Tag-4 / Tag-5, with a wrapper that simulates the
read-then-mutate race window for the CAS-conflict path.

### 6.5 Entry-signing tests (Phase-2 Sprint-4 Tag-1, additive over Tag-6)

Phase-2 Sprint-4 Tag-1 ships hermetic entry-signing tests at
`wirelang/tests/test_schema_registry_entry_signing.py`. Inventory
T-SR-SIG-01..12:

- **T-SR-SIG-01:** `sign_entry` → `verify_entry_signature` round-trip
  on a freshly-generated Ed25519 key-pair returns `True`. The
  returned `SignedSchemaRegistryEntry` carries the original entry
  byte-equal (`entry == returned.entry`).
- **T-SR-SIG-02:** signing is deterministic over the JCS canonical
  form: two `SchemaRegistryEntry` instances with byte-equal envelopes
  produce identical pre-image SHA-256 digests. (Ed25519 itself is
  deterministic per RFC 8032; equality of the digest is the
  necessary-and-sufficient invariant.)
- **T-SR-SIG-03:** the signature block is structurally fixed:
  `{alg: "Ed25519", kid: <given>, signature: <128-hex>}`. Any
  deviation (missing field, wrong alg, malformed hex, wrong length)
  raises `SchemaRegistrySignatureError` from
  `verify_entry_signature`.
- **T-SR-SIG-04:** tamper detection — mutating any envelope field
  on a signed entry (layer / name / version / schema_id /
  schema_body / schema_body_sha256 / registered_at /
  registered_by / supersedes) and re-running `verify_entry_signature`
  with the same signature block returns `False`.
- **T-SR-SIG-05:** self-reference exclusion — modifying the
  `signature` field of the envelope does NOT change the signing
  pre-image. The signature slot is stripped before JCS
  canonicalisation.
- **T-SR-SIG-06:** `envelope_with_signature` emits the envelope
  bytes that round-trip through `envelope_to_signed_entry` to a
  byte-equal `SignedSchemaRegistryEntry`. The optional `signature`
  slot is the only difference versus the Tag-1 codec.
- **T-SR-SIG-07:** backward compatibility — a v0.5.0-style envelope
  WITHOUT a `signature` slot round-trips through
  `envelope_to_signed_entry` and returns a plain
  `SchemaRegistryEntry` (parity with the Tag-1 codec).
- **T-SR-SIG-08:** `PERMISSIVE` mode — an unsigned envelope (no
  `signature` slot) verifies as `True` via
  `verify_entry_signature(entry, mode=PERMISSIVE)`. A signed envelope
  is verified end-to-end.
- **T-SR-SIG-09:** `STRICT` mode — an unsigned envelope raises
  `SchemaRegistrySignatureError` with a missing-signature message
  via `verify_entry_signature(entry, mode=STRICT)`.
- **T-SR-SIG-10:** wrong public key — `verify_entry_signature` with
  a different Ed25519 public key on a validly-signed entry returns
  `False` (cryptographic failure, not structural).
- **T-SR-SIG-11:** wrong key length — supplying a non-32-byte
  public key or non-32-byte private key raises a
  `SchemaRegistrySignatureError` (structural).
- **T-SR-SIG-12:** Tag-1 codec parity — a signed envelope emitted by
  `envelope_with_signature` is byte-equal to the corresponding
  unsigned Tag-1 envelope EXCEPT for the one optional `signature`
  slot. Stripping the slot from the signed envelope and re-decoding
  through the Tag-1 codec recovers the original entry byte-equal
  (the Tag-1 codec is unchanged in Sprint-4 Tag-1).

Total Phase-2 Sprint-4 Tag-1 test additions: 12 hermetic determinism
tests (T-SR-SIG-01..12). The signing layer is pure: no NATS
connections, no I/O. Tests use `cryptography.hazmat.primitives.
asymmetric.ed25519` to generate ephemeral key-pairs from
deterministic 32-byte seeds and known-answer Ed25519 vectors where
applicable.

### 6.6 kid-resolver tests (Phase-2 Sprint-4 Tag-3, additive over Sprint-4 Tag-1)

Phase-2 Sprint-4 Tag-3 ships hermetic resolver tests at
`wirelang/tests/test_identity_kid_resolver.py`. Inventory
T-KID-RES-01..12:

- **T-KID-RES-01** — happy-path resolve through the wired
  `generate_aip_document` factory. Pins that the resolver agrees with
  the byte-shape the generator emits: `kid="biscuit-root-1"`,
  `alg="Ed25519"`, `purpose="biscuit-root"`, validity-window parsed.
- **T-KID-RES-02** — multi-key resolve. Two distinct kids in
  `public_keys` (`biscuit-root-1` + `aip-signing-1`), both Ed25519,
  resolve independently to the right key.
- **T-KID-RES-03** — cross-layer end-to-end. Sign a
  `SchemaRegistryEntry` with `entry_signing.sign_entry`; resolve the
  kid via `resolve_kid`; feed the resolved public key into
  `verify_entry_signature(..., mode=VerifyMode.STRICT)`. Pins that
  the composition pattern (§5.9) verifies under STRICT. Negative
  branch: a wrong-key resolve returns `False` from verify (crypto
  failure, not structural).
- **T-KID-RES-04** — kid-not-found structural failure. A kid absent
  from `public_keys` raises `KidResolverError` with a
  `"kid not found"` message; the error message includes the list of
  candidate kids.
- **T-KID-RES-05** — duplicate-kid structural failure. Two
  `public_keys` entries with the same `kid` raise `KidResolverError`
  with a `"duplicate kid"` message; the resolver refuses to silently
  pick a winner.
- **T-KID-RES-06** — wrong-alg filter. A `secp256k1` entry on the
  requested kid raises `KidResolverError` (`"alg is not 'Ed25519'"`).
  Reinforces Z-1-K-Sprint-4-3: secp256k1 entries are invisible to
  the Identity-Document signing-layer resolver.
- **T-KID-RES-07** — validity-window enforcement. Three sub-cases
  with the same `validafter`/`validuntil` window: `as_of` before
  window raises `"not yet valid"`; inside window resolves
  successfully; after window raises `"has expired"`. A fourth probe
  confirms that no `as_of` argument disables the window check
  (historical-signature use-case).
- **T-KID-RES-08** — purpose-filter enforcement. `require_purpose`
  matching the entry passes; mismatched purpose raises
  `"purpose mismatch"`.
- **T-KID-RES-09** — malformed `key_hex` structural failures
  (three sub-cases): wrong hex-string length (62 chars); correct
  length but non-hex characters; missing `key_hex` field entirely.
  All three raise `KidResolverError`.
- **T-KID-RES-10** — missing/malformed `public_keys` array (five
  sub-cases): missing field; non-sequence (dict); a string in place
  of the sequence (Python sees strings as sequences — the resolver
  excludes `str`/`bytes` explicitly); empty array; non-mapping
  `aip_doc` argument; plus an empty-kid argument probe.
- **T-KID-RES-11** — `list_resolvable_kids` filter behaviour.
  Asserts: no filters lists both kids in sorted order; window filter
  excludes the expired key; purpose filter narrows to one kid;
  wrong-alg entries are dropped; duplicate kids cause both copies
  to be dropped (returns empty list when both kids of a 2-entry
  document collide).
- **T-KID-RES-12** — determinism. Repeated `resolve_kid` calls on
  the same input produce equal `ResolvedPublicKey` instances
  (frozen-dataclass equality); a JSON round-trip on the AIP document
  does not affect the result; `list_resolvable_kids` is also
  order-deterministic.

Total Phase-2 Sprint-4 Tag-3 test additions: 12 hermetic determinism
tests (T-KID-RES-01..12). The resolver is pure: no transport,
no signature verification on the AIP document, no I/O. Tests use
RFC 8032 Ed25519 test-vector seeds and hand-crafted minimal AIP-
document fragments.

**Suite-level effect (post-Sprint-4 Tag-3):** the wirelang test
suite grows from 671 passed (post-Sprint-4 Tag-1) to **683 passed**
(+12 net). The Tag-1 entry-signing tests (T-SR-SIG-01..12) remain
unchanged and green.

### 6.7 AIP-document transport-fetch tests (Phase-2 Sprint-4 Tag-4, additive over Sprint-4 Tag-3)

Phase-2 Sprint-4 Tag-4 ships hermetic transport-fetch tests at
`wirelang/tests/test_aip_document_transport_fetch.py`. Inventory
T-AIP-FT-01..12. All tests are hermetic: a fake `urlopen` is injected
into `HTTPSDocumentTransport` and a stub `TxtResolver` is supplied
for the DNS-anchor path. No real HTTPS calls and no real DNS queries
leave the process.

- **T-AIP-FT-01** — `aip_web_to_https_url` canonical mappings. Four
  sub-cases: `aip:web:host/persona-path` → canonical URL; no-path
  `aip:web:host` → `index.json` under `.well-known/aip/`; trailing
  `.json` on persona-path is stripped (single-source canonical form);
  pre-resolved `https://...` URL passes through verbatim.
- **T-AIP-FT-02** — URL-scheme structural failures. Six sub-cases:
  empty string; bare `aip:web:`; `aip:web:` with empty-host; `did:web:`
  (wrong scheme); plaintext `http://` (rejected with a V-908 §3.3
  message); bare `https://`. All six raise `AipUrlSchemeError`.
- **T-AIP-FT-03** — happy-path HTTPS fetch without DNS-anchor.
  `fetch_aip_document` returns an `AipFetchResult` with correct
  `aip_id`/`url`/`host`/`aip_doc`/`body_bytes`/`jcs_sha256_hex` and
  `dns_anchor=None`, `anchor_matched=False`. Exactly one HTTPS call
  at the mapped URL.
- **T-AIP-FT-04** — V-908 transport error propagation. A `404` from
  the fake `urlopen` surfaces as `HTTPSStatusError` (V-908 §3.3
  invariant), not as an `AipDocumentTransportError`; the typed
  `.status == 404` access is preserved (no wrapping).
- **T-AIP-FT-05** — non-object root body. A JSON array (`[1,2,3]`)
  as the body raises `HTTPSPayloadError` (the V-908 transport
  enforces "JSON object root"; the Tag-4 defensive guard is dead
  code in the production wire and is pinned to the transport here).
- **T-AIP-FT-06** — DNS-anchor soft-match. `anchor_required=False`
  with a matching TXT record (`v=1; sha256=<fp>` where `fp` equals
  the local JCS-anchor hex) → `anchor_matched=True`, `dns_anchor`
  populated, exactly one DNS resolver call at `_wakir-aip.<host>`
  with the configured timeout.
- **T-AIP-FT-07** — DNS-anchor soft-absent. `anchor_required=False`
  with no TXT record at the anchor host → no raise; `dns_anchor=None`,
  `anchor_matched=False`. The soft mode swallows the underlying
  `DnsAnchorError`.
- **T-AIP-FT-08** — DNS-anchor hard-mismatch. `anchor_required=True`
  with a TXT record whose fingerprint disagrees with the local
  JCS-anchor hex → `AipDnsAnchorMismatchError` with `expected` set
  to the local hex and `observed` set to the wire hex; `host` and
  `aip_id` carried on the exception.
- **T-AIP-FT-09** — DNS-anchor hard-absent. `anchor_required=True`
  with no TXT record at the anchor host → `AipDnsAnchorMismatchError`
  with a `"lookup failed"` message; the underlying `DnsAnchorError`
  is chained via `__cause__`.
- **T-AIP-FT-10** — eager-raise on missing resolver.
  `anchor_required=True` with `dns_resolver=None` → `AipDnsAnchorMismatchError`
  with `"dns_resolver is None"`. The HTTPS fetch still occurs (the
  eager raise happens post-fetch; the contract documents this).
- **T-AIP-FT-11** — cross-layer composition. End-to-end:
  `fetch_aip_document` → `resolve_kid`. The fetched body produces a
  `ResolvedPublicKey` whose `public_key` byte-equals the RFC-8032
  Ed25519 test-vector public key seeded into the AIP-doc fixture.
  Pairs with Sprint-4 Tag-3 `T-KID-RES-03` (the resolver →
  `verify_entry_signature` half) to pin the canonical Phase-2
  verifier flow.
- **T-AIP-FT-12** — determinism and pre-resolved-URL pass-through.
  Repeated `fetch_aip_document` calls with the same `aip_id` and
  byte-equal response produce byte-equal `(url, host, aip_doc,
  jcs_sha256_hex)`. The `https://...` pre-resolved shape produces
  the same `jcs_sha256_hex` as the `aip:web:` shape on the same body
  (URL passes through; host is parsed identically).

Total Phase-2 Sprint-4 Tag-4 test additions: 12 hermetic determinism
tests (T-AIP-FT-01..12). The fetcher is pure-composition: no signature
verification, no schema validation, no caching. Tests use a fake
`urlopen` script + a stub `TxtResolver` for end-to-end determinism;
RFC 8032 Ed25519 test-vector seeds are reused from the Sprint-4 Tag-3
kid-resolver tests for the cross-layer composition probe.

**Suite-level effect (post-Sprint-4 Tag-4):** the wirelang test
suite grows from **683 passed** (post-Sprint-4 Tag-3) to **695 passed**
(+12 net). The Tag-1 entry-signing tests (T-SR-SIG-01..12) and the
Tag-3 kid-resolver tests (T-KID-RES-01..12) remain unchanged and
green.

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
- **Phase-1c publisher CLI: OI-7-Phase-1c-publisher — CONSUMED in
  Tag-5.** Module: `wirelang/schemas/publisher_cli.py`. Tests:
  `wirelang/tests/test_schema_registry_publisher_cli.py`.
- **Phase-1c cross-bucket replication: OI-7-Phase-1c-replication
  — CONSUMED in Tag-6.** Module: `wirelang/schemas/replication.py`.
  Tests: `wirelang/tests/test_schema_registry_replication.py`.
- **Phase-1c is feature-complete; all four Phase-1c slots are
  consumed (Tag-3 / Tag-4 / Tag-5 / Tag-6).**
- **Phase-2 entry-signing: OI-7-Phase-2-sig — CONSUMED in Sprint-4
  Tag-1.** Module: `wirelang/schemas/entry_signing.py`. Tests:
  `wirelang/tests/test_schema_registry_entry_signing.py`. Signing
  primitive reuses `wirelang/identity/aip_signing.py` JCS+SHA-256+
  Ed25519 byte-identical (Cross-Review-Zone-1 Identity-Substrate
  touch).
- **Phase-2 kid → public-key resolver: CONSUMED in Sprint-4 Tag-3.**
  Module: `wirelang/identity/kid_resolver.py`. Tests:
  `wirelang/tests/test_identity_kid_resolver.py` (T-KID-RES-01..12).
  Closes Z-1-K-Sprint-4-1 (kid-Resolver-Shape) and reinforces
  Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519). The resolver is the
  Identity-Substrate consumer of Sprint-4 Tag-1 signature blocks:
  callers feed `resolved.public_key` into `verify_entry_signature`
  (§5.9 composition pattern).
- Phase-2 CAS-quorum: **OI-7-Phase-2-quorum** (reserved).
- Phase-2 deprecation policy: **OI-7-Phase-2-deprecation** (reserved).
- Phase-2 IPFS schema-hash: **OI-7-Phase-2-ipfs** (reserved).
- Phase-2 bidirectional replication: **OI-7-Phase-2-bidir-replication**
  (reserved; CRDT-style merge contract for two-way mirror).
- Phase-2 watch-stream resume: **OI-7-Phase-2-resume** (reserved;
  resume-from-revision policy on connection drop).
- **Phase-2 AIP-document transport-fetch: CONSUMED in Sprint-4
  Tag-4.** Module: `wirelang/identity/aip_document_transport_fetch.py`.
  Tests: `wirelang/tests/test_aip_document_transport_fetch.py`
  (T-AIP-FT-01..12). Closes the Sprint-4 Tag-3 §5.9 boundary item
  "AIP-document transport-fetch (`did:web` / `aip:web` HTTPS bridge)".
  The module composes the V-908 Phase-1b HTTPS-transport
  (`HTTPSDocumentTransport`) and the V-908 §3.4 DNS-anchor pattern
  (extended from FTD-doc to AIP-doc via the parallel TXT-record
  prefix `_wakir-aip.<host>`; same `v=1; sha256=<64-hex>` format).
  The fetch layer is byte-orthogonal to AIP-document signature
  verification (`wirelang.identity.verify_aip_signature` unchanged),
  the kid-resolver (Tag-3, §5.9), and the schema-registry backend
  (no method added to `NatsKvSchemaRegistry`). The Phase-2 canonical
  verifier flow is now end-to-end composable from an `aip:web:`
  identifier through to `verify_entry_signature` — see §5.10
  composition pattern.
- Phase-2 STRICT-mode activation toggle: reserved (Z-1-K-Sprint-4-4
  open; operator-controlled toggle is a Phase-2-roadmap consensus
  question).

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

**Tag-5 (v0.4.0) is additive relative to Tag-4 (v0.3.0):**

- All Tag-1 + Tag-3 + Tag-4 surfaces remain unchanged. Tag-5
  introduces no new method on `NatsKvSchemaRegistry`, no new field
  on `SchemaRegistryEntry`, and no new on-the-wire envelope.
- The Tag-5 addition is a *separate module*
  (`wirelang.schemas.publisher_cli`) consisting of an argparse
  surface, an `ExitCode` enum, a `PublishReceipt` dataclass, and a
  `run()` entry-point. Existing callers that consume the backend
  directly (verifier modules, watch-stream consumers) are untouched.
- M-2 conformance (additive-only schema evolution): Tag-5 adds no
  new envelope fields and modifies no existing field. The on-the-wire
  envelope schema remains `wakir.wirelang.schema-registry-entry/1`.
  The CLI is a routing layer onto the existing backend gates; it
  does not introduce an alternative codec.
- M-4 conformance (multi-version-aware registry): Tag-5 is orthogonal
  to the version axis. The CLI publishes one `(layer, name, version)`
  entry per invocation; multi-version coexistence on the bucket is
  unaffected.
- Spec semver bump 0.3.0 → 0.4.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive).

**Tag-6 (v0.5.0) is additive relative to Tag-5 (v0.4.0):**

- All Tag-1 + Tag-3 + Tag-4 + Tag-5 surfaces remain unchanged.
  Tag-6 introduces no new method on `NatsKvSchemaRegistry`, no new
  field on `SchemaRegistryEntry`, and no new on-the-wire envelope.
- The Tag-6 addition is a *separate module*
  (`wirelang.schemas.replication`) consisting of `SchemaReplicator`,
  `bootstrap_target_from_source`, `ReplicationConflictPolicy`,
  `ReplicationDecision`, `ReplicationFilter`, and
  `ReplicationMetrics`. The replication module is a *consumer* of
  Tag-1 LWW + Tag-3 CAS-pin + Tag-4 watch-stream surfaces; it
  imports them but does not modify them.
- Existing callers that consume the backend directly (verifier
  modules, watch-stream consumers, the publisher CLI) are untouched.
- M-2 conformance (additive-only schema evolution): Tag-6 adds no
  new envelope fields and modifies no existing field. The on-the-wire
  envelope schema remains `wakir.wirelang.schema-registry-entry/1`.
  The replicator transports the same envelope bytes across buckets;
  the encoder / decoder is shared (`_entry_to_envelope` /
  `_envelope_to_entry` from the Tag-1 backend).
- M-4 conformance (multi-version-aware registry): Tag-6 is orthogonal
  to the version axis. The replicator mirrors entries per bucket key
  (`schemas/<layer>/<name>/<version>`) without depending on whether
  multiple versions are simultaneously active on either bucket.
- Spec semver bump 0.4.0 → 0.5.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive).

**Phase-2 Sprint-4 Tag-1 (v0.6.0) is additive relative to Tag-6 (v0.5.0):**

- All Tag-1 + Tag-3 + Tag-4 + Tag-5 + Tag-6 surfaces remain
  unchanged. Sprint-4 Tag-1 introduces no new method on
  `NatsKvSchemaRegistry`.
- The Sprint-4 Tag-1 addition is a *separate module*
  (`wirelang.schemas.entry_signing`) consisting of
  `SignedSchemaRegistryEntry`, `sign_entry`,
  `verify_entry_signature`, `envelope_with_signature`,
  `envelope_to_signed_entry`, `SchemaRegistrySignatureError`, and
  `VerifyMode`. The signing module is a *consumer* of the Tag-1
  envelope codec (`_entry_to_envelope` / `_envelope_to_entry`)
  and of `wirelang.identity.aip_signing`'s JCS+SHA-256+Ed25519
  primitive; it imports them but does not modify them.
- The Tag-1 envelope codec (`_entry_to_envelope` /
  `_envelope_to_entry`) is left UNCHANGED in Sprint-4 Tag-1. The
  new `envelope_with_signature` / `envelope_to_signed_entry`
  helpers in `wirelang.schemas.entry_signing` provide the
  envelope-with-signature round-trip. Unsigned envelopes emitted by
  the Tag-1 codec remain byte-equal to v0.5.0 output (backward
  compatibility invariant); signed envelopes emitted by
  `envelope_with_signature` differ from the Tag-1 output by exactly
  the one optional `signature` slot.
- M-2 conformance (additive-only schema evolution): Sprint-4 Tag-1
  adds ONE optional field (`signature`) to the existing
  `wakir.wirelang.schema-registry-entry/1` envelope; no field is
  modified or removed. v0.5.0 readers tolerate the new optional
  field. The on-the-wire envelope schema URI is unchanged (no `/2`
  envelope is introduced).
- M-4 conformance (multi-version-aware registry): Sprint-4 Tag-1
  is orthogonal to the version axis. Signing operates on one entry
  envelope (`schemas/<layer>/<name>/<version>`) and is independent
  of whether multiple versions are simultaneously active.
- The synchronous verifier surface (`InMemorySchemaRegistry.lookup`
  / `lookup_by_triple` / `keys_sorted`) is unchanged. Verifier
  modules that consume frozen `InMemorySchemaRegistry` views are
  not forced onto the signing path; signing is opt-in at the
  envelope-build boundary.
- Spec semver bump 0.5.0 → 0.6.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive).

**Phase-2 Sprint-4 Tag-3 (v0.7.0) is additive relative to Sprint-4 Tag-1 (v0.6.0):**

- All Tag-1 + Tag-3 + Tag-4 + Tag-5 + Tag-6 + Sprint-4 Tag-1 surfaces
  remain unchanged. Sprint-4 Tag-3 introduces no new method on
  `NatsKvSchemaRegistry` and no modification to
  `wirelang.schemas.entry_signing`.
- The Sprint-4 Tag-3 addition is a *separate module*
  (`wirelang.identity.kid_resolver`) consisting of the pure
  functions `resolve_kid` / `list_resolvable_kids`, the frozen
  dataclass `ResolvedPublicKey`, and the typed exception
  `KidResolverError`. The resolver is exposed via the
  `wirelang.identity` package `__init__`.
- The on-the-wire envelope schema is UNCHANGED. The resolver reads
  from AIP documents (`wirelang/schemas/aip-document.json`); it
  does not emit, write, or canonicalise envelope bytes.
- The `wirelang.schemas.entry_signing` module is UNCHANGED. The
  resolver is a *peer* layer — callers compose the two: read AIP
  doc → `resolve_kid` → `verify_entry_signature`. The signing
  module does NOT import the resolver; this preserves the Sprint-4
  Tag-1 design that the signing module treats the public key as
  caller-supplied.
- M-2 conformance (additive-only schema evolution): Sprint-4 Tag-3
  adds NO new envelope field. The schema-registry on-the-wire
  surface (envelope shape, value-schema URI
  `wakir.wirelang.schema-registry-entry/1`, signature-block shape)
  is bit-equal to v0.6.0. M-2 is preserved trivially.
- M-4 conformance (multi-version-aware registry): Sprint-4 Tag-3
  is orthogonal to the version axis. The resolver operates on
  AIP documents (one per agent identity), not on registry entries.
- The AIP-document JSON-Schema
  (`wirelang/schemas/aip-document.json`) is UNCHANGED. The resolver
  reads existing fields (`kid`, `alg`, `key_hex`, `validafter`,
  `validuntil`, `purpose`); no new field is introduced and no
  field semantics is altered.
- The synchronous verifier surface (`InMemorySchemaRegistry.lookup`
  / `lookup_by_triple` / `keys_sorted`) is unchanged. The kid-
  resolver is opt-in: verifiers that do not consume signatures are
  not forced onto the resolver path.
- Spec semver bump 0.6.0 → 0.7.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive). The bump is
  warranted by the new §5.9 operational contract and §6.6 test
  inventory; no breaking-change to any consumer.

**Phase-2 Sprint-4 Tag-4 (v0.8.0) is additive relative to Sprint-4 Tag-3 (v0.7.0):**

- All Tag-1 + Tag-3 + Tag-4 + Tag-5 + Tag-6 + Sprint-4 Tag-1 +
  Sprint-4 Tag-3 surfaces remain unchanged. Sprint-4 Tag-4 introduces
  no new method on `NatsKvSchemaRegistry`, no modification to
  `wirelang.schemas.entry_signing`, and no modification to
  `wirelang.identity.kid_resolver` (the Sprint-4 Tag-3 surface).
- The Sprint-4 Tag-4 addition is a *separate module*
  (`wirelang.identity.aip_document_transport_fetch`) consisting of
  the pure function `fetch_aip_document`, the URL-mapping helper
  `aip_web_to_https_url`, the frozen dataclass `AipFetchResult`, the
  typed exception tree `AipDocumentTransportError` →
  {`AipUrlSchemeError`, `AipDnsAnchorMismatchError`}, and the
  module-level constants `WELL_KNOWN_AIP_PREFIX` /
  `DNS_ANCHOR_PREFIX`. The fetcher is exposed via the
  `wirelang.identity` package `__init__`.
- The on-the-wire envelope schema is UNCHANGED. The fetcher reads
  AIP documents from HTTPS; it does not emit, write, or canonicalise
  schema-registry envelope bytes.
- `wirelang.schemas.entry_signing` is UNCHANGED. `wirelang.identity.kid_resolver`
  is UNCHANGED. `wirelang.identity.aip_signing` is UNCHANGED. The
  fetcher consumes `wirelang.identity.aip_signing._jcs_canonicalize`
  via a lazy import (the canonicaliser is shared byte-identical with
  the signing path; no new JCS path introduced).
- The V-908 HTTPS-transport surface (`HTTPSDocumentTransport` and
  its exception tree `HTTPSBackendError` + subclasses) is UNCHANGED.
  The fetcher composes the existing transport without wrapping or
  re-parsing.
- The V-908 DNS-anchor surface (`dns_anchor.TxtResolver`,
  `dns_anchor.fetch_anchor`, `dns_anchor.parse_anchor`,
  `DnsAnchor`, `DnsAnchorError`) is UNCHANGED. The Wakir-AIP TXT-
  record prefix (`_wakir-aip.`) is a parallel slot to the Wakir-FTD
  prefix (`_wakir-ftd.`); the on-wire format is byte-identical
  (`v=1; sha256=<64-hex>`); the parser is reused verbatim.
- M-2 conformance (additive-only schema evolution): Sprint-4 Tag-4
  adds NO new envelope field. The schema-registry on-the-wire surface
  (envelope shape, value-schema URI
  `wakir.wirelang.schema-registry-entry/1`, signature-block shape)
  is bit-equal to v0.7.0. M-2 is preserved trivially.
- M-4 conformance (multi-version-aware registry): Sprint-4 Tag-4
  is orthogonal to the version axis. The fetcher operates on AIP
  documents (one per agent identity), not on registry entries.
- The AIP-document JSON-Schema (`wirelang/schemas/aip-document.json`)
  is UNCHANGED. The fetcher reads the body opaquely and does not
  validate it against the schema (schema-validation belongs to
  Phase-1a `aip_resolver`).
- Cross-Review-Zone-1 (Identity-Substrate) non-touched: the four
  Z-1-K-Sprint-4 consensus points remain byte-identical. The Tag-4
  `anchor_required` toggle is an *orthogonal* hard-vs-soft policy
  governing the transport-trust step; it is semantically distinct
  from the Sprint-4 Tag-1 `VerifyMode.STRICT` signature-policy toggle
  (Z-1-K-Sprint-4-4).
- The synchronous verifier surface (`InMemorySchemaRegistry.lookup`
  / `lookup_by_triple` / `keys_sorted`) is unchanged. The transport-
  fetch layer is opt-in: verifiers that consume out-of-band AIP
  documents (e.g. from a sidecar cache) are not forced onto the
  fetcher path.
- Spec semver bump 0.7.0 → 0.8.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive). The bump is
  warranted by the new §5.10 operational contract and §6.7 test
  inventory; no breaking-change to any consumer.

## 9. Brand-Guide §9 sweep

This document has been swept against the Wakir Brand-Guide §9
(role-strings, no clear-name leakage in module / file / module-doc
content). The Sprint-4 Tag-1 additions (§5.8, §6.5, change-log
v0.6.0 entry, Phase-2 boundary updates) use role-strings only
(`Reza`, `Tomás`, `Mira`, `Aisha` appear in outbox documents and
optional cross-review memos, not in this spec; the spec mentions
only `wakir.*` URIs and module-path references).

The Sprint-4 Tag-3 additions (§5.9, §6.6, change-log v0.7.0 entry,
§1.2 Phase-2 Sprint-4 Tag-3 block, §7 cross-references update, §8
compatibility statement update) have been swept identically — only
role-strings, module-path references, `wakir.*` URIs, and IETF /
RFC references appear in the spec body. No external-tool clear-name
leakage and no internal-persona-clear-name leakage in the spec body.

The Sprint-4 Tag-4 additions (§5.10, §6.7, change-log v0.8.0 entry,
§1.2 Phase-2 Sprint-4 Tag-4 block, §5.3 lands-update,
§7 cross-references update — transport-fetch slot CONSUMED, §8
compatibility statement update for v0.7.0 → v0.8.0) have been swept
identically — only role-strings (none in this spec body), module-path
references (`wirelang.identity.aip_document_transport_fetch`,
`wirelang.identity.aip_https_backend`, `wirelang.identity.dns_anchor`),
`wakir.*` URIs (`_wakir-aip.`, `/.well-known/aip/`, `aip:web:`,
`wakir.wirelang.schema-registry-entry/1`), and IETF / RFC references
(RFC 8615 well-known namespace, RFC 8785 JCS, RFC 8032 Ed25519,
V-908 spec sections) appear in the spec body. No external-tool
clear-name leakage and no internal-persona-clear-name leakage in
the Tag-4 spec body additions.

— End of spec —
