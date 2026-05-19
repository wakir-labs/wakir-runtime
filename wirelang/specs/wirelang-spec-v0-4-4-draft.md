<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

---
spec: wirelang
version: 0.4.4-draft
status: post-cutover-reserve-draft
parent: wirelang-spec-v0-4-3
extends: 0.4.3
supersedes: null
replaces: null
replaced-by: null
date: 2026-05-19
audience: implementers, integrators, operators, auditors
license: CC-BY-4.0
freeze-marker: null
freeze-anchor: null
activation-trigger: kw-24-cutover-T0-post-promotion
activation-policy: sequence-promotion-only
---

# Wirelang Specification v0.4.4-draft (Tag-63 Post-Cutover-Reserve-Draft)

This document is a **post-cutover-reserve-draft** maintained as a
parallel-track file alongside the frozen
[`wirelang-spec-v0-4-3.md`](wirelang-spec-v0-4-3.md)
(`status: pre-cutover-freeze`). It is **not** an edit of v0.4.3 and
it is **not** a successor in the `replaced-by:` chain — yet. It
collects substance-side increments that are known to be wanted
**after** the KW-24 Phase-3c cutover gate fires (2026-06-08 through
2026-06-14), so that the cutover-day team is not forced to draft
new spec text under cutover-day pressure.

> **v0.4.4-draft (2026-05-19, Tag-63):** Reserve-substrate only.
> **No on-the-wire authority. No frame-attribute authority. No
> caveat-predicate authority. No operator-contract authority.**
> The document holds **candidate** increments that MAY be promoted
> to a full v0.4.4 (or v0.5) document *only after* the KW-24
> cutover gate has fired and a CEO-Triage-approved sequence-
> promotion step is executed. Until that promotion, v0.4.3
> (`pre-cutover-freeze`) remains the sole conformance anchor.
>
> Implementations MUST NOT key off `wirelangversion: 0.4.4-draft`.
> Verifiers MUST treat any frame carrying that string as a
> protocol error.

v0.4.4-draft exists as a **separate file** for the same two
discipline reasons that motivated the v0.4.0 → v0.4.1 → v0.4.2 →
v0.4.3 file-per-marker splits:

1. **Seal integrity.** The v0.4.3 freeze-seal (Tag-58 probe,
   `tooling/audit/verify_wirelang_spec_freeze_seal.py`) hashes
   `wirelang-spec-v0-4-3.md` byte-for-byte against
   `freeze-baseline.json`. Even an intra-section reorder of
   v0.4.3 would flip the seal verdict to `SEAL-BROKEN`.
   Reserve-draft work MUST therefore live in a separate file.
2. **Patch-trace integrity.** Tag-53 PR (v0.4.3) is the spec-side
   pre-cutover closure-bit cited by Tag-56 ADR-head errata,
   Tag-58 seal-probe, Tag-60 OTS pre-anchor probe, and the
   KW-24 cutover-gate acceptance criteria. Reserve-draft work
   MUST NOT contaminate that patch-trace.

## 1. Scope of v0.4.4-draft

The draft collects five reserve-substrate items, each of which is a
**candidate** post-cutover increment. Severity is annotated by the
worst-case impact on the cutover-gate-success-criteria *had it
been merged pre-cutover*:

