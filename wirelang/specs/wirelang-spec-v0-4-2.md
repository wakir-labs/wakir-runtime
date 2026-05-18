<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

---
spec: wirelang
version: 0.4.2
status: draft
supersedes: null
extends: 0.4.1
replaced-by: null
date: 2026-05-19
audience: implementers, integrators, operators, auditors
license: CC-BY-4.0
---

# Wirelang Specification v0.4.2 (Tag-50 DRIFT-S4 Reconciliation Patch)

This document is an **additive patch** over v0.4.1 (Tag-48 PR #308).
It reconciles drift item **DRIFT-S4** raised against PR #314
(Tag-49 federation-resolver cross-lang-pin refresh suite) between
the spec §4.1 ENV-flag schema (nine components named
`WAKIR_PE_*_BACKEND`) and the Pin-Pack reality
(`infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml`) which
wires **ten** boot records under a `WAKIR_*_BACKEND` namespace
(no `_PE_` infix), with `persona-engine-federation-resolver` at
record #9 and `persona-engine-bridge-audit-writer` at record #10.

> **v0.4.2 (2026-05-19, Tag-50):** Additive patch over v0.4.1.
> **No on-the-wire change. No frame-attribute change. No caveat-
> predicate addition or removal. No publish-mode-contract change.
> No §3.1 catalogue change.** The change surface is §4.1 alone —
> ENV-flag table and one footnote — plus a backward-compatibility
> note (§5) and a manifest-doc consistency entry (§6).
>
> Every v0.4.1 frame, producer, verifier, operator, and runtime
> backend remains valid under v0.4.2 without modification.
> v0.4.2 verifiers MUST accept `wirelangversion: 0.4.0` /
> `0.4.1` frames without rewrite. v0.4.0 / v0.4.1 verifiers MAY
> treat `wirelangversion: 0.4.2` frames as v0.4.0 frames (the
> spec change is documentation-level, not wire-level).

It is published as a separate file (`wirelang-spec-v0-4-2.md`)
rather than as an edit to `wirelang-spec-v0-4-1.md` for the same
two reasons that motivated the v0.4.0 → v0.4.1 split:

1. **Patch-trace integrity.** The Tag-49 PR #314 federation-resolver
   cross-lang-pin refresh suite cites v0.4.1 §4.1 verbatim by
   regression-pin. Rewriting v0.4.1 in place would break the
   pin-trail.
2. **Spec-as-code discipline.** Wirelang carries semver-like
   versioning (§1.1 in v0.4.0). v0.4.0 + v0.4.1 + v0.4.2 is the
   patch-trace. A future v0.5 (Phase-3c-close consolidation,
   target ~KW 28) re-folds v0.4 + v0.4.1 + v0.4.2 into a single
   document.

## 1. Scope of v0.4.2

The patch resolves a single drift item.

| Drift ID | Severity | Surface affected | v0.4.2 resolution |
|---|---|---|---|
| DRIFT-S4 | medium | §4.1 ENV-flag-table: nine `WAKIR_PE_*_BACKEND` entries (spec) vs ten `WAKIR_*_BACKEND` entries with federation-resolver at #9 and bridge-audit-writer at #10 (pin-pack-0.5.1-pre-cutover) | §4.1 rewritten to document the Pin-Pack-0.5.1 reality verbatim (ten rows, `WAKIR_*_BACKEND` naming, federation-resolver at row #9, bridge-audit-writer at row #10); `canonical_form` demoted from row to **§4.1 footnote (FN-1)** with explicit "no ENV-flag wired in v0.4.2; Phase-4-Item" wording. |

**Source-of-truth direction (CEO-Triage 2026-05-19, Option C Hybrid v0.4.2):** Pin-Pack-0.5.1-pre-cutover.yaml (the machine-readable
substrate consumed by `cross-substrate-parity-gate.yml` and the
Tag-48 wire-in tests) is the **single source of truth** for the
§4.1 ENV-flag schema. The spec documents the Pin-Pack reality;
where spec and Pin-Pack disagree, the spec is wrong and must be
patched. v0.4.2 is the first such patch.

The patch does **not** modify §3.1 catalogue (sixteen rows,
unchanged from v0.4.1), §3.2 (Identity-Substrate byte-stability),
§3.3 (Foundation crates), §3.4 (Crate ↔ welle mapping), §4.2
(ENV-flag value space), §4.3 (switch atomicity), §4.4 (default-by-
welle-state), §5 (welle inventory), §6 (Bug-42 contract), §7
(canonical wire format), §8 (operator contract), §9 (Phase-3c
cutover), or §10 (Audit conformance).

## 2. Conformance keywords

The keywords MUST, MUST NOT, SHOULD, SHOULD NOT, MAY are used as
in RFC 2119 / RFC 8174 (unchanged from v0.2 §2, v0.4 §2, v0.4.1 §2).

A producer / verifier / operator conformant to v0.4.1 is
conformant to v0.4.2 by construction. No new conformance
obligations are introduced. Operators who have set ENV flags
under the **v0.4.1 names** (`WAKIR_PE_*_BACKEND`) MUST migrate
to the v0.4.2 names (`WAKIR_*_BACKEND`); see §5.6 migration
guidance.

## 3. §3 no change

§3 (Phase-3a Rust foundation, sixteen-row catalogue, Identity-
Substrate contract, Foundation classification, crate ↔ welle
mapping) is unchanged from v0.4.1. The patch scope is §4.1.

## 4. §4.1 patch: ENV-flag schema — the Pin-Pack-0.5.1 reality

### 4.1 The ten Pin-Pack-wired boot records

The v0.4.0 §4.1 / v0.4.1 §4.1 table titled "The nine components"
is **replaced** in v0.4.2 by the following ten-row table titled
"The ten Pin-Pack-wired boot records". The table is reproduced
**verbatim** from `infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml`
§`boot_wired_crates`. Record numbering is the Pin-Pack `record`
attribute (boot fan-out order, not welle order).

| Pin-Pack record # | Component (Pin-Pack `name`) | Selector ENV (`selector_env`) | Binary ENV (`binary_env`) | Python authority module | Phase-3c welle |
|---|---|---|---|---|---|
| 1 | `persona-engine-recovery` | `WAKIR_RECOVERY_BACKEND` | `WAKIR_RUST_RECOVERY_BIN` | `wirelang.persona_engine.recovery_workflow` | Welle 7 |
| 2 | `persona-engine-state-backing` | `WAKIR_STATE_BACKING_BACKEND` | `WAKIR_RUST_STATE_BACKING_BIN` | `wirelang.persona_engine.state_backing` | Welle 4 |
| 3 | `persona-engine-fsm` | `WAKIR_FSM_BACKEND` | `WAKIR_RUST_FSM_BIN` | `wirelang.persona_engine.lifecycle_state_machine` | Welle 5 |
| 4 | `persona-engine-v907-verify` | `WAKIR_V907_VERIFY_BACKEND` | `WAKIR_RUST_V907_VERIFY_BIN` | `wirelang.persona_engine.v907_verify` | Welle 1 |
| 5 | `persona-engine-bridge-diff` | `WAKIR_BRIDGE_DIFF_BACKEND` | `WAKIR_RUST_BRIDGE_DIFF_BIN` | `wirelang.persona_engine.bridge_audit_diff_engine` | Welle 3 (companion) |
| 6 | `persona-engine-subscribe-loop` | `WAKIR_SUBSCRIBE_LOOP_BACKEND` | `WAKIR_RUST_SUBSCRIBE_LOOP_BIN` | `wirelang.persona_engine.subscribe_ack` | Welle 6 |
| 7 | `persona-engine-anchor-emitter` | `WAKIR_ANCHOR_EMITTER_BACKEND` | `WAKIR_RUST_ANCHOR_EMITTER_BIN` | `wirelang.persona_engine.anchor_emitter` | Foundation (off-welle) |
| 8 | `persona-engine-svid-workload-identity` | `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND` | `WAKIR_RUST_SVID_WORKLOAD_IDENTITY_BIN` | `wirelang.persona_engine.svid_workload_identity` | Welle 2 |
| 9 | `persona-engine-federation-resolver` | `WAKIR_FEDERATION_RESOLVER_BACKEND` | `WAKIR_RUST_FEDERATION_RESOLVER_BIN` | `wirelang.identity.federation_resolver_canonical` | Off-Welle (boot fan-out) |
| 10 | `persona-engine-bridge-audit-writer` | `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND` | `WAKIR_RUST_BRIDGE_AUDIT_WRITER_BIN` | `wirelang.persona_engine.bridge_audit_writer` | Welle 3 |

**Naming contract.** The selector ENV namespace is
`WAKIR_<component>_BACKEND` (no `_PE_` infix). The binary ENV
namespace is `WAKIR_RUST_<component>_BIN`. The cross-cutting
timeout ENV is `WAKIR_RUST_BACKEND_TIMEOUT_S` (uniform across
every Rust subprocess; default `30` seconds). These three
namespaces are normative; producers, verifiers, operators, and
Quadlet substrates MUST use exactly these names.

**Anchor-emitter clarification.** Row 7 (`persona-engine-anchor-
emitter`) is wired as a Pin-Pack boot record in 0.5.1-pre-cutover
**and** is classified Foundation in §3.3. The two facts coexist:
the Pin-Pack wires the record so the boot fan-out emits a
deterministic `BackendDecision` for the anchor-emitter (audit
trail completeness — record-count invariant), while §3.3 declares
it off-welle because anchor-emitter is Rust-only-by-inception
(no Python counterpart on the cutover path). The selector
`WAKIR_ANCHOR_EMITTER_BACKEND` accepts the value `rust` and
treats `python` as a no-op alias for `rust` (Pin-Pack-0.5.1
runtime behaviour, codified at MANIFEST §2). v0.4.2 carries this
"accepted-but-unswitchable" behaviour forward from v0.4.0 §4.1
row #9 (which named the same crate but flagged it "not
switchable"); the difference is that in v0.4.2 the crate **does**
have an ENV-flag (per Pin-Pack reality), it just does not
meaningfully switch.

#### Footnote FN-1: `canonical_form` (DRIFT-S4-deferred)

The v0.4.0 §4.1 row #8 (`canonical_form`,
`persona-canonical-form` + `persona-canonical-form-yaml`,
"not switchable", Foundation) is **removed** as a §4.1 row in
v0.4.2. The crates remain in §3.1 (rows #1, #2) and remain
Foundation (§3.3) — those classifications are unchanged. They
are removed from the §4.1 ENV-flag table because:

1. **Pin-Pack-0.5.1 does not wire them.** No record in
   `boot_wired_crates` names `persona-canonical-form` or
   `persona-canonical-form-yaml`; no selector ENV exists for the
   canonical-form substrate; no boot fan-out emits a
   `BackendDecision` for canonical-form. The §4.1 table
   documents Pin-Pack-wired records only (Option-C-Hybrid
   reconciliation principle from §1).
2. **Foundation-circularity (§3.3) precludes a Python switch
   path.** The JCS canonicalisation primitive is the
   parity oracle for every other welle; switching it to a
   Python backend would introduce a circular oracle.
   Pin-Pack-0.5.1 reflects this by not wiring a record.

**No ENV-flag is wired for `canonical_form` in v0.4.2.** A future
v0.5 (Phase-3c-close consolidation, ~KW 28) or a Phase-4 release
may introduce a canonical-form ENV-flag if and only if (a) a
Python re-implementation of `persona-canonical-form` is added as
a parity-shadow (not as a backend swap), and (b) the §3.3
foundation-circularity argument is updated to permit shadow-only
operation. Neither is in scope for Phase-3c. The canonical-form
substrate's byte-stability obligation (§3.2) remains in force
under v0.4.2 — it is enforced by the cross-lang-parity-pin tests,
not by an ENV-flag.

> **Phase-4 item.** The canonical_form ENV-flag question is
> tracked as a v0.5 / Phase-4 open item (§7 carry-forward). It is
> not in v0.4.2 scope.

### 4.2 ENV-flag value space (unchanged scope, renamed flags)

Each selector ENV (`WAKIR_<component>_BACKEND` for the ten
Pin-Pack-wired records in §4.1) takes one of three values:

- `python` — the Python authority module (the `python_authority`
  column in §4.1).
- `rust` — the Rust crate (the Pin-Pack `name` column in §4.1).
- `parity` — both backends run; output is compared and divergence
  is logged and reported to the Bridge-Audit-Writer-Konsistenz-
  Report (AC-1). Used during Beobachtungs-Fenster (§9.2).

For record #7 (`persona-engine-anchor-emitter`), values `python`
and `parity` are accepted but degrade to `rust` (Rust-only-by-
inception; see §4.1 anchor-emitter clarification).

Unset for records #1–#6, #8, #10 (the seven cutover wellen and
the SVID record) is equivalent to `python` prior to the welle-
trigger date and to the welle-default thereafter (§4.4).
Unset for record #7 is `rust`. Unset for record #9 (federation-
resolver) is `rust` — it is boot-fan-out internal and has no
Python authority on the cutover path (see §4.1 row #9 / v0.4.1
§3.1.16).

