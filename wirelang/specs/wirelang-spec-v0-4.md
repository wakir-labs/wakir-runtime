<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

---
spec: wirelang
version: 0.4.0
status: draft
supersedes: 0.3.0
replaced-by: null
date: 2026-05-18
audience: implementers, integrators, operators
license: CC-BY-4.0
---

# Wirelang Specification v0.4 (Phase-3 consolidation refresh)

This document is the Tag-45 consolidation refresh of the Wirelang
inter-agent messaging stack. It is the **Phase-3-era reference
spec**: it consolidates the Phase-3a Rust foundation surface,
the Phase-3b ENV-flag-driven double-runtime substrate, and the
Phase-3c per-welle cutover substrate, into one document that the
on-call operator and the auditor can read end-to-end without
chasing per-Tag memos.

> **v0.4.0 (2026-05-18, Tag-45):** Additive minor bump over v0.3.
> No on-the-wire change. No frame-attribute change. No caveat-
> predicate addition or removal. The change surface is operational
> metadata, runtime backend selection, and audit-baseline
> documentation. v0.3 producers, v0.3 verifiers, and v0.3 frames
> remain valid under v0.4 without rewrite.
>
> The motivation for cutting v0.4 now — three weeks before
> Phase-3c-Trigger (~KW 27, ADR-0063 §Phase-3c-Final-Cutover) —
> is that the Phase-3 operator surface is no longer expressible
> as a delta against v0.3. The Rust crates, the ENV-flag schema,
> the welle substrates, and the publish-mode contract fix anchor
> (Bug-42) together constitute a coherent operational substrate
> whose contract surface deserves a single reference doc rather
> than five cross-referenced per-Tag memos.

It supersedes the per-Tag refresh memos shipped during the
Sprint-Pengine-13 / Sprint-7 / Phase-3-trigger-window
(approximately Tag-39 through Tag-44) and references — but
does not duplicate — the JSON-Schema documents, the per-crate
READMEs under `wirelang-rust/crates/*/`, and the per-welle
runbooks under `docs/phase-3c/`.

The intent of v0.4 is **consolidation, not redesign**. The wire
format, the semantic envelope, the trust layer, and the
identity substrate are unchanged relative to v0.3. v0.4
documents the Phase-3 substrate so that the cutover can be
executed against a stable spec rather than against a moving
target.

## 1. Versioning and scope

### 1.1 Semver, re-stated

Wirelang carries a semver-like spec version. The frame attribute
`wirelangversion` (Layer 1) is the on-the-wire indicator.

- **Patch** (`x.y.Z`) — clarifications, typo fixes, additional
  examples. No schema or normative change.
- **Minor** (`x.Y.0`) — additive: new optional fields, new optional
  layers, new optional caveat predicates, new operational-metadata
  contracts whose violation was previously undefined. Existing v0.x
  frames remain valid against v0.x+ verifiers.
- **Major** (`X.0.0`) — breaking: removed fields, changed semantics,
  reserved-to-required transitions. Requires migration guidance.

v0.4.0 is a **minor** release relative to v0.3.0: every v0.3.0
frame is a valid v0.4.0 frame, and every v0.3.0 caveat is a valid
v0.4.0 caveat. v0.4.0 verifiers MUST accept frames stamped
`wirelangversion: 0.1.0`, `0.2.0`, `0.2.1`, `0.3.0` without
modification. There is no wire-format-version requirement to
upgrade.

### 1.2 What v0.4 covers

| Layer | Concern | Substrate | Schema | Spec text |
|---|---|---|---|---|
| 0 | Transport | NATS + JetStream (publish-mode contract enforced; §6, §9) | `schemas/layer-0-transport.json` | §6 + `specs/nats-subject-mapping-v1.md` |
| 1 | Wire format | CloudEvents 1.0 + Wakir extensions, RFC 8785 JCS | `schemas/layer-1-wire.json` | (unchanged from v0.2 §4; not re-stated here) |
| 2 | Semantic | JSON Schema 2020-12 + vocabulary anchor | `schemas/layer-2-semantic.json` | (unchanged from v0.2 §5; not re-stated here) |
| 3 | Trust | AIP `draft-prakash-aip-00` + Biscuit v3, Phase-2 vocabulary | `schemas/layer-3-capability-token.json`, `schemas/aip-document.json`, `schemas/datalog-caveat.json` | (unchanged from v0.3; vocabulary stable) |
| Identity | Persona substrate | secp256k1 BIP-32 + Ed25519 SLIP-0010 | (none — implementation in `wirelang/identity/` + `wirelang-rust/crates/persona-*`) | §7 + `specs/identity-substrate.md` |
| Runtime | Double-runtime substrate (Python ⇆ Rust) | ENV-flag-driven backend selection | (none — operational contract, §8) | §8 |
| Cutover | Per-welle component migration | Doppel-Welle cadence (ADR-0066) | (none — process contract, §9) | §9 |
| Audit | NATS-JetStream subjects baseline + publish-mode parity | static-pass auditor | (none — emission-side discipline, §10) | §10 |