| Reserve ID | Class | Surface affected | Post-cutover intent |
|---|---|---|---|
| RES-D1 | identity-substrate-evolution | Identity-Substrate (§3.2 of v0.4.3 / v0.4.2): the BIP32 sub-key derivation path is currently pinned to a single Persona-Engine binary tag. A post-cutover roadmap item is to introduce a second derivation path under a stable HD-prefix so federation-pair rotations no longer require a Persona-Engine binary re-cut. | Add §3.2.1 covering the dual-path HD-prefix layout, the rotation-overlap window (analogous to the existing `vector-3-rotation-overlap.json` fixture), and the conformance bit for a verifier that observes a frame signed under either path. |
| RES-D2 | capability-token-refinements | Caveat predicates (§7 canonical wire format / §3 catalogue): the current Datalog-caveat vocabulary lacks a `min-attenuation-depth` predicate. Federation diff (`n3_chain_walker`) currently approximates this at policy level; pulling it into the wire-level predicate set lets verifiers reject under-attenuated tokens earlier and reduces the policy-surface that downstream adopters must implement. | Add §7.4 covering the `min-attenuation-depth` predicate semantics, the canonical wire encoding (one varint), the per-issuer interaction with the `max-attenuation-depth` predicate (must be `min <= max`, else producer-side abort), and the verifier conformance bit. |
| RES-D3 | bridge-audit-cleanup | Bridge audit writer (Pin-Pack record #10, `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND`): the audit-writer ENV-flag schema currently distinguishes only `python` / `rust-shim` modes. Post-cutover, the Rust-native bridge-audit-writer is the production path; the shim mode becomes a fallback-only mode. The reserve-draft codifies the post-cutover three-mode schema (`python` / `rust-native` / `shim-fallback`) and the operator-contract for switching between them. | Add §4.1.10a sub-row covering the three-mode schema, the precedence rule (`rust-native > shim-fallback > python`), the operator-contract for graceful degradation, and the audit-trail invariant (every bridge-audit envelope MUST carry a mode-tag in its outer metadata). |
| RES-D4 | schema-registry-v2-prep | Schema registry (`wirelang/specs/schema-registry-spec.md`): the current schema-registry is a single-author single-anchor design. Post-cutover, an OTS-anchored multi-author registry is wanted so federation peers can publish their own schema extensions without consuming Wakir-Labs anchor capacity. The reserve-draft codifies the v2 registry-frame layout, the anchor-cost-attribution rule (the publishing peer pays the OTS-anchor cost on its own side; Wakir-Labs registry-side anchor cost is a small registry-pointer only), and the verifier-conformance bit. | Add §8.5 covering the registry-v2 frame layout (a thin `registry-pointer` frame referencing an externally-anchored schema document), the federation-side discovery contract (peer publishes its registry URL via a `registry-pointer-record` in the `route_registry_nats_kv_backend`), and the verifier-conformance bit for accepting a peer-anchored schema as binding. |
| RES-D5 | recovery-drill-leaf-projection-v2 | Recovery drill leaf-projection (`wirelang/specs/recovery-drill-leaf-projection.md`): the current leaf-projection contract assumes a single-shard recovery-drill (Phase-3 substrate). Post-cutover Phase-4 sequence-promotion will introduce sharded recovery-drills; the reserve-draft codifies the multi-shard leaf-projection invariant so the sharding step does not require a wire-format-bump. | Add §6.4 covering the multi-shard leaf-projection envelope, the shard-id encoding, the cross-shard merge invariant (a verifier observing shards `0..n-1` MUST be able to reconstruct a single canonical projection), and the operator-contract for the sharding-day transition. |

**Source-of-truth direction (Reza-Hand 2026-05-19, Tag-63):**
v0.4.3 (`pre-cutover-freeze`) is the conformance anchor; v0.4.4-draft
is the post-cutover reserve substrate. A reserve item is a
candidate, not a contract. The post-cutover sequence-promotion
step (Phase-4 governance, TBD) will decide which RES-Dn items get
folded into the v0.4.4 or v0.5 final document.

## 2. Conformance keywords

The keywords MUST, MUST NOT, SHOULD, SHOULD NOT, MAY are used as
in RFC 2119 / RFC 8174 (unchanged from v0.4.3 §2).

A producer / verifier / operator conformant to v0.4.3 is **not**
required to be conformant to v0.4.4-draft. The draft introduces
**no new conformance obligations**. Any text in v0.4.4-draft that
appears to bind a participant is **non-normative** until the
sequence-promotion step has flipped the document's `status:` away
from `post-cutover-reserve-draft`.

Specifically:

- A v0.4.3-conformant verifier MUST reject any frame carrying
  `wirelangversion: 0.4.4-draft` as a protocol error.
- A v0.4.3-conformant producer MUST NOT emit a frame carrying
  `wirelangversion: 0.4.4-draft`.
- A v0.4.3-conformant operator MUST NOT switch a Pin-Pack record
  to a backend that references the v0.4.4-draft document.

The above three MUSTs are the **draft-isolation invariant** and
are the only normative content of v0.4.4-draft.

## 3. Carry-forward inventory from v0.4.3 (§3)

v0.4.3 §3 (Phase-3a Rust foundation, sixteen-row catalogue,
Identity-Substrate contract, Foundation classification, crate ↔
welle mapping) is carried forward by reference. v0.4.4-draft does
not modify, extend, or re-baseline §3.

The reserve item RES-D1 (identity-substrate-evolution) proposes a
new §3.2.1 sub-section; that text is collected in §6.1 of this
document and is non-normative until promotion.

## 4. Carry-forward inventory from v0.4.3 (§4)

v0.4.3 §4 (ten Pin-Pack-wired boot records, ENV-flag value space,
switch atomicity, default-by-welle-state) is carried forward by
reference. v0.4.4-draft does not modify, extend, or re-baseline
§4.

The reserve item RES-D3 (bridge-audit-cleanup) proposes a new
§4.1.10a sub-row; that text is collected in §6.3 of this document
and is non-normative until promotion.

### 4.1 Carry-forward of the ten Pin-Pack-0.5.1 boot records

For audit-locality, the ten Pin-Pack-0.5.1 boot records
(v0.4.3 §4.1, mirroring v0.4.2 §4.1) are restated here verbatim.
This is a structural mirror only; the substance lives in v0.4.3
§4.1 and the Pin-Pack source-of-truth at
`infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml`.

| Pin-Pack record # | Component | Selector ENV |
|---|---|---|
| 1 | `persona-engine-recovery` | `WAKIR_RECOVERY_BACKEND` |
| 2 | `persona-engine-state-backing` | `WAKIR_STATE_BACKING_BACKEND` |
| 3 | `persona-engine-fsm` | `WAKIR_FSM_BACKEND` |
| 4 | `persona-engine-v907-verify` | `WAKIR_V907_VERIFY_BACKEND` |
| 5 | `persona-engine-bridge-diff` | `WAKIR_BRIDGE_DIFF_BACKEND` |
| 6 | `persona-engine-subscribe-loop` | `WAKIR_SUBSCRIBE_LOOP_BACKEND` |
| 7 | `persona-engine-anchor-emitter` | `WAKIR_ANCHOR_EMITTER_BACKEND` |
| 8 | `persona-engine-svid-workload-identity` | `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND` |
| 9 | `persona-engine-federation-resolver` | `WAKIR_FEDERATION_RESOLVER_BACKEND` |
| 10 | `persona-engine-bridge-audit-writer` | `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND` |

This table is the same byte-anchor as v0.4.3 §4.1 and v0.4.2 §4.1.
If any row above disagrees with the live v0.4.3 §4.1 table, that
is a v0.4.4-draft bug (not a v0.4.3 bug) and the draft is the
side that must be repaired.

## 5. §5 / §6 / §7 / §8 / §9 / §10 carry-forward

§5 (welle inventory), §6 (Bug-42 contract), §7 (canonical wire
format), §8 (operator contract), §9 (Phase-3c cutover), and §10
(audit conformance) are carried forward from v0.4.3 by reference.
v0.4.4-draft does not modify, extend, or re-baseline any of these
sections.

The reserve items RES-D2 (capability-token-refinements),
RES-D4 (schema-registry-v2-prep), and RES-D5 (recovery-drill-
leaf-projection-v2) propose additions to §7, §8, and the
companion document `recovery-drill-leaf-projection.md`. Those
texts are collected in §6.2, §6.4, and §6.5 of this document and
are non-normative until promotion.

## 6. Reserve-substrate (non-normative)

The following five sub-sections collect the candidate text for the
five reserve items. The text is written in normative voice (MUST,
MUST NOT, SHALL, MAY) for ease of post-cutover promotion, but
**the draft-isolation invariant of §2 overrides** — none of this
text is binding until the sequence-promotion step fires.

### 6.1 RES-D1: identity-substrate-evolution (candidate §3.2.1)

A v0.4.4-or-later Identity-Substrate MUST support dual-path BIP32
sub-key derivation under a stable HD-prefix.

The first path (`m/44'/<wakir-coin-type>'/0'/0/<index>`) is the
v0.4.3 path; it remains the default-emit path.

The second path (`m/44'/<wakir-coin-type>'/0'/1/<index>`) is the
post-cutover rotation-path; it MAY be used to issue a federation-
pair rotation without re-cutting the Persona-Engine binary.

A verifier observing a frame signed under either path MUST accept
the frame as long as the HD-prefix is one of the two pinned paths
and the sub-key index falls within the per-issuer overlap window
(default 256 indices each side; configurable via a new
`WAKIR_BIP32_OVERLAP_WINDOW_LEN` ENV-flag with default `256`).

The rotation-overlap window is the same shape as the existing
`tests/fixtures/wakir-ftd-vectors/vector-3-rotation-overlap.json`
shape; a new fixture
`vector-3a-rotation-overlap-dual-path.json` will be added in the
promotion PR.

### 6.2 RES-D2: capability-token-refinements (candidate §7.4)

A v0.4.4-or-later canonical wire format MUST recognise a new
caveat predicate `min-attenuation-depth: <varint>`.

The semantics: the issuer asserts that the token MUST have been
attenuated at least `<varint>` times along its delegation chain
before reaching the verifier. A verifier observing a chain of
length `< varint` MUST reject the token with verdict
`under-attenuated`.

The canonical wire encoding is one varint of `<value>` following
the predicate tag byte. The predicate tag byte is currently
unallocated in the v0.4.3 §3 catalogue and will be allocated as
catalogue-row #17 (`min-attenuation-depth`) in the promotion PR.

The per-issuer interaction: if a token carries both
`min-attenuation-depth: A` and `max-attenuation-depth: B` (the
latter is already in v0.4.3), then `A <= B` MUST hold. A
producer attempting to emit a token with `A > B` MUST abort with
error `predicate-interval-empty`.

### 6.3 RES-D3: bridge-audit-cleanup (candidate §4.1.10a)

A v0.4.4-or-later operator contract MUST recognise three modes for
the Pin-Pack record #10 backend selector
`WAKIR_BRIDGE_AUDIT_WRITER_BACKEND`:

- `python` — the Phase-2 / Phase-3a Python writer; legacy mode.
- `rust-native` — the Phase-3c Rust-native writer; production mode.
- `shim-fallback` — the Phase-3a Rust shim over the Python writer;
  fallback mode for transitional windows.

Precedence: `rust-native > shim-fallback > python`. The operator
contract is that under graceful degradation, the operator MAY
switch from `rust-native` to `shim-fallback` without a Persona-
Engine restart; switching to or from `python` MUST be done with a
Persona-Engine restart.

Every bridge-audit envelope MUST carry a mode-tag in its outer
metadata (`mode: python | rust-native | shim-fallback`). The
audit-trail invariant is that a downstream WAT-leaf MUST be able
to identify the writer-mode from the envelope alone, without
consulting the Pin-Pack at audit time.

### 6.4 RES-D4: schema-registry-v2-prep (candidate §8.5)

A v0.4.4-or-later schema-registry MUST support an OTS-anchored
multi-author layout.

The v2 registry-frame is a thin `registry-pointer` frame
referencing an externally-anchored schema document. The frame
layout (one OTS-anchor pointer, one peer-identity, one
schema-id) is wire-stable; the schema document itself is opaque
to the wire format.

Federation-side discovery: a peer publishes its registry URL via
a `registry-pointer-record` in the
`route_registry_nats_kv_backend` (currently used for federation-
peer route discovery). The record is keyed by peer-identity and
versioned by OTS-anchor pointer; two peers publishing the same
schema-id under different anchors does not collide (the registry
keeps both, and the federation-route walker disambiguates by
peer-identity).

Anchor-cost-attribution rule: the publishing peer pays the OTS-
anchor cost on its own side; Wakir-Labs registry-side anchor
cost is a small registry-pointer only (one OTS-anchor per
~1000 registry-pointer-records, amortised). A peer that does not
have OTS-anchor capacity MAY publish under a Wakir-Labs-side
courtesy-anchor, subject to a courtesy-anchor budget.

A verifier observing a frame that references a peer-anchored
schema MUST accept the schema as binding if and only if (a) the
OTS-anchor pointer resolves to a confirmed Bitcoin block and
(b) the publishing peer-identity is a recognised federation peer.

### 6.5 RES-D5: recovery-drill-leaf-projection-v2 (candidate §6.4 of `recovery-drill-leaf-projection.md`)

A v0.4.4-or-later recovery-drill MUST support sharded leaf-
projection.

The multi-shard leaf-projection envelope carries `shard-id`
(varint, range `0..n-1` where `n` is the shard-count for this
drill) and `shard-count` (varint, `>= 1`). The single-shard case
(`shard-count: 1, shard-id: 0`) is the Phase-3 substrate and
remains the default.

A verifier observing shards `0..n-1` MUST be able to reconstruct
a single canonical projection by concatenating the per-shard
leaf-trees in shard-id-ascending order. The canonical
concatenation invariant is that `concat(shard[0], shard[1], ...,
shard[n-1])` MUST byte-equal the single-shard projection over
the same underlying leaf-set.

Operator contract for the sharding-day transition: the operator
MAY introduce a sharded drill at any point post-cutover; the
sharded drill MUST be back-compatible with single-shard
verifiers (a single-shard verifier that observes only
`shard-id: 0` of an `n > 1` drill MUST emit verdict
`incomplete-projection` rather than `valid` or `invalid`).

## 7. Backward compatibility

A producer / verifier / operator running v0.4.0, v0.4.1, v0.4.2,
or v0.4.3 SHALL NOT be affected by v0.4.4-draft in any way. The
draft introduces no behavioural changes. The draft-isolation
invariant of §2 is the only normative content of this document.

The Pin-Pack-0.5.1-pre-cutover substrate
(`infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml`) remains
the source-of-truth for §4.1 ENV-flag schema. The draft does not
propose a Pin-Pack revision.

The Tag-58 freeze-seal probe over v0.4.3 remains intact: the
draft is a separate file (`wirelang-spec-v0-4-4-draft.md`) and
the seal probe hashes only `wirelang-spec-v0-4-3.md`. A v0.4.3
seal-probe run alongside this draft MUST emit `SEAL-INTACT`.

## 8. Audit conformance

A spec document v0.4.4-draft is audit-conformant if and only if:

- Frontmatter declares `version: 0.4.4-draft`.
- Frontmatter declares `status: post-cutover-reserve-draft` (the
  draft-isolation invariant §2 forbids any other status value
  until promotion).
- Frontmatter declares `parent: wirelang-spec-v0-4-3` (the
  parent-pointer is the conformance anchor; the `extends: 0.4.3`
  bit is its version-twin).
- Frontmatter declares `replaces: null` and `replaced-by: null`
  (the draft is not in any patch-trace chain).
- Frontmatter declares `freeze-marker: null` and
  `freeze-anchor: null` (the draft is not a freeze-marker).
- Frontmatter declares `activation-trigger:
  kw-24-cutover-T0-post-promotion` and `activation-policy:
  sequence-promotion-only` (the draft can only be activated by a
  post-cutover sequence-promotion step, not by an in-flight edit).
- The body declares the draft-isolation invariant §2 prominently
  (intro paragraph and §2 verbatim).
- The body carries forward §3, §4, §5–§10 by reference (no
  in-place edits to those sections).
- The body collects the five RES-Dn candidate texts in §6 only,
  and §6 is annotated as non-normative.

The hermetic test suite that accompanies this draft
(`tests/audit/test_wirelang_spec_v0_4_4_draft_tag63.py`,
twelve or more tests, Tag-63) enforces these invariants
statically (no NATS, no engine boot, no Rust build, no network
import).

## 9. Citation pointers

- Tag-53 PR (v0.4.3 pre-cutover-freeze parent):
  `wirelang/specs/wirelang-spec-v0-4-3.md`.
- Tag-50 PR #320 (v0.4.2 substance baseline carried forward):
  `wirelang/specs/wirelang-spec-v0-4-2.md`.
- Tag-58 PR (v0.4.3 freeze-seal probe):
  `tooling/audit/verify_wirelang_spec_freeze_seal.py` +
  `wirelang/specs/freeze-baseline.json`.
- Tag-60 PR (v0.4.3 OTS pre-anchor probe):
  `tooling/audit/verify_wirelang_spec_ots_pre_anchor.py`.
- Pin-Pack substrate (source-of-truth for §4.1, unchanged):
  `infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml`.
- Cutover-gate acceptance criteria:
  `docs/quality-gates/phase-3c-acceptance-criteria.md`.
- Recovery-drill leaf-projection (RES-D5 target):
  `wirelang/specs/recovery-drill-leaf-projection.md`.
- Schema-registry (RES-D4 target):
  `wirelang/specs/schema-registry-spec.md`.

— Reza