### 4.3 ENV-flag-switch atomicity (unchanged)

§4.3 (atomicity at component granularity, `systemctl restart`
SLA ≤600 s per HC-AC-2) is unchanged from v0.4.1. The flag names
change (`WAKIR_PE_*_BACKEND` → `WAKIR_*_BACKEND`); the
atomicity contract does not.

### 4.4 Default-by-welle-state (unchanged scope, renamed flags)

§4.4 (default backend per welle state) is unchanged in scope.
The seven welle wellen are now flagged by:

- Welle 1 — `WAKIR_V907_VERIFY_BACKEND` (record #4)
- Welle 2 — `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND` (record #8)
- Welle 3 — `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND` (record #10);
  Welle 3 companions are gated by `WAKIR_BRIDGE_DIFF_BACKEND`
  (record #5) for the diff engine; replay and forward have
  no Pin-Pack-wired ENV-flag (consumed lazily, see Pin-Pack
  `boot_unwired_crates`).
- Welle 4 — `WAKIR_STATE_BACKING_BACKEND` (record #2)
- Welle 5 — `WAKIR_FSM_BACKEND` (record #3)
- Welle 6 — `WAKIR_SUBSCRIBE_LOOP_BACKEND` (record #6)
- Welle 7 — `WAKIR_RECOVERY_BACKEND` (record #1)

The Quadlet-Default-ENV-Flags substrate (WE-2) is the operational
implementation of this contract: at Welle-7-acceptance, all seven
flags are pinned to `rust` in the Quadlet defaults. The Tag-49
acceptance test `test_welle_7_we_2_quadlet_all_seven_rust` will
be re-pointed at the v0.4.2 names in a follow-up sweep.

## 5. Backward-compatibility note (v0.4.1 → v0.4.2)

### 5.1 Wire format

No change. Every v0.4.1 frame is a valid v0.4.2 frame.
`wirelangversion: 0.4.0` is the wire-attribute value emitted by
v0.4.1 and v0.4.2 producers (the patch-trace versions are
documentation, not wire).

### 5.2 Frame attributes

No change. v0.4.2 introduces no frame-attribute additions or
deletions.

### 5.3 Caveat predicates

No change. v0.4.2 introduces no caveat-predicate additions,
deletions, or semantic changes.

### 5.4 Schema documents

No change. `schemas/layer-0-transport.json`,
`schemas/layer-1-wire.json`, `schemas/layer-2-semantic.json`,
`schemas/layer-3-capability-token.json`, `schemas/aip-document.json`,
`schemas/datalog-caveat.json` are unchanged. Validators that pass
v0.4.1 continue to pass v0.4.2.

### 5.5 Audit baseline

The Tag-47 audit
(`reports/audit/phase-3a-15-crate-consistency-2026-05-19.md`)
cited v0.4.0 §3.1 verbatim. v0.4.1 reconciled DRIFT-S1/S2/S3
(catalogue scope); v0.4.2 reconciles DRIFT-S4 (ENV-flag scope).
None of the four reconciliations invalidate the Tag-47 audit —
they extend the spec to match the substrate the audit cited
indirectly (the pin-pack and the manifest). A future Tag-N audit
will pin against v0.4.2 §4.1 (ten rows, `WAKIR_*_BACKEND`
naming) and will record zero drift on DRIFT-S1, DRIFT-S2,
DRIFT-S3, DRIFT-S4.

### 5.6 Operator migration guidance (ENV-flag names)

Operators with Quadlet substrates or shell environments that set
ENV flags under the **v0.4.0 / v0.4.1 names** (`WAKIR_PE_*_BACKEND`)
MUST migrate to the v0.4.2 names (`WAKIR_*_BACKEND`). The mapping
is mechanical:

| v0.4.0 / v0.4.1 name (deprecated) | v0.4.2 name (canonical) |
|---|---|
| `WAKIR_PE_V907_BACKEND` | `WAKIR_V907_VERIFY_BACKEND` |
| `WAKIR_PE_SVID_BACKEND` | `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND` |
| `WAKIR_PE_BRIDGE_AUDIT_BACKEND` | `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND` (writer); `WAKIR_BRIDGE_DIFF_BACKEND` (diff companion); replay + forward have no wired flag |
| `WAKIR_PE_STATE_BACKING_BACKEND` | `WAKIR_STATE_BACKING_BACKEND` |
| `WAKIR_PE_FSM_BACKEND` | `WAKIR_FSM_BACKEND` |
| `WAKIR_PE_SUBSCRIBE_LOOP_BACKEND` | `WAKIR_SUBSCRIBE_LOOP_BACKEND` |
| `WAKIR_PE_RECOVERY_BACKEND` | `WAKIR_RECOVERY_BACKEND` |
| `WAKIR_PE_ANCHOR_EMITTER_BACKEND` (informally; never normative) | `WAKIR_ANCHOR_EMITTER_BACKEND` |
| `WAKIR_PE_CANONICAL_FORM_BACKEND` (never wired) | (removed; see §4.1 FN-1) |

The Pin-Pack-0.5.1 substrate already uses the v0.4.2 names —
operators following Pin-Pack since Tag-48 have nothing to migrate.
The migration affects only documentation, runbooks, and any
operator-local Quadlet drop-ins that pre-date Pin-Pack-0.5.1.

### 5.7 Foundation-circularity argument

No change. The §3.3 reasoning (parity-oracle-circularity for the
JCS canonicalisation primitive) is preserved and is the
substantive reason `canonical_form` carries no ENV-flag in v0.4.2
(§4.1 FN-1).

## 6. Manifest-doc consistency entry

`wirelang/persona_engine/MANIFEST-0.5.1-pre-cutover.md` §2 ("ENV-Flag
Schema (Consistent `WAKIR_*_BACKEND` Naming)") is already
consistent with v0.4.2 §4.1 by construction (the manifest was
authored against the Pin-Pack reality). No manifest edit is
required for v0.4.2.

A new docstring-level cross-reference is added to the manifest
top-of-file note in a companion commit:

> **Spec cross-reference.** This manifest's §2 ENV-flag schema
> is the authoritative companion to `wirelang-spec-v0-4-2.md`
> §4.1. The two surfaces are kept consistent by the
> hermetic test suite `tests/specs/test_wirelang_spec_v0_4_2_drift_s4_reconciliation.py`
> (Tag-50).

This is a doc-only addition (no behavioural change). The
companion commit is in the same PR as this spec.

## 7. Open items (carried to v0.5 / Phase-4)

The following items are **not** resolved in v0.4.2. They are
carried to a future v0.5 (Phase-3c-close consolidation, ~KW 28)
or a Phase-4 release:

- **`canonical_form` ENV-flag (Phase-4-Item).** §4.1 FN-1 defers
  the canonical_form ENV-flag question to v0.5 / Phase-4. The
  prerequisites (Python re-implementation as a parity-shadow;
  §3.3 amendment to permit shadow-only operation) are not in
  Phase-3c scope.
- **Replay and forward companion ENV-flags.**
  `persona-engine-bridge-audit-replay` and
  `persona-engine-bridge-forward` are Pin-Pack-unwired
  (`boot_unwired_crates`) and therefore carry no §4.1 ENV-flag
  in v0.4.2. If a future Phase-3c-close decision wires them, the
  spec patches §4.1 in a v0.4.3 additive patch (or absorbs them
  into v0.5).
- **Welle-0 (boot fan-out) classification.** Carried forward
  from v0.4.1 §6 unchanged. v0.5 may formalise a Welle-0 tier
  to group records #7 and #9 (off-welle, Rust-only-by-inception).
- **Parity-oracle formalisation for the three Tooling/cross-lang-
  parity-pinned crates.** Carried forward from v0.4.1 §6
  unchanged.
- **Audit-spec-trace re-pin discipline.** Carried forward from
  v0.4.1 §6 unchanged. The Tag-50 hermetic suite
  (`tests/specs/test_wirelang_spec_v0_4_2_drift_s4_reconciliation.py`)
  pins v0.4.2 §4.1 against the working-copy Pin-Pack-0.5.1; a
  future audit-update spawn re-pins audit citations against
  v0.4.2.

None of these items blocks Phase-3c-Trigger (~KW 27) or the
Phase-3c per-welle cutover.

## 8. Verification

A static-pass verifier of v0.4.2 §4.1 (ten-row catalogue) against
the working-copy substrate at Tag-50 main-tip must produce:

- 10/10 §4.1 rows match the `record` ordering in
  `infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml`
  `boot_wired_crates`.
- 10/10 §4.1 `Pin-Pack name` cell values match the Pin-Pack
  `name` field byte-for-byte.
- 10/10 §4.1 `selector_env` cell values match the Pin-Pack
  `selector_env` field byte-for-byte and follow the
  `WAKIR_<component>_BACKEND` naming contract (no `_PE_` infix).
- 10/10 §4.1 `binary_env` cell values match the Pin-Pack
  `binary_env` field byte-for-byte and follow the
  `WAKIR_RUST_<component>_BIN` naming contract.
- 10/10 §4.1 `python_authority` cell values match the Pin-Pack
  `python_authority` field byte-for-byte.
- The string `WAKIR_PE_` does **not** appear in §4.1 (it appears
  only in §5.6 migration guidance, where it is enclosed in the
  deprecated-name table).
- The string `canonical_form` appears in §4.1 only inside FN-1
  (no row carries it).
- §3 (catalogue) is byte-identical to v0.4.1 §3 (no
  catalogue-side drift introduced).
- Frontmatter declares `version: 0.4.2` and `extends: 0.4.1`.

The hermetic test suite that accompanies this spec
(`tests/specs/test_wirelang_spec_v0_4_2_drift_s4_reconciliation.py`,
ten or more tests, Tag-50) enforces these invariants statically
(no NATS, no engine boot, no Rust build, no network import).

## 9. Citation pointers

- Tag-49 PR #314 (DRIFT-S4 origin):
  `tests/specs/test_wirelang_spec_v0_4_1_federation_resolver_cross_lang_pin_refresh.py`.
- v0.4.1 spec being extended:
  `wirelang/specs/wirelang-spec-v0-4-1.md` (Tag-48 PR #308).
- v0.4.0 spec (root of the v0.4 patch-trace):
  `wirelang/specs/wirelang-spec-v0-4.md` (Tag-45 PR #291).
- Pin-Pack substrate (source-of-truth for §4.1):
  `infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml`.
- Boot manifest:
  `wirelang/persona_engine/MANIFEST-0.5.1-pre-cutover.md` §2.
- Welle path canonical:
  `docs/quality-gates/phase-3c-acceptance-criteria.md`.
- Tag-47 audit (catalogue-side drift origin):
  `reports/audit/phase-3a-15-crate-consistency-2026-05-19.md`.

— Reza
