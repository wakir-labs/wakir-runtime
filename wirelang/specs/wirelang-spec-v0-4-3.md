<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

---
spec: wirelang
version: 0.4.3
status: pre-cutover-freeze
supersedes: null
extends: 0.4.2
replaced-by: null
date: 2026-05-19
audience: implementers, integrators, operators, auditors
license: CC-BY-4.0
freeze-marker: kw-24-cutover-gate
freeze-anchor: persona-engine-0.5.2-final-pre-cutover
---

# Wirelang Specification v0.4.3 (Tag-53 Pre-Cutover-Freeze-Marker)

This document is a **status-only freeze-marker** over v0.4.2 (Tag-50
PR #320). It introduces **no substance diff** to v0.4.2: the on-the-
wire format, frame attributes, caveat predicates, publish-mode
contract, §3 catalogue, §4 ENV-flag schema, §5 welle inventory,
§6 Bug-42 contract, §7 canonical wire format, §8 operator contract,
§9 Phase-3c cutover, and §10 audit conformance are **all** carried
forward from v0.4.2 unchanged.

The single normative change of v0.4.3 is the frontmatter
`status:` flip from `draft` (v0.4.2) to `pre-cutover-freeze`
(v0.4.3) and the addition of two governance-bits:
`freeze-marker: kw-24-cutover-gate` and
`freeze-anchor: persona-engine-0.5.2-final-pre-cutover`.

> **v0.4.3 (2026-05-19, Tag-53):** Strict-superset freeze-marker
> over v0.4.2. **No on-the-wire change. No frame-attribute change.
> No caveat-predicate addition or removal. No publish-mode-contract
> change. No §3 catalogue change. No §4 ENV-flag schema change.**
> The change surface is the spec-status bit alone, declaring the
> specification frozen for the KW-24 Phase-3c cutover gate.
>
> Every v0.4.2 frame, producer, verifier, operator, and runtime
> backend remains valid under v0.4.3 without modification.
> v0.4.3 verifiers MUST accept `wirelangversion: 0.4.0` /
> `0.4.1` / `0.4.2` frames without rewrite. v0.4.0 / v0.4.1 /
> v0.4.2 verifiers MAY treat `wirelangversion: 0.4.3` frames as
> v0.4.0 frames (the spec change is governance-level, not
> wire-level).

v0.4.3 is the **complementary spec-side marker** to the Tag-52
Persona-Engine 0.5.2-final-pre-cutover (PR #336) consolidated
strict-superset bump: the engine declares "no further
substance-side changes pre-cutover" via the `0.5.2-final-pre-
cutover` tag; v0.4.3 declares "no further spec-side changes
pre-cutover" via the `pre-cutover-freeze` status-bit. Together
the two markers form the closed pre-cutover-freeze envelope for
the KW-24 Phase-3c cutover gate.

## 1. Scope of v0.4.3

The marker resolves a single governance item.

| Marker ID | Severity | Surface affected | v0.4.3 resolution |
|---|---|---|---|
| FREEZE-S1 | governance | Spec-side pre-cutover discipline: the KW-24 cutover gate requires a closed change-surface on both substrate (Persona-Engine binary) and spec (Wirelang document). Persona-Engine declared its closure via Tag-52 0.5.2-final-pre-cutover (PR #336). Spec closure was implicit (no PR planned past Tag-50 v0.4.2) but not explicit. | Frontmatter `status: pre-cutover-freeze` plus `freeze-marker: kw-24-cutover-gate` plus `freeze-anchor: persona-engine-0.5.2-final-pre-cutover`. The marker makes spec-side closure auditable, machine-readable, and synchronisable with the engine-side closure. |

**Source-of-truth direction (CEO-Triage 2026-05-19, Tag-53):**
The Persona-Engine substrate is the cutover-trigger; the Wirelang
spec is the conformance-anchor. A cutover gate requires both
to be closed. v0.4.3 is the explicit spec-side closure-bit.

The marker does **not** modify §3.1 catalogue (sixteen rows,
unchanged from v0.4.2), §3.2 (Identity-Substrate byte-stability),
§3.3 (Foundation crates), §3.4 (Crate ↔ welle mapping), §4.1
(ten Pin-Pack-wired boot records — unchanged from v0.4.2 DRIFT-S4
reconciliation), §4.2 (ENV-flag value space), §4.3 (switch
atomicity), §4.4 (default-by-welle-state), §5 (welle inventory),
§6 (Bug-42 contract), §7 (canonical wire format), §8 (operator
contract), §9 (Phase-3c cutover), or §10 (Audit conformance).

It is published as a separate file
(`wirelang-spec-v0-4-3.md`) rather than as an edit to
`wirelang-spec-v0-4-2.md` for the same two reasons that motivated
the v0.4.0 → v0.4.1 → v0.4.2 splits:

1. **Patch-trace integrity.** Tag-50 PR #320 (v0.4.2) is cited
   verbatim by the regression-pin in
   `tests/specs/test_wirelang_spec_v0_4_2_drift_s4_reconciliation.py`.
   Rewriting v0.4.2 in place — even just the frontmatter — would
   break the pin-trail.
2. **Spec-as-code discipline.** Wirelang carries semver-like
   versioning (§1.1 in v0.4.0). v0.4.0 + v0.4.1 + v0.4.2 + v0.4.3
   is the patch-trace. A future v0.5 (Phase-3c-close consolidation,
   target ~KW 28) re-folds v0.4 + v0.4.1 + v0.4.2 + v0.4.3 into a
   single document.

## 2. Conformance keywords

The keywords MUST, MUST NOT, SHOULD, SHOULD NOT, MAY are used as
in RFC 2119 / RFC 8174 (unchanged from v0.2 §2, v0.4 §2, v0.4.1 §2,
v0.4.2 §2).

A producer / verifier / operator conformant to v0.4.2 is
conformant to v0.4.3 by construction.
**No new conformance obligations are introduced.**
The freeze-marker is a governance attribute on the spec document
itself; it does not bind producers, verifiers, or operators to new
behaviour.

## 3. §3 no change

§3 (Phase-3a Rust foundation, sixteen-row catalogue, Identity-
Substrate contract, Foundation classification, crate ↔ welle
mapping) is unchanged from v0.4.2. The freeze-marker scope is
frontmatter only.

## 4. §4 no change

§4.1 (the ten Pin-Pack-wired boot records — DRIFT-S4 reconciliation
from v0.4.2), §4.2 (ENV-flag value space), §4.3 (switch atomicity),
§4.4 (default-by-welle-state) are unchanged from v0.4.2. The
freeze-marker scope is frontmatter only.

### 4.1 Carry-forward inventory (Pin-Pack-0.5.1 boot records)

For audit-locality and to make this freeze-marker document
self-contained for the cutover-gate auditor, the ten Pin-Pack-0.5.1
boot records (v0.4.2 §4.1) are restated here verbatim. The
substance lives in v0.4.2 §4.1; this restatement is a structural
mirror only.

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

This table is a verbatim mirror of v0.4.2 §4.1 columns 1–3. The
binary ENV column, Python authority column, and Phase-3c welle
column are omitted here (they live in v0.4.2 §4.1) — the mirror's
purpose is auditor-locality, not duplication. The
v0.4.2 §4.1 table remains the substance-of-record.

Pin-Pack-0.5.1-pre-cutover.yaml remains the single source of truth
(DRIFT-S4 reconciliation principle from v0.4.2 §1). If any Pin-Pack
record disagrees with the table above, the Pin-Pack wins and a
v0.4.4 patch issues.

## 5. §5 / §6 / §7 / §8 / §9 / §10 no change

§5 (welle inventory), §6 (Bug-42 contract), §7 (canonical wire
format), §8 (operator contract), §9 (Phase-3c cutover), §10
(Audit conformance) are unchanged from v0.4.2.

## 6. Freeze-marker semantics

### 6.1 What `pre-cutover-freeze` means

A Wirelang specification document with frontmatter
`status: pre-cutover-freeze` declares that the document
constitutes the **conformance anchor for the imminent cutover
gate** and that no further substance-side edits to the document
are planned before the cutover gate fires.

The freeze is **soft** in the sense that emergency reconciliation
patches (analogous to v0.4.2 DRIFT-S4) MAY still be issued
between the freeze-marker date and the cutover-gate date if and
only if:

1. A pre-cutover audit (Henrik Internal-Audit, Aisha cross-review,
   or AR-pre-sichtung) identifies a substantive drift between
   spec and substrate that would invalidate the cutover; and
2. The patch is published as a new patch-trace version
   (e.g. v0.4.4) rather than as an in-place edit to v0.4.3; and
3. The new patch-trace version carries
   `status: pre-cutover-freeze` and supersedes v0.4.3 in the
   `replaced-by:` chain.

The freeze is **hard** against non-emergency edits: no editorial
polish, no clarifying footnote, no reformatting MAY be applied
to v0.4.3 between the freeze-marker date and the cutover-gate
date.

### 6.2 What `kw-24-cutover-gate` means

The `freeze-marker: kw-24-cutover-gate` annotation declares
which cutover gate v0.4.3 is anchored to. The Phase-3c cutover
schedule (`docs/quality-gates/phase-3c-acceptance-criteria.md`)
targets KW 24 (calendar week 24 of 2026, i.e. 2026-06-08 through
2026-06-14). v0.4.3 is the conformance anchor for that gate.

Should the cutover-gate date slip (KW 24 → KW 25 etc.), v0.4.3
remains the conformance anchor — the annotation does not encode
a calendar deadline, it encodes a gate-identity.

### 6.3 What `persona-engine-0.5.2-final-pre-cutover` means

The `freeze-anchor: persona-engine-0.5.2-final-pre-cutover`
annotation declares which Persona-Engine binary tag v0.4.3 is
anchored to. The Tag-52 PR #336 consolidated strict-superset
bump (Selin, Phase-3c-Marathon Final Pre-Cutover) tagged the
engine as `0.5.2-final-pre-cutover` declaring no further
substance-side changes pre-cutover. v0.4.3 declares the
complementary spec-side closure.

Together:
- engine substrate: `persona-engine-0.5.2-final-pre-cutover`
- spec anchor: `wirelang v0.4.3 pre-cutover-freeze`
- gate identity: `kw-24-cutover-gate`

form the closed pre-cutover-freeze envelope.

### 6.4 What `pre-cutover-freeze` does NOT mean

`pre-cutover-freeze` is **not** equivalent to:

- **`finalised` / `frozen` / `archived`:** those statuses apply
  post-cutover. v0.4.3 will be re-tagged via a successor
  document (v0.4.4 or v0.5) once the cutover gate has fired.
- **`obsoleted`:** v0.4.2 is **not** obsoleted by v0.4.3.
  v0.4.2 remains the substance-of-record; v0.4.3 is a status-
  marker over the same substance.
- **`canonical`:** the canonical pointer remains
  `wirelang-spec-v0-4.md` plus the v0.4.1 + v0.4.2 + v0.4.3
  patch-trace until the v0.5 consolidation rewrite is published.

## 7. Backward compatibility

A producer / verifier / operator running v0.4.0, v0.4.1, or
v0.4.2 SHALL be treated as fully conformant to v0.4.3. The
freeze-marker is a documentary attribute on the spec, not a
behavioural attribute on participants.

The Pin-Pack-0.5.1-pre-cutover substrate
(`infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml`)
remains the source-of-truth for §4.1 ENV-flag schema. A future
Pin-Pack revision (post-cutover) MAY trigger a v0.4.4 or v0.5
reconciliation patch; until then, v0.4.3 §4.1 (= v0.4.2 §4.1)
is the anchor.

## 8. Audit conformance

A spec document v0.4.3 is audit-conformant if and only if:

- Frontmatter declares `version: 0.4.3` and `extends: 0.4.2`.
- Frontmatter declares `status: pre-cutover-freeze` (the freeze-
  marker discipline §6.1 forbids any other status value).
- Frontmatter declares `freeze-marker: kw-24-cutover-gate`.
- Frontmatter declares
  `freeze-anchor: persona-engine-0.5.2-final-pre-cutover`.
- The body declares "no substance diff" relative to v0.4.2
  prominently (intro paragraph and §1 marker table).
- The body cross-references Tag-52 PR #336 (the engine-side
  closure) and Tag-50 PR #320 (the v0.4.2 substance baseline).
- §3 catalogue contents are unchanged from v0.4.2 (no row
  added, removed, or modified).
- §4.1 contents are unchanged from v0.4.2 (no row added,
  removed, or modified; ten Pin-Pack-wired boot records preserved
  byte-for-byte).

The hermetic test suite that accompanies this spec
(`tests/specs/test_wirelang_spec_v0_4_3_pre_cutover_freeze.py`,
ten or more tests, Tag-53) enforces these invariants statically
(no NATS, no engine boot, no Rust build, no network import).

## 9. Citation pointers

- Tag-52 PR #336 (engine-side pre-cutover-freeze counterpart):
  `5b74b45 Tag-52 Persona-Engine 0.5.2-final-pre-cutover
  consolidated bump (Selin)`.
- Tag-50 PR #320 (v0.4.2 substance baseline):
  `wirelang/specs/wirelang-spec-v0-4-2.md` (ee6c9ca).
- Tag-48 PR #308 (v0.4.1 baseline):
  `wirelang/specs/wirelang-spec-v0-4-1.md` (100004b).
- Tag-45 PR #291 (v0.4 baseline):
  `wirelang/specs/wirelang-spec-v0-4.md` (0300e74).
- Pin-Pack substrate (source-of-truth for §4.1, unchanged):
  `infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml`.
- Boot manifest:
  `wirelang/persona_engine/MANIFEST-0.5.1-pre-cutover.md` §2.
- Cutover-gate acceptance criteria:
  `docs/quality-gates/phase-3c-acceptance-criteria.md`.

— Reza
