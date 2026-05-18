<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

---
spec: wirelang
version: 0.4.1
status: draft
supersedes: null
extends: 0.4.0
replaced-by: null
date: 2026-05-19
audience: implementers, integrators, operators, auditors
license: CC-BY-4.0
---

# Wirelang Specification v0.4.1 (Tag-47 Drift Reconciliation Patch)

This document is an **additive patch** over v0.4 (Tag-45 PR #291).
It reconciles the three drift items recorded in the Tag-47 15-Crate
Consistency Audit (PR #305,
`reports/audit/phase-3a-15-crate-consistency-2026-05-19.md`)
between the spec §3.1 crate catalogue, the pin-pack substrate
(`infra/persona-engine/pin-pack-0.5.0-pre-cutover.yaml`), and the
boot manifest (`wirelang/persona_engine/MANIFEST-0.5.0-pre-cutover.md`).

> **v0.4.1 (2026-05-19, Tag-48):** Additive patch over v0.4.0.
> No on-the-wire change. No frame-attribute change. No caveat-
> predicate addition or removal. No ENV-flag-schema change. No
> publish-mode-contract change. The change surface is the §3.1
> Phase-3a-Substrate-Klassifikation table and three accompanying
> classification clarifications.
>
> Every v0.4.0 frame, producer, verifier, operator, and runtime
> backend remains valid under v0.4.1 without modification.
> v0.4.1 verifiers MUST accept `wirelangversion: 0.4.0` frames
> without rewrite. v0.4.0 verifiers MAY treat `wirelangversion:
> 0.4.1` frames as v0.4.0 frames (the spec changes are
> documentation-level, not wire-level).

It is published as a separate file (`wirelang-spec-v0-4-1.md`)
rather than as an edit to `wirelang-spec-v0-4.md` for two reasons:

1. **Patch-trace integrity.** The Tag-47 audit references
   v0.4.0 §3.1 verbatim. Rewriting v0.4.0 in place would break
   the audit's citation trail and the regression-pin in
   `tests/audit/test_phase_3a_15_crate_consistency.py`.
2. **Spec-as-code discipline.** Wirelang carries semver-like
   versioning (§1.1 in v0.4.0). v0.4.0 + v0.4.1 is the
   patch-trace. A future v0.5 (Phase-3c-close consolidation,
   ~KW 28) re-folds v0.4 + v0.4.1 into a single document.

## 1. Scope of v0.4.1

The patch resolves three drift items identified in
`reports/audit/phase-3a-15-crate-consistency-2026-05-19.md`
§2 (headline finding) and §4 (symmetric difference).

| Drift ID | Severity | Surface affected | v0.4.1 resolution |
|---|---|---|---|
| DRIFT-S1 | medium | `persona-engine-federation-resolver` classified "tooling" in spec §3.1 but wired record 9 in pin-pack | §3.1 catalogue extended by row 16; spec §3.1 acknowledges federation-resolver as a wired boot-record |
| DRIFT-S2 | low | `persona-engine-recovery-replay` companion-vs-row collision in pin-pack ↔ spec | §3.1 row 14 footnote clarifies the companion-substrate sharing semantic |
| DRIFT-S3 | informational | Three pin-pack unwired crates (`-anchor-submit-worker`, `-federation-frame-parser`, `-frontmatter-parser`) classified "tooling" in spec but pin-pack-pinned | §3 classification-clarification footnote separates "tooling/CI-internal" from "tooling/cross-lang-parity-pinned" |

The patch does **not** modify §3.2 (Identity-Substrate-byte-
stability contract), §3.3 (Foundation crates), §3.4 (Crate ↔
welle mapping). The Welle column for the new row 16 is
**explicitly not on the Phase-3c-welle path**; see §3.1.16 below.

## 2. Conformance keywords

The keywords MUST, MUST NOT, SHOULD, SHOULD NOT, MAY are used as
in RFC 2119 / RFC 8174 (unchanged from v0.2 §2, v0.4 §2).

A producer / verifier / operator conformant to v0.4.0 is
conformant to v0.4.1 by construction. No new conformance
obligations are introduced.

## 3. §3 patches (Phase-3a Rust foundation: the 15 Rust crates)

### 3.1 Patch: catalogue extension (DRIFT-S1, DRIFT-S3)

The v0.4.0 §3.1 catalogue (fifteen rows) is **extended by one
row (row 16)** in v0.4.1. The fifteen-row substrate is preserved
as the Phase-3c-welle-target catalogue; row 16 documents a wired
boot-record that is **outside the Phase-3c-welle path** by spec
intent.

The v0.4.1 §3.1 catalogue (sixteen rows) is:

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
| 14 | `persona-engine-recovery-replay` | Recovery-replay substrate (Welle-7 companion; see §3.1.14 footnote) | Welle 7 (companion) | Cross-modul orchestration |
| 15 | `persona-engine-anchor-emitter` | WAT-anchor emission substrate (Layer-4 hand-off) | Foundation | WAT-Wirelang-boundary |
| **16** | **`persona-engine-federation-resolver`** | **Wired boot-record (cold-start fan-out); not on cutover path** | **Off-Welle (boot)** | **Boot-fan-out, Rust-only by inception** |

#### 3.1.14 Footnote: recovery-replay companion-vs-row clarification (DRIFT-S2)

`persona-engine-recovery-replay` (row 14) is the **deterministic
replay companion** to `persona-engine-recovery` (row 13). The two
crates form one welle (Welle 7) and one cutover unit. Their
ENV-flag is shared (`WAKIR_PE_RECOVERY_BACKEND`, §4.1 row 7).

The pin-pack substrate
(`infra/persona-engine/pin-pack-0.5.0-pre-cutover.yaml`) treats
recovery-replay as a **companion of `persona-engine-recovery`**:
both crates share

- the cross-lang fixture directory
  `tests/fixtures/recovery-workflow-cross-lang/`, and
- the cross-lang parity test
  `wirelang/tests/persona_engine/test_recovery_workflow_cross_lang_parity.py`.

The pin-pack pins `persona-engine-recovery` as boot-wired record 1;
`persona-engine-recovery-replay` is implicitly co-pinned via the
companion-row sharing. This is intentional: the replay substrate's
oracle is the same canonical-form recovery workflow that record 1
exercises, so a separate pin would introduce a circular oracle
(see §3.3 foundation-circularity argument).

Verifiers and auditors MUST treat row 13 + row 14 as one
substrate unit. The Tag-47 audit's `companion` notation in the
per-crate substrate check (audit §5 row 14) is the canonical
expression of this contract.

#### 3.1.16 New row: `persona-engine-federation-resolver` (DRIFT-S1)

`persona-engine-federation-resolver` is the **federation-route
resolver** that the persona-engine cold-start fan-out invokes
to seed the NATS-KV-backed federation route table (per
`docs/orchestrator-nats-kv-phase-1-runbook.md` I-3, Sprint-2
Tag-3, commit `7d5580f`). It is record 9 of the nine wired
boot-records in `MANIFEST-0.5.0-pre-cutover.md` §1.

It is added to v0.4.1 §3.1 as row 16 with the following
classification:

- **Phase-3-role:** Wired boot-record (cold-start fan-out;
  emits a BackendDecision on every cold-start).
- **Welle:** Off-Welle (boot). It is **not** on the Phase-3c
  per-welle cutover path (§9) because it is Rust-only by
  inception — there is no Python counterpart that the §8
  ENV-flag substrate could switch to.
- **Substrat-Klassifikation:** Boot-fan-out, Rust-only.

The substrate it operates on (NATS-KV federation route table)
**is** subject to the Phase-3c subscribe-loop welle (Welle 6,
row 12); the resolver itself is not. Operators MUST NOT flip an
ENV-flag for federation-resolver — there is no such ENV-flag
(consistent with §3.3 foundation-treatment).

The row is added to §3.1 (not §3 "remaining seventeen") because:

1. It is a wired boot-record per manifest §1. Boot-records are
   the operationally-visible substrate of the engine and belong
   in the §3.1 catalogue.
2. The Tag-47 audit identified the §3.1 / pin-pack symmetric
   difference, of which federation-resolver was the substantive
   item (audit §4.3).

The seventeen-crate "remaining tooling" sub-population mentioned
in v0.4.0 §3.1 prose is correspondingly **reduced by one** in
v0.4.1 (the tooling sub-population becomes sixteen, the foundation
sub-population becomes sixteen, the workspace total stays 32).

### 3.2 No change

§3.2 (Identity-Substrate-byte-stability contract) is unchanged.
The four identity-substrate-kritische crates (#1, #2, #3, #4)
remain the byte-stability anchors. Row 16 is **not**
identity-substrate-kritisch.

### 3.3 No change

§3.3 (Foundation crates) is unchanged. Crates #1, #2, #15 remain
the Foundation set. Row 16 (`persona-engine-federation-resolver`)
is **not** added to the Foundation set, because the Foundation
classification implies "no Python counterpart by parity-oracle-
circularity argument". Row 16's Rust-only status is for a
different reason: it is a boot-fan-out internal whose substrate
(NATS-KV route table) **has** a parity oracle elsewhere (via
the subscribe-loop welle, row 12).

### 3.4 No change

§3.4 (Crate ↔ welle mapping is normative) is unchanged. Row 16
documents "Off-Welle (boot)" in its Welle column; the §3.4 MUST-
NOT-flip rule does not apply because there is no ENV-flag to
flip for row 16.

## 4. §3 prose patch: unwired-crates classification clarification (DRIFT-S3)

The v0.4.0 §3.1 prose paragraph beginning "The remaining seventeen
crates in the workspace…" is amended in v0.4.1 to split the
tooling sub-population into two operationally-distinct subclasses:

> **v0.4.1 amended text:** The remaining **sixteen** crates in
> the workspace (`persona-cli`, `persona-converter`,
> `persona-engine-smoke`, `persona-migration*`,
> `persona-pilot-export`, `persona-validator`,
> `persona-engine-format`, `persona-engine-loop-latency-bench`,
> `persona-engine-v907-recompute-bench`,
> `persona-engine-nats-subjects`,
> `persona-engine-integration-tests`,
> `persona-engine-migrate-version`, and the three pin-pack-pinned
> parity-substrate crates `persona-engine-anchor-submit-worker`,
> `persona-engine-federation-frame-parser`,
> `persona-engine-frontmatter-parser`) divide into **two
> tooling subclasses**:
>
> - **Tooling/CI-internal (13 crates):** ship as Rust-only from
>   inception or are CI-internal. They are **not** in the pin-pack
>   substrate. Examples: `persona-cli`, `persona-validator`,
>   `persona-engine-smoke`, the bench crates, the migration crates.
> - **Tooling/cross-lang-parity-pinned (3 crates):**
>   `persona-engine-anchor-submit-worker`,
>   `persona-engine-federation-frame-parser`,
>   `persona-engine-frontmatter-parser`. They have Python
>   counterparts, cross-lang fixtures, and cross-lang parity
>   tests. They appear in the pin-pack substrate as **unwired**
>   records (no boot fan-out commitment), and they are pinned at
>   pin-pack-version-cutover to prevent silent Rust/Python drift
>   on the parity oracle. They are **not** on the §9 Phase-3c
>   welle path because they are not user-visible runtime
>   components — they are oracles and parsers invoked by
>   higher-layer wired records.
>
> The two subclasses together form the sixteen-crate tooling
> sub-population. The sixteen-crate Phase-3a-foundation
> sub-population (§3.1 catalogue) plus the sixteen-crate tooling
> sub-population sums to 32 = the workspace total at Tag-48.

This clarification removes the v0.4.0 wording ambiguity
identified in the audit §4.3 ("classification drift" for the
three unwired-but-pinned crates).

## 5. Backward-compatibility note (v0.4.0 → v0.4.1)

### 5.1 Wire format

No change. Every v0.4.0 frame is a valid v0.4.1 frame.
`wirelangversion: 0.4.0` is the wire-attribute value emitted by
v0.4.1 producers as well (v0.4.1 is a documentation patch, not
a wire patch; producers SHOULD NOT bump the wire-attribute to
`0.4.1` because there is no on-the-wire distinction to encode).

### 5.2 ENV-flag schema

No change. The nine engine components in v0.4.0 §4.1 remain
nine engine components in v0.4.1. Row 16 of §3.1
(federation-resolver) is **not** a tenth ENV-flag-component
because it is Rust-only-by-inception and has no Python
counterpart to switch to.

### 5.3 Schema documents

No change. `schemas/layer-0-transport.json`,
`schemas/layer-1-wire.json`, `schemas/layer-2-semantic.json`,
`schemas/layer-3-capability-token.json`, `schemas/aip-document.json`,
`schemas/datalog-caveat.json` are unchanged. Validators that pass
v0.4.0 continue to pass v0.4.1.

### 5.4 Audit baseline

The Tag-47 audit (`reports/audit/phase-3a-15-crate-consistency-
2026-05-19.md`) cited v0.4.0 §3.1 verbatim. v0.4.1 reconciles
the three drift items the audit recorded, but does **not**
invalidate the audit. A future Tag-N audit re-run will pin
against v0.4.1 §3.1 (sixteen rows) and will record zero drift
on DRIFT-S1, DRIFT-S2, DRIFT-S3.

The regression-pin in
`tests/audit/test_phase_3a_15_crate_consistency.py` continues to
pin against v0.4.0 §3.1's fifteen-row catalogue at Tag-48; a
follow-up audit-update spawn will re-pin against v0.4.1's
sixteen-row catalogue once the spec is merged. This is the
audit-spec-trace discipline (audit cites a frozen spec version;
spec updates do not retroactively re-pin closed audits).

### 5.5 Foundation-circularity argument

No change. The §3.3 reasoning (parity-oracle-circularity for the
JCS canonicalisation primitive) is preserved. Row 16
(federation-resolver) is Rust-only for a different reason
(operational scope, not oracle scope), and is therefore
classified Off-Welle rather than Foundation.

## 6. Open items (carried to v0.5)

The following items are noted but **not** resolved in v0.4.1.
They are carried forward to a future v0.5 (Phase-3c-close
consolidation, target ~KW 28):

- **Welle column for row 16.** v0.4.1 records "Off-Welle (boot)"
  as the Welle classification for federation-resolver. A future
  spec may introduce a Welle-0 ("boot fan-out") classification
  that groups Off-Welle Rust-only-by-inception boot-records into
  a named tier. This is a presentation concern, not a contract
  concern, and is deferred.
- **Parity oracle for `persona-engine-anchor-submit-worker`,
  `persona-engine-federation-frame-parser`,
  `persona-engine-frontmatter-parser`.** v0.4.1 §4 classifies
  them as "Tooling/cross-lang-parity-pinned" but does not
  formalise the parity contract (the byte-stability requirement
  per §3.2 is currently the operational anchor). A future spec
  may formalise a "parity-pinned tooling" sub-tier with explicit
  byte-stability obligations.
- **Audit-spec-trace re-pin discipline.** The regression-pin in
  `tests/audit/test_phase_3a_15_crate_consistency.py` requires a
  protocol for "audit re-pins against a newer spec version". v0.5
  may codify this as part of §10 (Audit conformance).

These items are documentation-quality concerns. None of them
blocks Phase-3c-Trigger (~KW 27) or the Phase-3c per-welle
cutover.

## 7. Verification

A static-pass verifier of v0.4.1 §3.1 (sixteen-row catalogue)
against the working-copy substrate at Tag-48 main-tip must
produce:

- 16/16 spec §3.1 crates exist in `wirelang-rust/crates/`.
- 14/16 have Python siblings (Foundation rows #1, #2, #15 and
  Off-Welle row #16 are Rust-only).
  - Specifically: #1 has a Py sibling
    (`wirelang/persona/persona_canonical_form.py`); #2 and #15
    do not. Net: 13 Py siblings across rows #1–#15.
  - Row #16 has no Py sibling (Rust-only-by-inception).
  - Across all sixteen rows: 13 Py siblings, 3 Foundation-no-Py
    (#2, #15 — and one of #1 depending on whether the
    `wirelang/persona/persona_canonical_form.py` substrate is
    counted; see audit §5 row 1), and 1 Off-Welle-no-Py (#16).
  - The contract is: every row where Welle ≠ Foundation and
    Welle ≠ Off-Welle has a Py sibling. This evaluates to
    **12 rows** (#3, #4, #5, #6, #7, #8, #9, #10, #11, #12,
    #13, #14), of which all 12 have Py siblings per audit §5.
- 12/16 have cross-lang fixture directories. Same scope as above.
- 12/16 have cross-lang parity tests. Same scope as above.
- 16/16 have non-trivial source (LoC floor 100 holds across all
  rows; federation-resolver's source resides under
  `wirelang-rust/crates/persona-engine-federation-resolver/src/`).
- 32 workspace crates = 16 (v0.4.1 §3.1) + 16 (v0.4.1 §4 tooling
  sub-population). The sixteen-plus-sixteen partition recovers
  the v0.4.0 fifteen-plus-seventeen partition by moving
  federation-resolver from "tooling" to "§3.1 catalogue".

The hermetic test suite that accompanies this spec
(`tests/specs/test_wirelang_spec_v0_4_1_drift_reconciliation.py`)
enforces these invariants statically (no NATS, no engine boot,
no Rust build, no network import).

## 8. Citation pointers

- Tag-47 audit report:
  `reports/audit/phase-3a-15-crate-consistency-2026-05-19.md`
  (PR #305, baseline `7ada5ab`).
- v0.4.0 spec being extended:
  `wirelang/specs/wirelang-spec-v0-4.md` (Tag-45 PR #291).
- Pin-pack substrate:
  `infra/persona-engine/pin-pack-0.5.0-pre-cutover.yaml`.
- Boot manifest:
  `wirelang/persona_engine/MANIFEST-0.5.0-pre-cutover.md` §1.
- Welle path canonical:
  `docs/quality-gates/phase-3c-acceptance-criteria.md`.

— Reza
