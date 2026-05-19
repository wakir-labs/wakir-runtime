<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

# Wirelang-Spec v0.4.4 Reserve-Item Promotion-Sequencing (Tag-65)

**Status:** post-cutover-T0 sequence-promotion plan, doc-form only.
**Activation gate:** KW-24 cutover-T0 fired (no earlier).
**Activation policy:** sequence-promotion-only.
**Anchor draft:** [`wirelang/specs/wirelang-spec-v0-4-4-draft.md`](../../wirelang/specs/wirelang-spec-v0-4-4-draft.md).
**Owner:** Reza (Dev-Engineering-2).
**Mirror-twin:** none (this is the first promotion-sequencing doc;
the Tag-62 protocol-handoff doc covers a different axis).
**AR-authorisation required:** yes (per-RES-Dn promotion PR is a
fresh CEO-Triage decision; this doc only sequences the candidates).

---

## 1. Scope

This document is the **promotion-sequencing plan** for the five
reserve items RES-D1 .. RES-D5 collected in
`wirelang/specs/wirelang-spec-v0-4-4-draft.md` (`status:
post-cutover-reserve-draft`). It is **doc-form only**: no helper
is wired, no test changes any binding behaviour, no spec frontmatter
flips. The sequence-promotion-only activation policy declared in
the draft's frontmatter is the hard authority — until the KW-24
cutover-T0 gate has fired, **no RES-Dn item promotes**.

In scope:

- §2 — per-RES-Dn promotion-voraussetzungen + activation-trigger-
  conditions (one row per reserve item).
- §3 — dependency-DAG between the five items (which items unblock
  which, and which can promote in parallel).
- §4 — recommended sequence-order (the promotion schedule). The
  schedule is a **recommendation**, not a binding contract; the
  CEO-Triage step may reorder items at its discretion.
- §5 — per-item acceptance-criteria (the green/red verdict that
  the per-item promotion PR must satisfy).
- §6 — rollback-pattern when a promotion step fails partway through
  (sequence-rollback discipline, not a forced revert).
- §7 — sandbox-boundary (what this doc may touch from claude-dev
  hands, what requires Operator-Hand / AR-authorisation).

Out of scope:

- Any binding semantic change to v0.4.3 (`pre-cutover-freeze`).
- Any edit to `wirelang-spec-v0-4-4-draft.md` frontmatter.
- Any per-item normative-promotion **execution** (the per-item PR
  is a separate document, written at promotion-time under CEO-Triage
  hand; this doc only **sequences** them).
- Any OTS-anchor activation (Tag-60 stub remains audit-only until
  AR-authorisation per ADR-0023a).

This doc is the Tag-65 follow-on to:

- Tag-63 PR #403 — v0.4.4-draft RES-D1..D5 baseline (17 tests).
- Tag-64 PR #407 — v0.4.4-draft RES-D1..D5 sample-block coverage
  (19 tests).

---

## 2. Per-RES-Dn Promotion-Voraussetzungen + Activation-Trigger-Conditions

Each reserve item has (a) a static-substrate-set (artefacts the
draft already pins or proposes), (b) a dynamic activation-trigger
condition (the runtime / cutover state required at promotion time),
and (c) the post-cutover surface the item touches.

### 2.1 RES-D1 — identity-substrate-evolution (dual-path BIP32)

- **Substrate already pinned (Tag-63 + Tag-64):**
  - Draft §6.1 normative-shape text (dual-path layout, overlap
    window, ENV-flag `WAKIR_BIP32_OVERLAP_WINDOW_LEN`).
  - Sample block §6.1.1 (RES-D1 canonical-form shape with
    `identity-substrate-version: 0.4.4-draft-RES-D1`).
  - Fixture shape-anchor citation: existing
    `tests/fixtures/wakir-ftd-vectors/vector-3-rotation-overlap.json`.