Layer 4 (WAT audit anchoring) remains out-of-module and owned by
the WAT component. The contract from Wirelang to WAT is documented
in `specs/wat-leaf-projection.md` and unchanged in v0.4.

### 1.3 What v0.4 does **not** cover

- TEE attestation evaluation logic (`attests`, `tee_required`
  caveats). The predicates are reserved; verifiers MUST fail-closed
  on any token that references them. Phase-1b adoption per
  ADR-0023b — separate spec when promoted.
- A Wakir-native DID method (`did:wakir`). Requires an ADR before
  spec work begins. Until then, `did:web` is canonical.
- The Phase-3-trigger conditions themselves (these are
  ADR-0063 §Decision-Trigger + ADR-0065 §Decision-Trigger
  controlled, not spec controlled).
- The Phase-2c-Closeout consolidation of Adapter-A → Adapter-B
  (producer-rewrite). The Bug-42 fix anchor (§9) documents the
  contract; the rewrite is engineering work, not spec work.

## 2. Conformance keywords

The keywords MUST, MUST NOT, SHOULD, SHOULD NOT, MAY are used as
in RFC 2119 / RFC 8174 (unchanged from v0.2 §2).

A **producer** is conformant to v0.4 if every frame it emits is a
valid v0.4 frame, and if its publish-surface declaration matches
the §6 contract. A **verifier** is conformant to v0.4 if it
correctly accepts and rejects v0.4 frames, and if (when it is
also a subscriber) its subscribe-surface declaration matches the
§6 contract.

An **operator** is conformant to v0.4 if the runtime backend the
operator selects via the §8 ENV-flag schema matches the welle-
state documented in §9.

## 3. Phase-3a Rust foundation: the 15 Rust crates

**Normative status of this section:** §3 is a reference catalogue.
The crates exist independently of this spec; the spec records the
existence, role, and Phase-3-cutover-target classification of
each crate so that the operator and the auditor have a single
source of truth for "what runs in the Rust runtime, and what
is its Phase-3 role".

### 3.1 Catalogue

The Rust workspace under `wirelang-rust/crates/` contains 32
crates as of Tag-45. Of these, fifteen are **Phase-3a-foundation**
crates — i.e., they are the deterministic substrate that the
Phase-3b ENV-flag substrate (§8) selects between, and that the
Phase-3c per-welle cutover (§9) migrates from Python-default to
Rust-default one welle at a time.

| # | Crate | Phase-3-role | Welle | Substrat-Klassifikation |
|---|---|---|---|---|
| 1 | `persona-canonical-form` | Identity hash substrate (axis-A JCS canonicalisation) | Foundation | Identity-Substrate-kritisch (byte-stable) |
| 2 | `persona-canonical-form-yaml` | Persona-md axis-A YAML parsing companion | Foundation | Identity-Substrate-kritisch |
| 3 | `persona-hash` | V-907 persona-hash compute (axis-A → JCS → sha256) | Welle 1 | Identity-Substrate-kritisch |
| 4 | `persona-engine-v907-verify` | V-907 verify-pin (compute + match) | Welle 1 | Identity-Substrate-kritisch |
| 5 | `persona-engine-svid-workload-identity` | SPIFFE Workload-API gRPC client | Welle 2 | Identity-Substrate-adjacent (SPIRE-Trust) |
| 6 | `persona-engine-bridge-audit-writer` | Engineering-output double-sink (Bridge-Forward + state-backing) | Welle 3 | WAT-anchor-relevant (write, idempotent) |
| 7 | `persona-engine-bridge-audit-replay` | Bridge-Audit replay/diff substrate | Welle 3 (companion) | WAT-anchor-relevant |
| 8 | `persona-engine-bridge-diff` | Bridge-Audit diff engine | Welle 3 (companion) | Cross-Runtime-Parity-Probe |
| 9 | `persona-engine-bridge-forward` | Bridge-Forward NATS dispatcher (publish-mode-contract anchor) | Welle 3 (companion) | Bug-42-relevant; §9 anchor |
| 10 | `persona-engine-state-backing` | Persona-State persistence (InMemory + NatsKV) | Welle 4 | State-Schema-relevant (JCS-byte-parity) |
| 11 | `persona-engine-fsm` | Lifecycle-state-machine (uninstantiated → … → despawned) | Welle 5 | Cross-modul state contract |
| 12 | `persona-engine-subscribe-loop` | NATS subscribe-loop + envelope parse | Welle 6 | NATS-state-relevant; §9 anchor |
| 13 | `persona-engine-recovery` | Recovery-drill orchestration | Welle 7 | Cross-modul orchestration |
| 14 | `persona-engine-recovery-replay` | Recovery-replay substrate (Welle-7 companion) | Welle 7 (companion) | Cross-modul orchestration |
| 15 | `persona-engine-anchor-emitter` | WAT-anchor emission substrate (Layer-4 hand-off) | Foundation | WAT-Wirelang-boundary |