- **Activation-trigger conditions:**
  - KW-24 cutover-T0 fired (`pre-cutover-freeze` -> `post-cutover`
    transition completed; Tag-58 seal-probe verdict carried
    forward as `SEAL-INTACT-AT-FREEZE`).
  - Persona-Engine 0.5.3 production-readiness audit closed-green
    (Tag-63 audit cited in Pin-Pack record #1..#10).
  - Federation-pair rotation policy ratified by CEO-Triage (the
    second derivation path only buys value if rotation cadence
    is decided).
- **Promotion-touch surface:**
  - Wirelang spec body §3.2 -> new §3.2.1 (insert).
  - Persona-Engine: a new ENV-flag default
    (`WAKIR_BIP32_OVERLAP_WINDOW_LEN=256`) under Pin-Pack record #1.
  - Test fixtures: add `vector-3a-rotation-overlap-dual-path.json`.

### 2.2 RES-D2 — capability-token-refinements (`min-attenuation-depth`)

- **Substrate already pinned:**
  - Draft §6.2 normative-shape text (predicate semantics,
    `predicate-interval-empty` error, verifier
    `under-attenuated` verdict).
  - Sample block §6.2.1 pre-allocates catalogue-row-17 alongside
    existing row-16 (`max-attenuation-depth`).
- **Activation-trigger conditions:**
  - KW-24 cutover-T0 fired.
  - RES-D1 not required (independent surface).
  - Federation-diff (`n3_chain_walker`) policy-layer
    approximation deprecation path agreed by CEO-Triage (the
    wire-level predicate only wins if the policy-layer mirror
    retires; otherwise we double-spec).
- **Promotion-touch surface:**
  - Wirelang spec body §7 -> new §7.4 (insert).
  - Catalogue allocation: row-17 reserved across v0.4.3 §3 and
    v0.4.4-draft §3 carry-forward.
  - Producer + verifier code (out-of-scope for this doc; the
    promotion PR carries that change).

### 2.3 RES-D3 — bridge-audit-cleanup (3-mode envelope)

- **Substrate already pinned:**
  - Draft §6.3 normative-shape text (three-mode schema, precedence
    `rust-native > shim-fallback > python`, restart-rule).
  - Sample block §6.3.1 (outer-metadata mode-tag + envelope
    example under each mode).
  - Pin-Pack record #10 anchor citation
    (`WAKIR_BRIDGE_AUDIT_WRITER_BACKEND`).
- **Activation-trigger conditions:**
  - KW-24 cutover-T0 fired.
  - Rust-native bridge-audit writer production-stability window
    (>=14 days under live Welle-Routing) closed-green.
  - Bridge-audit writer image-build pipeline
    (`docs/operations/bridge-audit-writer-image-build.md`)
    enforcing under main-branch protection.
- **Promotion-touch surface:**
  - Wirelang spec body §4.1 -> new §4.1.10a sub-row (insert).
  - Pin-Pack 0.5.1 (or its post-cutover successor) record #10
    value-space extended to the three-mode set.
  - Operator runbook addition (graceful-degradation switch
    procedure).

### 2.4 RES-D4 — schema-registry-v2-prep (OTS-anchored multi-author)

- **Substrate already pinned:**
  - Draft §6.4 normative-shape text (registry-pointer frame,
    federation-side discovery via `route_registry_nats_kv_backend`,
    anchor-cost-attribution rule, verifier-acceptance rule).
  - Sample block §6.4.1 (registry-pointer frame + NATS-KV
    record-shape under `route_registry` bucket).
- **Activation-trigger conditions:**
  - KW-24 cutover-T0 fired.
  - OTS-anchor activation has crossed from audit-only-stub
    (Tag-60) to live-emit (AR-authorisation per ADR-0023a). RES-D4
    is the **first** reserve item that hard-depends on live OTS.
  - Federation-peer-identity catalogue (the `recognised federation
    peer` set in the verifier-acceptance rule) ratified by
    CEO-Triage; minimum two peers identified.
- **Promotion-touch surface:**
  - Wirelang spec body §8 -> new §8.5 (insert).
  - Companion spec `wirelang/specs/schema-registry-spec.md`
    revision to v2.
  - NATS-KV bucket `route_registry` schema extension
    (`registry-pointer-record` key-shape).
  - OTS-anchor courtesy-budget allocation (CFO ratification).

### 2.5 RES-D5 — recovery-drill-leaf-projection-v2 (sharded)

- **Substrate already pinned:**
  - Draft §6.5 normative-shape text (multi-shard envelope,
    `shard-id` / `shard-count` encoding, canonical-concat
    invariant, single-shard back-compat).
  - Sample block §6.5.1 (back-compat `incomplete-projection`
    verdict path).
- **Activation-trigger conditions:**
  - KW-24 cutover-T0 fired.
  - Phase-3c recovery-drill substrate frozen-green (Tag-53 v0.4.3
    parent intact; no in-flight recovery-drill regression).
  - Phase-4 sharding-day plan ratified by CEO-Triage (the multi-
    shard envelope only earns its keep when sharding-day is
    actually scheduled; pre-scheduling is wasted spec surface).
- **Promotion-touch surface:**
  - Wirelang spec body §6 of `recovery-drill-leaf-projection.md`
    -> new §6.4 (insert).
  - Recovery-drill verifier-code adds `incomplete-projection`
    verdict path.
  - Persona-Engine recovery-drill emit-path opt-in flag
    (`WAKIR_RECOVERY_DRILL_SHARD_COUNT` proposed; default `1`).

---

## 3. Dependency-DAG between Items

The five reserve items are **mostly independent** at the spec-text
level — each adds a new section to a different part of v0.4.3 — but
two activation-trigger conditions create dependency edges that the
sequence-order must respect.

```
                  (KW-24 cutover-T0 fired)
                            |
              +-------------+-------------+
              |             |             |
              v             v             v
            RES-D3        RES-D1        RES-D2
        (bridge-audit  (identity-    (capability-
         3-mode)        substrate     token)
              |         dual-path)        |
              |             |             |
              |             v             |
              |          RES-D5           |
              |       (recovery-drill     |
              |        sharded; depends   |
              |        on D1 only         |
              |        through fixture    |
              |        family co-located) |
              |             |             |
              +------+------+-------+-----+
                     |              |
                     v              v
              (live OTS-anchor activation; AR-authorisation
               per ADR-0023a — not a Sandbox-Hand decision)
                            |
                            v
                         RES-D4
                  (schema-registry-v2;
                  HARD dep on live OTS)
```

**Edges (DAG, no cycles):**

1. `cutover-T0 -> {RES-D1, RES-D2, RES-D3, RES-D5}` (all four can
   start the moment T0 fires; they touch independent surfaces).
2. `RES-D1 -> RES-D5` (soft edge): the dual-path identity-substrate
   fixture family (`vector-3a-rotation-overlap-dual-path.json`)
   shares a fixture-tree with the recovery-drill leaf-projection
   fixtures. Promoting RES-D5 before RES-D1 forces a fixture-tree
   reshuffle at promotion-time. This is **soft** — the promotion
   PRs do not error if violated — but it costs +1 PR.
3. `RES-D2 -> nothing` (independent; the catalogue-row-17
   pre-allocation in Tag-64 sample already pins the slot, so
   RES-D2 promotion is a pure §7.4 insert).
4. `RES-D3 -> nothing` (independent; Pin-Pack record #10 already
   exists and is the anchor).
5. `{anything} -> RES-D4` (HARD edge): RES-D4 hard-depends on live
   OTS-anchor activation. Live OTS activation is **not** a Sandbox
   decision (ADR-0023a Sandbox-boundary), so RES-D4 cannot promote
   until AR-authorisation has crossed it from audit-only stub to
   live-emit. This is the only RES-D4 blocker that the
   sequence-plan must enforce.

**Parallelism:** RES-D1, RES-D2, RES-D3 may promote in any order
or in parallel. RES-D5 should follow RES-D1 (soft). RES-D4
follows everything else **and** requires the live-OTS authorisation
crossing.

---

## 4. Recommended Sequence-Order (Promotion-Schedule)

The recommendation below balances three concerns:

- **Risk surface ascending** — the lowest-risk-per-promotion item
  goes first, so a promotion-failure rollback is cheap to absorb.
- **Soft-edge minimisation** — RES-D1 before RES-D5 saves the
  fixture-reshuffle.
- **Live-OTS critical path** — RES-D4 is gated by an AR-authorisation
  step that is **not** on the spec-engineering critical path, so
  RES-D4 goes last and may be deferred indefinitely without
  blocking the others.

| Step | Item | Recommended timing | Rationale |
|---|---|---|---|
| 1 | RES-D3 (bridge-audit 3-mode) | cutover-T0 +1..3 days | Lowest surface change (one §4.1 sub-row insert). Pin-Pack record #10 already exists. The 14-day production-stability window for the Rust-native writer should already be closing-green by this point (it starts running at T0). |
| 2 | RES-D2 (`min-attenuation-depth`) | cutover-T0 +3..7 days | Catalogue-row-17 pre-allocated by Tag-64 sample. The federation-diff policy-layer-mirror deprecation is a separate decision that can run in parallel with promotion. |
| 3 | RES-D1 (dual-path BIP32) | cutover-T0 +7..14 days | Touches Identity-Substrate (high-trust surface). Needs the federation-pair rotation policy ratified first. Adding the second derivation path is reversible (default-emit-path unchanged), so the rollback story is clean. |
| 4 | RES-D5 (sharded recovery-drill) | cutover-T0 +14..28 days, **after RES-D1** | Soft-depends on RES-D1 for fixture-tree co-location. The sharding-day plan must be ratified before this is promoted; until then, the single-shard substrate (`shard-count: 1`) is the default and no behaviour changes. |
| 5 | RES-D4 (OTS-anchored multi-author registry) | indefinite-deferral; promotes when (a) AR has authorised live OTS-emit per ADR-0023a, and (b) two federation peers exist | Hard-depends on live-OTS activation. The other four items earn their keep without RES-D4; RES-D4 only earns its keep when federation has actually grown to >=2 peers. Deferring is the correct default. |

The schedule is **non-binding**. CEO-Triage may reorder Steps 1-4
freely (they are independent at the spec-text level). Step 5
should not be promoted out-of-order: doing so without the live-OTS
authorisation would either ship a broken §8.5 (verifier-acceptance
rule fails at-issuance because the OTS-anchor does not resolve) or
force a degenerate `dry-run` mode that adds churn without value.

---

## 5. Per-Item Acceptance-Criteria

For each RES-Dn promotion, the promotion PR is acceptance-green
iff **all** of the following hold. Acceptance is per-item; a
multi-item PR is discouraged (one promotion = one PR keeps the
patch-trace clean).

### 5.1 Common acceptance-criteria (all five items)

- A1: The v0.4.3 freeze-seal (Tag-58 baseline,
  `wirelang/specs/freeze-baseline.json`) MUST remain `SEAL-INTACT`.
  Promotion edits live in v0.4.4-draft.md (which is becoming v0.4.4
  upon promotion) **or** a new sibling spec file — never in v0.4.3.
- A2: The draft-isolation invariant text (`§2` of v0.4.4-draft)
  MUST be edited at promotion-time: the `status:` frontmatter flips
  away from `post-cutover-reserve-draft`, the activation-trigger
  is consumed, and §2 either flips to v0.4.4-conformance language
  or is replaced by an explicit "this section was the
  draft-isolation invariant; it is hereby retired" stub.
- A3: The Tag-63 (PR #403) and Tag-64 (PR #407) audit suites
  MUST be updated to reflect the post-promotion state — they
  cannot stay frozen on `is_draft=True` after promotion. The
  promotion PR carries this test update.
- A4: The carry-forward inventory (§3, §4, §5..§10 of the draft)
  MUST be re-examined: any section that is materially touched by
  the promotion graduates from "carried forward by reference" to
  "edited in place".
- A5: A new ADR-class entry MUST cite the promotion (per-item ADR
  is appropriate; the Tag-09 / Tag-25 governance pattern applies).

### 5.2 Per-item acceptance-criteria

- **RES-D1:** `vector-3a-rotation-overlap-dual-path.json` fixture
  added and consumed by at least one new test under
  `tests/fixtures/wakir-ftd-vectors/` or
  `wirelang/tests/`. Pin-Pack record #1 ENV-flag value-space
  documents `WAKIR_BIP32_OVERLAP_WINDOW_LEN` with default `256`.
- **RES-D2:** Catalogue-row-17 (`min-attenuation-depth`) added to
  v0.4.3 §3 catalogue carry-forward **and** to v0.4.4 §3 catalogue.
  At least one negative-path test rejects a token with
  `min-attenuation-depth: A` and `max-attenuation-depth: B`
  where `A > B`.
- **RES-D3:** Pin-Pack record #10 value-space documents three
  modes (`python`, `rust-native`, `shim-fallback`). At least one
  test verifies that a bridge-audit envelope is rejected when
  `outer-metadata.mode` is absent.
- **RES-D4:** Companion spec `schema-registry-spec.md` revised
  to v2 with `registry-pointer-frame` layout. At least one test
  verifies that a peer-anchored schema is rejected when (a) the
  OTS-anchor pointer does not resolve, or (b) the peer-identity
  is not on the federation-peer roster.
- **RES-D5:** Recovery-drill verifier returns `incomplete-projection`
  on observing only `shard-id: 0` of an `n > 1` drill, and returns
  the canonical projection on observing the full `0..n-1` set.
  At least one test pins the concat-byte-equality invariant.

---

## 6. Rollback-Pattern at Promotion-Failure

A promotion step fails when (a) the per-item PR cannot land green
under main-branch protection, (b) a post-merge regression is
detected within 24h of merge, or (c) CEO-Triage withdraws the
promotion decision after the PR has merged. The rollback discipline
below assumes any of these triggers.

### 6.1 Pre-merge failure (PR cannot land green)

This is the easy case. The promotion PR remains an open PR;
nothing on `main` has changed. Recovery:

1. Identify the failing acceptance-criterion (A1..A5 or per-item
   5.2).
2. Either fix the criterion in the open PR, or close the PR
   without merge.
3. The reserve item remains in v0.4.4-draft `§6` with its sample
   block intact. No fixture is removed, no Pin-Pack edit happens.
4. The next CEO-Triage cycle may re-attempt with a corrected PR.

No fixture-state-removal, no Pin-Pack rollback, no spec-frontmatter
flip-back. Pre-merge failure is purely a PR-state event.

### 6.2 Post-merge regression within 24h

This is the costly case. The promotion has landed on `main`,
downstream consumers may have started keying off the new shape,
and the regression-window action is **forward-fix-or-revert**
under CEO-Triage hand. Recovery:

1. **Within 4h of detection:** CEO-Triage triages forward-fix vs.
   revert. Default verdict if no triage in 4h: revert.
2. **Forward-fix path:** a follow-on PR lands within 24h. The
   §6.x non-normative text remains retired (the promotion-PR
   removed it).
3. **Revert path:** `git revert` on the promotion-PR commit. The
   §6.x non-normative text is re-added (cherry-picked back from
   the pre-promotion HEAD of v0.4.4-draft.md). The `status:`
   frontmatter is flipped back to `post-cutover-reserve-draft` if
   the promotion-PR had flipped it. The ADR entry from A5 is
   marked `superseded: revert-<tag-N>`.
4. **Post-revert:** the reserve item returns to its pre-promotion
   state. A follow-up CEO-Triage cycle decides whether to re-attempt.

### 6.3 CEO-Triage withdraws after merge

This is the political case. The PR landed green, no regression
fired, but CEO-Triage subsequently decides the promotion was
premature. Recovery follows the **revert path** (6.2 step 3),
plus a Mira-Hand notify-log entry recording the withdrawal
rationale for the audit-trail.

### 6.4 Multi-item rollback sequencing

If two or more items have promoted and a regression is detected
on the latest one, **only the latest** is rolled back by default.
The earlier promoted items remain on `main`. The dependency-DAG
(§3) guarantees this is safe: edges are forward-only, so reverting
a later item never breaks an earlier item.

Exception: if the regression-investigation reveals that an
earlier promotion was the root cause, the rollback cascades
backwards in promoted-order. This is **rare** and is a
CEO-Triage decision, not a Sandbox-Hand decision.

---

## 7. Sandbox-Boundary

Per ADR-0023a, the Sandbox boundary draws a hard line between
operations claude-dev MAY perform autonomously and operations
that require Operator-Hand or AR-authorisation.

### 7.1 Sandbox-Scope (claude-dev MAY do)

- Author this Tag-65 doc and its helper / test substrate.
- Open the Tag-65 PR (`reza/tag-65-promotion-sequencing`) with a
  REUSE-wrapped doc plus stdlib helper plus pytest suite, run the
  hermetic tests inside the worktree, and self-merge under the
  Tag-N continuous-mode-spawn pattern.
- Cite ADR pointers, prior PR numbers, and the v0.4.3 freeze-seal
  baseline.
- Walk the v0.4.4-draft.md document in read-only mode to verify
  RES-D1..D5 anchors are present.

### 7.2 Out-of-Sandbox-Scope (Operator-Hand / AR required)

- The actual per-item promotion PRs (Steps 1..5 in §4). Each is
  a fresh CEO-Triage decision under a new ADR-class entry. This
  Tag-65 doc only **sequences** them.
- Any edit to `wirelang-spec-v0-4-4-draft.md` body or frontmatter.
  The draft is frozen-by-discipline for Tag-65; the next edit is
  the promotion PR itself.
- Activation of live OTS-anchor emit (ADR-0023a §7). The Tag-60
  pre-activation probe and the Tag-65 RES-D4 sequencing both
  remain pre-activation until AR-authorisation crosses them to
  live.
- Pin-Pack 0.5.1 revision. Pin-Pack is a Selin / Tomás Pin-Pack
  axis; Tag-65 cites Pin-Pack records but does not edit them.
- Persona-Engine code change. Tag-65 cites the Persona-Engine
  ENV-flag value-space but does not change a single Persona-Engine
  binary or config file.

### 7.3 Operator-Hand-Sandbox-Gap recap

The Tag-65 doc is **doc-form only**. Even when this doc lands
green on `main`, no reserve-item promotion has executed. The
sequence-order in §4 becomes operative only when CEO-Triage opens
a per-item promotion PR citing this doc as the sequencing
authority. Anything downstream of that (binary cuts, ENV-flag
defaults, live OTS calls) is Operator-Hand work outside the
Sandbox boundary.

### 7.4 Cross-anchor

- ADR-0007 (Persona-Engine Pin-Pack discipline).
- ADR-0023a (Sandbox-Boundary).
- ADR-0023b (Operator-Hand vs. AR-authorisation).
- ADR-0025 (Three-axis performance measurement).
- Tag-58 PR — v0.4.3 freeze-seal probe.
- Tag-60 PR #382 — OTS pre-activation stub.
- Tag-63 PR #403 — v0.4.4-draft RES-D1..D5 baseline (Reza, 17 tests).
- Tag-64 PR #407 — v0.4.4-draft RES-D1..D5 sample-block coverage
  extension (Reza, 19 tests).

-- Reza