The remaining seventeen crates in the workspace (e.g.,
`persona-cli`, `persona-converter`, `persona-engine-smoke`,
`persona-migration*`, `persona-pilot-export`, `persona-validator`,
`persona-engine-frontmatter-parser`, `persona-engine-format`,
`persona-engine-loop-latency-bench`, `persona-engine-v907-recompute-bench`,
`persona-engine-anchor-submit-worker`, `persona-engine-nats-subjects`,
`persona-engine-federation-frame-parser`,
`persona-engine-federation-resolver`,
`persona-engine-integration-tests`,
`persona-engine-migrate-version`,
`persona-engine-smoke`) are tooling, benchmarks, integration
harnesses, or migration utilities. They are not on the Phase-3c
welle path because they are not user-visible runtime components;
they ship as Rust-only from inception or are CI-internal.

### 3.2 Identity-Substrate-kritische Crates: byte-stability contract

Crates marked "Identity-Substrate-kritisch" in §3.1 (#1, #2, #3,
#4) MUST produce output that is byte-identical to the Python
counterpart on the same input. This is the
`PersonaStateSnapshot`-byte-stability anchor described in the
Selin-Roadmap (`docs/decisions/persona-engine-rust-rewrite-roadmap.md`
§1.3): any format mismatch between Python and Rust engines
breaks recovery irreversibly.

Conformance verification: Phase-3b ENV-flag substrate (§8) runs
both backends side-by-side and emits a per-call envelope-hash
parity report (the Bridge-Audit-Writer-Konsistenz-Report,
AC-1 in `docs/quality-gates/phase-3c-acceptance-criteria.md`).
Any non-zero divergence on identity-substrate-kritische crates
is a Welle-Stop-condition.

### 3.3 Foundation crates: pre-cutover Rust-only

Crates #1, #2, #15 are "Foundation" — they ship as Rust-only
from Phase-3a inception. There is no Python counterpart that the
ENV-flag substrate could switch to. The contract is "Rust must
not regress", not "Python ⇆ Rust parity".

This is intentional: `persona-canonical-form` is the JCS
canonicalisation primitive on which every higher-layer
byte-stability claim depends. If it had a Python counterpart,
the parity oracle would be circular (a Python-JCS-bug would not
be detectable because the Python-byte-stream is the oracle).
The same reasoning applies to `persona-canonical-form-yaml`
and `persona-engine-anchor-emitter`.

### 3.4 Crate ↔ welle mapping (normative)

The Welle column in §3.1 is normative: it documents which crate
is the cutover target of which welle. Operators MUST NOT flip the
ENV-flag for a crate to `rust` outside that crate's welle window
unless an asymmetric-rollback (§9.4) or a foundation-only path
(§3.3) is in effect.

## 4. Phase-3b ENV-flag schema: the 9 engine components

**Normative status of this section:** §4 is the contract surface
of the double-runtime substrate. It is the contract under which
the Phase-3c cutover (§9) operates. Violations are silent
runtime drift — the same failure class as Bug-42 was for §6.

### 4.1 The nine components

The Phase-3b ENV-flag schema covers **nine** engine components.
Seven are the Phase-3c-welle targets (§9); two are foundation
components that participate in the ENV-flag schema but are not
on the cutover path (because they have no Python counterpart;
§3.3).

| # | Component | Crate(s) (§3) | ENV-Flag | Phase-3c welle | Notes |
|---|---|---|---|---|---|
| 1 | `v907_verify` | `persona-hash`, `persona-engine-v907-verify` | `WAKIR_PE_V907_BACKEND` | Welle 1 | Read-only; lowest risk |
| 2 | `svid_workload_identity` | `persona-engine-svid-workload-identity` | `WAKIR_PE_SVID_BACKEND` | Welle 2 | Deterministic lookup; low risk |
| 3 | `bridge_audit_writer` | `persona-engine-bridge-audit-writer`, `-bridge-audit-replay`, `-bridge-diff`, `-bridge-forward` | `WAKIR_PE_BRIDGE_AUDIT_BACKEND` | Welle 3 | Write, idempotent; Henrik-Caution |
| 4 | `state_backing` | `persona-engine-state-backing` | `WAKIR_PE_STATE_BACKING_BACKEND` | Welle 4 | Persistent state; schema-migration-rollback critical |
| 5 | `lifecycle_state_machine` | `persona-engine-fsm` | `WAKIR_PE_FSM_BACKEND` | Welle 5 | Cross-modul state |
| 6 | `subscribe_loop` | `persona-engine-subscribe-loop` | `WAKIR_PE_SUBSCRIBE_LOOP_BACKEND` | Welle 6 | NATS-state; Bug-42-replay |
| 7 | `recovery_workflow` | `persona-engine-recovery`, `-recovery-replay` | `WAKIR_PE_RECOVERY_BACKEND` | Welle 7 | Cross-modul orchestration; highest risk |
| 8 | `canonical_form` | `persona-canonical-form`, `-canonical-form-yaml` | (not switchable) | Foundation (§3.3) | Rust-only; ENV-flag accepted-and-ignored |
| 9 | `anchor_emitter` | `persona-engine-anchor-emitter` | (not switchable) | Foundation (§3.3) | Rust-only; ENV-flag accepted-and-ignored |

> **Vermutung-P2** (spec-author marking): The exact ENV-flag
> variable names (`WAKIR_PE_*_BACKEND`) are documented here as
> the canonical schema, derived from the §"ENV-Flag" column in
> `docs/quality-gates/phase-3c-acceptance-criteria.md` plus the
> `WAKIR_PE_*` namespace conventions in the Quadlet substrate.
> The Phase-3a-Rust-rewrite-engineering-spawn is the substantive
> source-of-truth and may rename one or more of these — in which
> case this section is patched in a v0.4.1 additive-patch release
> without re-cutting the spec.

### 4.2 ENV-flag value space

Each switchable ENV-flag (`WAKIR_PE_*_BACKEND` for components
#1–#7 in §4.1) takes one of three values:

- `python` — the legacy Python implementation
  (`wirelang/persona_engine/*.py`).
- `rust` — the Rust implementation
  (`wirelang-rust/crates/persona-engine-*`).
- `parity` — both backends run; output is compared and divergence
  is logged + reported to the Bridge-Audit-Writer-Konsistenz-
  Report (AC-1). Used during Beobachtungs-Fenster (§9.2).

Unset is equivalent to `python` for components #1–#7 prior to
their welle-trigger date, and to the welle-default (`python`
pre-welle, `rust` post-welle) thereafter. This is the
**default-by-welle-state** rule.

### 4.3 ENV-flag-switch atomicity

A backend switch (`python` → `rust` or vice versa) is performed
by a single `systemctl restart wakir-persona-engine` after the
ENV-flag is updated in the Quadlet unit. The switch SLA is
**≤600 s** wall-time from flag-edit to running-state, per
HC-AC-2 in `docs/quality-gates/phase-3c-acceptance-criteria.md`.

The switch MUST be atomic at the **component** granularity:
flipping `WAKIR_PE_STATE_BACKING_BACKEND` does not flip any other
component. This is the **asymmetric-rollback substrate** that
makes single-component rollback (§9.4) safe.

### 4.4 Default-by-welle-state contract

For an operator who has not explicitly set any ENV-flag, the
effective backend per component is determined by the current
welle state:

| Welle state | Component default backend |
|---|---|
| Pre-welle-trigger | `python` (legacy) |
| Welle Beobachtungs-Fenster (5 days post-trigger) | `parity` |
| Post-welle-acceptance | `rust` |
| Post-welle rollback (HC-AC-2 triggered) | `python` (until re-trigger) |

The Quadlet-Default-ENV-Flags substrate (WE-2 in
`docs/quality-gates/phase-3c-acceptance-criteria.md`) is the
operational implementation of this contract: at Welle-7-acceptance,
all seven flags are pinned to `rust` in the Quadlet defaults,
which closes the Phase-3c cutover (`test_welle_7_we_2_quadlet_all_seven_rust`).

## 5. Phase-3c welle substrates: the 7 cutover wellen

**Normative status of this section:** §5 documents the cutover
**substrate**, not the cutover **schedule**. The schedule is
ADR-0066 §Beschluss controlled and may shift; the substrate
contract is spec-stable.

### 5.1 Welle inventory

The seven Phase-3c wellen are the seven components #1–#7 in §4.1,
cut over in the order given. The cadence is Doppel-Welle (two
components per kalender-week) per ADR-0066 §Beschluss; the
substrate contract is per-welle regardless of cadence.

| Welle | Component | Risiko-Klasse | Welle-Fokus |
|---|---|---|---|
| 1 | `v907_verify` | Niedrigste (read-only) | V-907-pin-attest payload parity |
| 2 | `svid_workload_identity` | Niedrig (deterministic lookup) | SPIRE-SVID-payload hash parity |
| 3 | `bridge_audit_writer` | Mittel (write, idempotent) | WAT-anchor idempotency + hold-out Python writer |
| 4 | `state_backing` | Erhöht (persistent state) | JCS-byte-parity + schema-migration-rollback |
| 5 | `lifecycle_state_machine` | Erhöht (cross-modul state) | Transition-table cross-lang parity + Welle-4 contract |
| 6 | `subscribe_loop` | Hoch (NATS state) | Subscription-cursor parity + Bug-42-replay |
| 7 | `recovery_workflow` | Höchste (cross-modul orchestration) | Recovery-decision parity + Welle-Ende WE-1…WE-4 |

### 5.2 Per-welle substrate elements

Each welle ships **seven** substrate elements (the welle-substrate
heptad):

1. **Runbook.** `docs/phase-3c/welle-N-*-runbook.md` — operator
   step-by-step from trigger to acceptance.
2. **Cutover-smoke.** `docs/phase-3c/welle-N-cutover-smoke.md` —
   live-bring-up smoke discipline (Memory: live-bring-up-sandbox-gap).
3. **E2E acceptance test.** `tests/acceptance/phase_3c/
   test_welle_N_<component>_e2e.py` — the AC-1…AC-5 contract for
   the welle.
4. **CI workflow.** `.github/workflows/phase-3c-welle-N-validation.yml`
   — gating the welle's PR-merge path against the AC-suite.
5. **Bridge-Audit-Writer-Konsistenz-Report entry.** Per-welle
   line in the daily-probe report; the AC-1 oracle.
6. **Quadlet default-flag pin.** WE-2 contract end-state — at
   welle-acceptance, the welle's ENV-flag default in the Quadlet
   unit flips from `python` (or `parity`) to `rust`.
7. **Rollback drill artefact.** `tests/acceptance/phase_3c/
   test_welle_N_rollback_drill.py` — the HC-AC-2 atomic-switch-
   under-600s gate.

The heptad is normative: a welle is **not** in "acceptance" state
unless all seven elements are green. A welle with a green E2E
test but a missing rollback-drill artefact is a Welle-Stop.

### 5.3 Doppel-Welle additional contract

When two wellen are cut in the same kalender-week (Doppel-Welle,
per ADR-0066), an additional five DW-AC-1…DW-AC-5 acceptance
criteria apply (`docs/quality-gates/phase-3c-acceptance-criteria.md`
§9):

- **DW-AC-1.** Symmetric drift-detection: both components' parity
  reports must be 5/5 green.
- **DW-AC-2.** No cross-component-drift: a divergence on component
  A must not be silently absorbed by component B.
- **DW-AC-3.** Asymmetric single-component rollback: a bug in one
  component rolls only that component to `python`; the other
  stays `rust`. Elapsed ≤10min ENV-flag-switch SLA.
- **DW-AC-4.** Coordinated bring-up: both components reach
  Beobachtungs-Fenster within ≤24 h of each other.
- **DW-AC-5.** Coordinated acceptance: both components reach
  AC-1…AC-5-green within ≤48 h of each other (else solo-welle
  fallback per ADR-0066 §Mitigation).

The Doppel-Welle substrate is a Phase-3c-Beschleuniger (4 Wochen
statt 7) and not a contract-relaxation: every DW-AC-N criterion is
additive to the AC-1…AC-5 contract of each component.

### 5.4 Welle-Ende WE-1…WE-4 (Welle-7 only)

Welle-7 (recovery_workflow) is the last welle and carries an
additional **Welle-Ende** contract (WE-1…WE-4) per
`docs/quality-gates/phase-3c-acceptance-criteria.md`:

- **WE-1.** All seven welle artefact-heptads are complete and
  green (28 artefacts ≠ welle-7-skeleton).
- **WE-2.** All seven Quadlet-Default-ENV-flags are pinned to
  `rust` in the Quadlet unit (closes the Phase-3c-cutover).
- **WE-3.** The Python `wirelang/persona_engine/*.py` surface is
  flagged "deprecated, retained for rollback only" (release-note
  contract, not removal-contract; v0.4 does not remove the
  Python surface).
- **WE-4.** The 5-day post-welle-7 Beobachtungs-Fenster has
  expired without an HC-AC-2 trigger.

When WE-1…WE-4 are all green, Phase-3c is closed and the spec
enters the **Phase-3-Closeout** state. A v0.5 spec MAY then
remove the §4–§5 ENV-flag substrate sections (or migrate them
to a historical annex); v0.4 does not pre-commit to that.

## 6. Bug-42 fix anchor: publish-mode-contract + Adapter-B

**Normative status of this section:** §6 is a cross-reference and
reaffirmation of the v0.2.1 §13 (Layer-0 Subscribe-Mode contract)
substrate, anchored against the Phase-2c-Closeout Adapter-B
migration path. The wire-level contract is **unchanged** from
v0.2.1 §13; v0.4 §6 records the closure of the engineering work
that v0.2.1 §13 enumerated as "strategic target".

### 6.1 The contract, re-stated

Producers and subscribers MUST declare and agree on their
publish/subscribe surface (`core` / `jetstream` / `jetstream-push`
/ `jetstream-pull`) before a pipe is brought up. The §13.2
compatibility matrix is the canonical reference. A pipe whose
producer-surface ⇆ subscriber-surface combination is `NO` in
the matrix is a **broken pipe at the Layer-0 substrate**, even
though the wire format is well-formed.

### 6.2 Adapter-B status: Phase-3-trigger-ready

v0.2.1 §13.4 enumerated three adapter shapes:

- **Adapter A.** Stream-mirror (a side-process subscribes via
  core and republishes via JetStream). Transition mechanism.
- **Adapter B.** Producer-rewrite (`nc.publish` → `js.publish`).
  Strategic target for Phase-2c-Closeout.
- **Adapter C.** Subscribe-side fallback (subscribe via both
  surfaces, dedup by `id`). Transition mechanism; SHOULD NOT
  remain in production beyond a Phase-boundary.

v0.4 records the following Adapter-B status:

- The `wirelang/cli/bridge_forward.py` CLI ships a
  `--publish-mode {core,jetstream}` switch and the `js.publish`
  dispatch path. Producer-side rewrite-ready.
- The `wirelang/persona_engine/publish_mode_contract.py` module
  encodes the §13.2 compatibility matrix as a static gate
  callable by both producers (pre-publish) and subscribers
  (pre-bind, via `require_compatible(...)`).
- The Tag-41 PR #265 closure documented in
  `docs/audit/nats-jetstream-subjects-audit.md` is the
  engineering-side substantive close.

Phase-3c cutover proceeds with the assumption that all
Wirelang pipes that traverse operationally distinct producer
and subscriber surfaces are either (a) Adapter-B-migrated
(producer flipped to `js.publish`) or (b) explicitly Adapter-A-
configured (and that configuration is captured in the operator
runbook + audited per §10).

Welle 6 (`subscribe_loop`) carries a **Bug-42-replay** AC-component
(`welle-fokus` column in §5.1) — the welle's e2e test reproduces
the Sprint-Pengine-13 silent-drop F-1 class as a regression-test
and verifies that the Rust subscribe-loop honours the same
publish-mode-contract gate that the Python loop does.

### 6.3 Failure-mode inventory: unchanged

The F-1 through F-6 failure-mode inventory in v0.2.1 §13.3 is
**unchanged** in v0.4. v0.4 records that the
`docs/audit/nats-jetstream-subjects-audit.md` static-pass auditor
(§10) is the operational diagnostic substrate for F-1 through
F-4 (the "silently drops messages" class); F-5 and F-6 remain
operator-runbook-diagnosed.

## 7. Identity substrate

Identity-substrate content (axis-A canonicalisation, persona-hash
derivation, V-907 verify-pin, DID document signing, AIP document
transport-fetch, FTD verifier, federation resolver, kid resolver,
DNS anchor, SPIFFE Workload-API adapter) is **unchanged** from
v0.3.0. See `specs/identity-substrate.md` for the substrate spec
and the Rust implementations under
`wirelang-rust/crates/persona-canonical-form*`, `persona-hash`,
`persona-engine-v907-verify`, and
`persona-engine-svid-workload-identity` for the Phase-3a-foundation
realisations.

The v0.4 addition is operational only: see §3.2 for the
byte-stability contract that the Phase-3b ENV-flag substrate (§4)
exercises and the Phase-3c-cutover (§5) validates.

## 8. NATS-JetStream subjects audit baseline

**Normative status of this section:** §8 documents the audit
**baseline** — the static-pass auditor that watches the
emission-side discipline of publish-mode declarations across
the codebase. The audit is a defence in depth against silent
regression of the v0.2.1 §13 contract (re-stated in §6).

### 8.1 Audit substrate

The audit is implemented by:

- **Companion script.** `scripts/audit/nats-jetstream-subjects-audit.py`
  — static, stdlib-only, hermetic pass over the working tree.
- **Hermetic tests.** `tests/audit/test_nats_jetstream_subjects_audit.py`
  — covers the parse + classify + report-emit pipeline.
- **First report.** `reports/audit/2026-05-18-nats-jetstream-subjects-audit.md`
  — the Tag-43 baseline report.
- **CI workflow.** `.github/workflows/nats-jetstream-subjects-audit.yml`
  — re-runs the audit on every PR and emits a check-status.

The audit does **not** run NATS, does **not** import `nats-py`,
and does **not** execute the engine. It is a deterministic grep
+ parse + classify pipeline over the working tree's `*.py` files.

### 8.2 Audit findings vocabulary

The audit classifies each NATS publish/subscribe call site as:

- **`PUB_CORE`** — `nc.publish(...)` call (core-surface publish).
- **`PUB_JS`** — `js.publish(...)` call (JetStream-surface publish).
- **`SUB_CORE`** — `nc.subscribe(...)` call (core-surface subscribe).
- **`SUB_JS_PULL`** — JetStream-pull-consumer fetch.
- **`SUB_JS_PUSH`** — JetStream-push-consumer subscribe.
- **`CONFIG_PUBLISH_MODE_CONTRACT`** — call site that consults
  `publish_mode_contract.require_compatible(...)` or the
  CLI `--publish-mode` flag.
- **`UNCLASSIFIED`** — call site that uses NATS but does not
  declare its surface via §13/§6 mechanisms; this is the
  **silent-drift candidate** class.

### 8.3 Baseline guarantee

At v0.4 publication, the Tag-43 audit baseline report
(`reports/audit/2026-05-18-nats-jetstream-subjects-audit.md`)
documents zero `UNCLASSIFIED` findings against the Tag-43
working tree. The audit CI workflow enforces this as a hard
gate: any PR that introduces an `UNCLASSIFIED` call site
fails check `nats-jetstream-subjects-audit` and cannot merge.

This is the **emission-side discipline counterpart** of the
verifier-side discipline encoded by `publish_mode_contract.
require_compatible(...)`. Together they constitute the Phase-3-
era Bug-42 defence in depth:

- Compile-time/import-time: `publish_mode_contract` gate.
- Static-pass/CI-time: NATS-JetStream-subjects-audit.
- Run-time/operator-time: surface-declaration in runbooks (§6.1).
- Cutover-time: Welle-6 Bug-42-replay e2e (§6.2).

## 9. Forward compatibility and migration v0.3 → v0.4

### 9.1 Additive minor release, re-stated

v0.4.0 demonstrates the additive-minor pattern (per §1.1).
Specifically:

- v0.4 introduces no new mandatory frame attributes.
- v0.4 introduces no new caveat predicates (vocabulary v0.2,
  the 18+2+N1/N2/R/P substrate, remains stable).
- v0.4 introduces no new on-the-wire schema. The
  `schemas/*.json` files referenced from §1.2 are unchanged in
  byte-content from v0.3.
- v0.4 documents the Phase-3a Rust foundation (§3), the
  Phase-3b ENV-flag substrate (§4), the Phase-3c welle
  substrate (§5), the Bug-42 fix anchor (§6 re-stating §13),
  and the audit baseline (§8) as integral parts of the spec
  rather than as out-of-spec runbooks.

### 9.2 Backward-compatibility note v0.3 → v0.4 (normative)

A v0.4 verifier MUST accept every v0.3, v0.2.1, v0.2.0, v0.1.0
frame as-is. The acceptance rule is:

1. **Wire format.** Layer-0/1/2 contract unchanged. v0.3
   frames parse against v0.4 schemas without modification.
2. **Trust layer.** Layer-3 vocabulary unchanged. v0.3 caveats
   evaluate against v0.4 verifiers with identical accept/reject
   semantics.
3. **Identity.** Persona-canonical-form, persona-hash,
   AIP/DID/FTD substrate byte-stable.
4. **Operational metadata.** §4 ENV-flag substrate is opt-in
   by default-by-welle-state (§4.4). A v0.3-era operator who
   sets none of the `WAKIR_PE_*_BACKEND` flags is conformant.
5. **Publish-mode.** §6 contract reaffirms v0.2.1 §13; a v0.3
   producer that already honours v0.2.1 §13 is v0.4-conformant.

A v0.4 producer that emits frames stamped `wirelangversion:
0.4.0` MAY do so once its integration tests pass against a v0.4
verifier; there is no on-the-wire behaviour change. There is no
requirement to upgrade the `wirelangversion` stamp.

### 9.3 Migration sequence v0.3 → v0.4 (recommended)

1. **Verifier upgrade.** Verifiers add `0.4.0` to the
   `wirelangversion` whitelist; no schema change.
2. **Producer upgrade (optional).** Producers MAY bump
   `wirelangversion` to `0.4.0` once their integration tests
   pass.
3. **Operator upgrade (recommended).** Operators read §4 and
   §5; capture the welle-state of each component in the local
   Quadlet substrate; pin `WAKIR_PE_*_BACKEND` defaults to the
   welle-state contract (§4.4).
4. **Audit upgrade (recommended).** Re-run the
   `nats-jetstream-subjects-audit` workflow against the
   operator's downstream fork to confirm zero `UNCLASSIFIED`
   findings.
5. **Documentation.** Update internal integration docs to
   reference `specs/wirelang-spec-v0-4.md` rather than per-Tag
   memos. Mark `specs/wirelang-spec-v0-2.md` and
   `specs/wirelang-spec-v0-3.md` (if present) as
   `replaced-by: 0.4.0` in their frontmatter.

There is no requirement to upgrade. v0.3 frames remain valid
against v0.4 verifiers indefinitely; v0.3 operators who do not
participate in the Phase-3c cutover (e.g., downstream forks
that retain the Python engine) remain conformant.

### 9.4 Asymmetric per-component rollback path

v0.4 makes a normative commitment to **per-component rollback
without spec re-issue**. If a Phase-3c welle requires an
asymmetric single-component rollback (DW-AC-3 / HC-AC-2 trigger):

- The operator flips the offending component's
  `WAKIR_PE_*_BACKEND` from `rust` (or `parity`) to `python`.
- The other components remain on their post-welle-acceptance
  default.
- The spec is **not** re-issued. The rollback is operational
  metadata at the ENV-flag level (§4.2 / §4.3), not a spec
  change.

This is the substrate that makes the Phase-3c cutover
**reversible at the component granularity** without breaking
the spec contract. A v0.4-conformant operator can run a mixed-
backend system (e.g., six Rust components + one Python
component) and remain spec-conformant; the spec does not
require all-Rust or all-Python.

## 10. Cross-review-zone integration (Phase-3 update)

The three cross-review zones from ADR-0009 had Phase-1a
closure status documented in v0.2 §9. The Phase-3 update:

| Zone | v0.2 status | v0.4 status |
|---|---|---|
| Zone 1 — Identity-Substrate | Consensus reached; markers A1/B2/C1/D2. | Re-confirmed at Phase-3a-Rust-rewrite-trigger; the byte-stability contract (§3.2) is the Phase-3 operationalisation of the consensus. |
| Zone 2 — WAT × Wirelang Frame integration | Consensus reached on four-tuple leaf projection. | Re-confirmed; `persona-engine-anchor-emitter` (Phase-3a foundation crate #15) is the Rust-side implementation of the consensus. |
| Zone 3 — OTS-Schema-Anchor | Anchor format documented at Layer 2; consensus stamp pending. | Closure deferred — not Phase-3-trigger-relevant. v0.4 does not depend on the marker for validation. Re-evaluation at Phase-3-Closeout. |

## 11. Brand-Guide §9 compliance

This document uses only role-strings (`Dev-Engineering-2 / Wirelang`,
`Persona-Engine-Engineer`, `QA`, `Internal Audit`, `CTO`, `CEO`,
`Federation-Substrate-Ops`, `treasury-issuer`, etc.). The single
clear-name appearances are in the historical decision-doc
references (`docs/decisions/rust-rewrite-crate-wahlen.md` authored
by Reza Tehrani; `docs/decisions/persona-engine-rust-rewrite-roadmap.md`
authored by Selin Çelik) — these references are to file-author
metadata, not to in-spec actor identity, and are retained for
audit-traceability.

All v0.4 examples and the schema references are inherited from
the per-layer specs and have been checked against
`projects/comms/brand-guide.md` §9 at v0.4 publication.

## 12. References

### 12.1 Wakir specs (this module)

- `specs/wirelang-spec-v0-2.md` — predecessor; §13 (Layer-0
  Subscribe-Mode contract) is re-stated and anchored in §6.
- `specs/layer-0-2-overview.md` — Layer-0–2 walkthrough.
- `specs/layer-3-capability-token.md` — Layer-3 trust concerns.
- `specs/datalog-caveat-vocabulary.md` — vocabulary v0.1.
- `specs/datalog-caveat-vocabulary-phase-2.md` — Phase-2 vocabulary.
- `specs/identity-substrate.md` — persona substrate.
- `specs/nats-subject-mapping-v1.md` — Layer-0 subject naming.
- `specs/schema-registry-spec.md` — schema registry NATS-KV
  backend (Sprint-7 Pfad-B).
- `specs/wat-leaf-projection.md` — Layer-4 hand-off contract.
- `specs/bridge-forward-pipe-v1.md` — Bug-42-fix-anchor
  reference (§6).
- `specs/wirelang-tv-strategy.md` — TV-W-1/2/3 substrate.

### 12.2 Phase-3 substrate (this module)

- `wirelang-rust/crates/persona-*/` — the 15 Phase-3a-foundation
  crates and the 17 tooling/companion crates (§3).
- `docs/decisions/persona-engine-rust-rewrite-roadmap.md` —
  Selin-Roadmap (Sprint-Pengine-13 strategy).
- `docs/decisions/rust-rewrite-crate-wahlen.md` — Reza-Crate-
  Wahlen (ADR-0063 §Folgeartefakte 1).
- `docs/quality-gates/phase-3c-acceptance-criteria.md` — per-
  welle AC-1…AC-5 + DW-AC-1…DW-AC-5 + WE-1…WE-4 +
  HC-AC-2 contracts.
- `docs/quality-gates/phase-3c-doppel-welle-4-5.md`,
  `docs/quality-gates/phase-3c-doppel-welle-6-7.md` — doppel-
  welle Cross-Modul-Drift contracts.
- `docs/phase-3c/welle-N-*-runbook.md`,
  `docs/phase-3c/welle-N-cutover-smoke.md` — per-welle operator
  artefacts (§5.2 element 1 + 2).
- `docs/audit/nats-jetstream-subjects-audit.md` — §8 audit
  substrate.
- `reports/audit/2026-05-18-nats-jetstream-subjects-audit.md` —
  §8 baseline report.

### 12.3 ADR substrate

- ADR-0009 — Cross-Review-Zone Setup.
- ADR-0023a / ADR-0023b — Phase-1a/b spec boundary.
- ADR-0035 — Sprache-pro-Komponente (Rust Hot-Path).
- ADR-0058 — Phase-3 framework.
- ADR-0063 — Phase-3-Trigger (Option A) approved 2026-05-16.
- ADR-0065 — Phase-3c-Per-Welle-Verifikations-Plan.
- ADR-0066 — Doppel-Welle-Beschleunigung (4 Wochen statt 7).

### 12.4 IETF / external references

- RFC 2119 / RFC 8174 — conformance keywords.
- RFC 8785 — JSON Canonicalization Scheme (JCS).
- CloudEvents 1.0 — wire-envelope format.
- `draft-prakash-aip-00` — AIP document substrate (referenced
  via v0.2.1 §6; v0.4 does not change the reference).
- Biscuit v3 — capability-token language (referenced via v0.2.1
  §6; v0.4 does not change the reference).

## 13. Acknowledgements

The Tag-45 consolidation follows the per-Tag substrate work of
the Sprint-Pengine-13 / Sprint-7 / Phase-3-trigger-window
contributors (role-strings only: Persona-Engine-Engineer,
Dev-Engineering-2 / Wirelang, Federation-Substrate-Ops, QA,
Internal Audit, Observability, CTO, CEO). Per-actor file-author
attribution is preserved in the referenced runbook and quality-
gate documents.

— *role: wirelang-spec-owner*
