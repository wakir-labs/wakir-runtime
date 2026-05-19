<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

# RES-D4 High-Residual Mitigation Deep-Dive (Tag-69)

**Status:** mitigation-deep-dive, doc-form only.
**Activation gate:** KW-24 cutover-T0 fired (no earlier);
RES-D4 specifically remains **indefinite-deferral** per Tag-65
§4 Step 5 until AR-authorisation per ADR-0023a lands.
**Anchor pre-mortem:** [`docs/operations/wirelang-spec-v0-4-4-activation-pre-mortem.md`](./wirelang-spec-v0-4-4-activation-pre-mortem.md) §5, §7.3.
**Anchor sequencing:** [`docs/operations/wirelang-spec-v0-4-4-promotion-sequencing.md`](./wirelang-spec-v0-4-4-promotion-sequencing.md) §2.4, §3 (HARD edge), §4 Step 5.
**Owner:** Reza (Dev-Engineering-2).
**Mirror-twin:** none (this is the first deep-dive doc on a single
RES-Dn item; the Tag-67 activation pre-mortem inventories all five
items at one level of detail and identifies RES-D4 as the single
`high`-residual outlier — this doc takes that outlier and unpacks
each of its three dominant residual drivers).
**AR-authorisation required:** no (informative skizze in the
sense of GOVERNANCE.md §10; no audit-verdict, no normative
classification, no recommendation to alter the indefinite-deferral
default; this is a planning artifact for the day AR-authorisation
eventually lands).

---

## 1. Scope

This document is the **RES-D4-specific mitigation deep-dive** for
the single reserve item that the Tag-67 activation pre-mortem
rated `high`-residual (the only such item among RES-D1..RES-D5).
The Tag-67 doc §5 enumerates the ten failure modes (A1..A5,
B1..B5) at table-row granularity; §5.2 names the conjunction
A1 + B2 + B5 (live-OTS-anchor activation, federation-peer roster
integrity, audit-coverage gap) as the dominant residual driver;
§7.3 confirms the `high` rating and §7.2 (cross-item hot spots)
flags RES-D4 as the single isolation hot spot in the aggregate-
risk-map.

This deep-dive does **not** alter the Tag-67 ratings, does not
re-rank the Tag-65 §4 sequence-order, and does not lift the
indefinite-deferral default. It takes the three dominant residual
drivers, treats them under a **joint-necessity** framing (each
hard-dep is necessary; the conjunction is the minimum bar), and
decomposes each into:

- the **hard dependency** chain that produces the residual risk,
- the **mitigation strategy** that closes the gap when (and only
  when) the hard dependency is satisfied, and
- the **re-evaluation trigger** that should cause the deep-dive
  to be revisited.

It is **doc-form only**: no helper changes binding behaviour, no
spec frontmatter is flipped, no fixture is added, no Pin-Pack
record is allocated, no NATS-KV bucket is mutated. The deep-dive
is an **informative skizze** (GOVERNANCE.md §10 pattern), not an
audit-verdict and not a CEO-Triage decision-input requesting
schedule change.

The structure follows the Tag-67 pre-mortem pattern at one level
of zoom (three hard-deps, three mitigation tables, one indefinite-
deferral justification, two audit-only substrate-preparation
sketches, and one explicit sandbox-boundary recital):

- §1 — scope and posture declaration.
- §2 — hard-dep inventory (OTS-Calendar + Peer-Roster +
  Audit-Coverage), the three dominant residual drivers.
- §3 — mitigation strategies per hard-dep (one decomposition
  table per dep, with failure-mode codes cross-anchored back to
  Tag-67 §5).
- §4 — indefinite-deferral justification and re-evaluation
  triggers (when should this doc be revisited).
- §5 — cross-anchor to the Tag-67 pre-mortem and the Tag-65
  promotion-sequencing doc, with the HARD-edge restatement.
- §6 — OTS-anchor substrate preparation, audit-only (what can
  be readied in advance of AR-authorisation without invoking it).
- §7 — peer-roster substrate preparation, audit-only (what can
  be readied in advance of federation-peer-count >= 2 without
  asserting it).
- §8 — sandbox-boundary recital (the three explicit boundaries
  that this doc does not cross).

Out of scope:

- Any binding semantic change to v0.4.3 (`pre-cutover-freeze`).
- Any edit to `wirelang-spec-v0-4-4-draft.md` frontmatter or body.
- Any RES-D4-promotion-PR execution (separate document, written
  at promotion-time under CEO-Triage hand once AR-authorisation
  lands; this doc only **deepens the mitigation map** for those
  promotions).
- Any AR-authorisation request for live OTS-anchor activation —
  remains AR-Hand per ADR-0023a; this doc does not advocate for
  the authorisation to be granted or withheld.
- Any audit-verdict classification, finding, or risk-rating in
  the audit sense; this is an informative skizze, not a
  Henrik-Voss audit-output.
- Schedule re-recommendation: the Tag-65 §4 sequence-order plus
  Step-5 indefinite-deferral remain the binding-by-default
  recommendation; this deep-dive enumerates mitigation **per
  hard-dep** without re-ranking the schedule.
- Any change to RES-D1, RES-D2, RES-D3, RES-D5 mitigation maps;
  those four items are covered at one level by Tag-67 §2..§6 and
  do not warrant deep-dives at this time (their residual ratings
  range from `low-medium` to `medium`).

The five-axis classifier for §3 mitigation tables is:

- **Hard-dep code** (HD-1 / HD-2 / HD-3),
- **Failure-mode codes cross-anchored** (the Tag-67 §5 A* / B*
  codes that this hard-dep dominates),
- **Mitigation strategy** (the doc-form-only, audit-only path to
  closing the residual when the hard-dep is eventually satisfied),
- **Pre-conditions** (what must be true before the mitigation is
  executable),
- **Post-mitigation residual** (what `medium`-or-lower rating the
  mitigated item would carry once the hard-dep clears).

This doc is the Tag-69 follow-on to:

- Tag-63 PR #403 — v0.4.4-draft RES-D1..D5 baseline (17 tests).
- Tag-64 PR #407 — v0.4.4-draft RES-D1..D5 sample-block
  coverage extension (19 tests).
- Tag-65 PR — RES-D promotion-sequencing doc + helper + tests.
- Tag-66 PR #421 — RES-D items OTS-probe coverage (22 tests).
- Tag-67 PR — v0.4.4 activation pre-mortem doc (Reza, 17 tests).
- Tag-68 PR #432 — pre-mortem coverage test-suite (163 tests).

---

## 2. Hard-Dep Inventory

The Tag-67 pre-mortem §5.2 identifies the dominant residual
driver for RES-D4 as the conjunction of three failure modes:
**A1 (live-OTS-anchor activation)**, **B2 (federation-peer roster
integrity)**, **B5 (audit-coverage gap on a critical item)**.
Each maps to a **hard dependency** — a state of the world that
must be true before the corresponding mitigation can fire. This
section enumerates those three hard-deps and names them HD-1,
HD-2, HD-3.

| HD | Name | Tag-67 §5 cross-anchor | What state of the world it requires |
|---|---|---|---|
| HD-1 | Live OTS-Calendar | A1, A3, B1, B4 | AR-authorisation per ADR-0023a has crossed live-OTS-anchor activation from audit-only stub (Tag-60) to live-emit. The Tag-60 OTS pre-activation stub resolves to a live OpenTimestamps calendar that produces real anchors at issuance. |
| HD-2 | Peer-Roster Integrity | A2, B2, B3 | Minimum two federation peers exist in the production-active roster (not test-fixtures, not catalogue-stub entries). The peer-roster is observable, rotation-tracked, and the verifier-acceptance rule reads a snapshot at issuance (not at verification, TOCTOU-safe). |
| HD-3 | Audit-Coverage on Critical Items | A4, A5, B4, B5 | Henrik Voss audit-sample (ADR-0014 + ADR-0025) is configured to prioritise live-OTS-dependent items in the post-promotion rotation. RES-D4 is flagged in the audit-sample-priority list and post-promotion audits include the registry-pointer-frame verifier-acceptance path. |

The three hard-deps are **independent but co-required**: HD-1
without HD-2 produces a live-OTS-anchor that anchors a
fixture-only registry (no production federation value); HD-2
without HD-1 produces a real federation roster but no anchored
provenance for registry pointers (no audit-trail for multi-author
registry mutations); HD-3 without HD-1 and HD-2 is moot (no
critical item exists yet to prioritise in audit-sample). The
conjunction is what RES-D4 promotion requires.

The Tag-65 §4 Step 5 indefinite-deferral is the canonical
default: **none** of HD-1, HD-2, HD-3 are currently satisfied at
Tag-69. AR-authorisation for live-OTS has not been requested;
federation-peer count is currently 0 production-active peers
(the Tag-60 stub uses fixture peers); Henrik Voss audit-sample
configuration has not been amended for RES-D4 prioritisation.

---

## 3. Mitigation Strategies per Hard-Dep

This section enumerates the mitigation strategy for each of the
three hard-deps, structured as one table per dep. The intent is
that on the day each hard-dep clears (HD-1 by AR-authorisation,
HD-2 by federation growth, HD-3 by audit-sample-config update),
the corresponding mitigation can be executed without re-deriving
the strategy from first principles. The mitigations are
**doc-form-only** at Tag-69; the binding-behaviour code change
happens at promotion-time under CEO-Triage hand.

### 3.1 HD-1 — Live OTS-Calendar Mitigation

| Item | Detail |
|---|---|
| Hard-dep code | HD-1 |
| Cross-anchored failure modes | A1 (live-OTS resolver fails at issuance), A3 (anchor budget volatility), B1 (async authorisation race), B4 (rollback non-atomic across NATS-KV + spec) |
| Mitigation strategy | (a) Verifier-acceptance rule cites the OTS-anchor as a **required** field in `registry-pointer-frame` only when live-OTS is active; in audit-only-stub mode (Tag-60), the field is `optional` with a `pending-anchor` marker. (b) The promotion-PR for RES-D4 includes a **flip-switch test**: producer emits a frame with live-anchor, verifier accepts it; then producer emits a stub-marked frame, verifier rejects it. (c) Courtesy-budget allocation uses a 2x headroom factor (Tag-67 §5.1 A3). (d) Rollback procedure (Tag-65 §6.2 step 3 tightening) reverts NATS-KV bucket schema atomically with spec §8.5. |
| Pre-conditions | AR-authorisation per ADR-0023a has landed (anchor in `/var/home/fred/AI-Corp/decisions/` or equivalent). CFO ratification of OTS-anchor courtesy-budget includes explicit post-promotion run-rate (Tag-67 §5.1 B3). Live-OTS resolver smoke-test passes on a non-fixture calendar URL. |
| Post-mitigation residual | `medium` (down from `high`-driver). The dominant residual after HD-1 clears is anchor-budget volatility (A3), which is monetary not technical, and is contained by the 2x headroom and the `pending-anchor` queue depth metric. |

### 3.2 HD-2 — Peer-Roster Integrity Mitigation

| Item | Detail |
|---|---|
| Hard-dep code | HD-2 |
| Cross-anchored failure modes | A2 (TOCTOU on peer rotation), B2 (peer-count loose interpretation), B3 (CFO ratification envelope unclear post-promotion) |
| Mitigation strategy | (a) Verifier-acceptance rule reads the peer-roster snapshot at **issuance**, not at verification (Tag-67 §5.1 A2 mitigation anchor). The snapshot is included in the issued frame (so verifier and producer agree on the roster). (b) The "minimum two peers" condition is interpreted strictly: **production-active**, not fixture-bucket, not catalogue-stub. The roster lists `(peer-id, kind)` where `kind ∈ {production, fixture}` and the count is filtered to `kind == production`. (c) Peer-rotation events emit a `roster-mutation` audit-trail entry; the audit-trail is observable in the NATS-KV `route_registry` bucket. (d) CFO ratification line-item for post-promotion run-rate is included in the promotion-PR (Tag-67 §5.1 B3 mitigation anchor). |
| Pre-conditions | Federation has grown to >=2 production-active peers (not 2 fixtures + 0 production, not 1 production + 1 stub). Selin's federation work-stream confirms the production-peer count. The Tag-65 §2.4 activation-trigger "minimum two peers identified" is read in the strict sense. |
| Post-mitigation residual | `medium-low` (down from `high`-driver). The dominant residual after HD-2 clears is the cross-team handoff discipline (Selin federation + CFO budget), which is procedural and contained by the standard cross-team handoff pattern (Tag-67 §7.1 mode-family row). |

### 3.3 HD-3 — Audit-Coverage Mitigation

| Item | Detail |
|---|---|
| Hard-dep code | HD-3 |
| Cross-anchored failure modes | A4 (NATS-KV key-shape schema collision), A5 (v1→v2 migration silently breaks consumers), B4 (rollback leaves NATS-KV bucket extension in place), B5 (audit-sample misses RES-D4) |
| Mitigation strategy | (a) Henrik Voss audit-sample configuration is amended (under HR/Audit-hand, not Reza-hand) to prioritise live-OTS-dependent items per ADR-0025 risk-weighted rotation; RES-D4 is flagged as `priority: live-ots-critical-path`. (b) Schema-extension audit verifies the `registry-pointer-record` key-shape is a strict superset of the existing `route_registry_nats_kv_backend.py` discovery key-shape (Tag-67 §5.1 A4 mitigation). (c) Companion spec `wirelang/specs/schema-registry-spec.md` v2 carries a migration appendix and the promotion-PR includes a v1-consumer compatibility smoke (Tag-67 §5.1 A5 mitigation). (d) Rollback procedure includes an explicit NATS-KV bucket schema atomic-revert step OR a forward-compat documentation note that the bucket extension is left in place by design (Tag-67 §5.1 B4 mitigation). |
| Pre-conditions | Audit-sample-priority-list amendment is anchored in HR/Audit decision-doc (not in Reza's hand). Henrik Voss confirms RES-D4 prioritisation. The Tag-66 PR #421 OTS-probe coverage extends to the RES-D4 verifier-acceptance code path. |
| Post-mitigation residual | `medium-low` (down from `high`-driver). The dominant residual after HD-3 clears is rollback-atomicity discipline (B4), which is shared across RES-D2, RES-D3, RES-D4, RES-D5 (Tag-67 §7.2 rollback-atomicity hot spot) and is contained by the Tag-65 §6.2 step-3 rollback procedure tightening. |

### 3.4 Aggregate Residual After Three-Hard-Dep Clearance

When all three hard-deps clear (HD-1 + HD-2 + HD-3), the
aggregate residual for RES-D4 drops from `high` to **`medium`**
(driven by anchor-budget volatility and rollback-atomicity hot
spot, both shared with other RES-Dn items and not RES-D4-unique).
This matches the Tag-67 §7.3 distribution rating that the other
four RES-Dn items currently carry — RES-D4 stops being the
isolation hot spot once all three hard-deps are satisfied.

The deep-dive does **not** claim that satisfying the three
hard-deps is sufficient to promote RES-D4; sufficiency is a
CEO-Triage decision (Tag-65 §4 Step 5 framing). The deep-dive
claims that satisfying the three hard-deps is **necessary** to
drop the residual from `high` to `medium`, and that until they
are satisfied, the indefinite-deferral default is the correct
response.

---

## 4. Indefinite-Deferral Justification and Re-Evaluation Triggers

### 4.1 Indefinite-deferral as the correct default

The Tag-65 §4 Step 5 recommendation is **indefinite-deferral**
for RES-D4 until two conditions hold (AR-authorised live-OTS,
two production-peer roster). The Tag-67 §5.2 residual analysis
reaffirms this default. This deep-dive adds a third necessary
condition (HD-3 audit-coverage prioritisation) and explains the
**joint-necessity** structure: any one hard-dep without the
others produces residual `high` regardless of the other two's
state.

The indefinite-deferral is not a recommendation to abandon
RES-D4; it is a recommendation to **wait** until the federation
substrate has organic reasons to demand the multi-author registry.
The Tag-65 §2.4 activation-trigger language is "minimum two peers
identified"; this deep-dive interprets that strictly (HD-2). The
single-peer federation has no operational use for a multi-author
registry, so the residual `high` simply reflects that the item
should not promote into a non-existent demand.

### 4.2 Re-evaluation triggers

This doc should be revisited when **any** of the following
trigger events occurs (each independently warrants a re-read,
not necessarily a re-write):

| Trigger | What changed | Action |
|---|---|---|
| T1 | AR-authorisation for live-OTS lands (HD-1 clears) | Re-read §3.1, confirm pre-conditions in §3.1 still hold (CFO ratification envelope, smoke-test passes). If yes, mark HD-1 as `satisfied` in a Tag-N follow-on note and proceed to T2 check. |
| T2 | Federation grows to >=2 production-active peers (HD-2 clears) | Re-read §3.2, confirm peer-roster integrity in the strict sense. If yes, mark HD-2 as `satisfied` and proceed to T3 check. |
| T3 | Henrik Voss audit-sample amended to prioritise RES-D4 (HD-3 clears) | Re-read §3.3, confirm audit-sample-priority anchor exists. If yes, mark HD-3 as `satisfied` and the deep-dive's "joint necessity" condition is met. |
| T4 | CEO-Triage signals RES-D4-promotion-PR is to be written | This is the consumer of T1+T2+T3 being satisfied. The promotion-PR author re-reads §3.1, §3.2, §3.3 mitigation strategies and folds them into the PR's mitigation-anchor citations. |
| T5 | Tag-67 pre-mortem is amended or superseded | This deep-dive is downstream of Tag-67 §5; if Tag-67 §5 is rewritten, this doc must be re-aligned. |
| T6 | ADR-0023a is amended (sandbox-boundary change) | The deep-dive's HD-1 mitigation depends on ADR-0023a framing; if the ADR is amended, §3.1 pre-conditions must be re-derived. |
| T7 | NATS-KV bucket schema undergoes unrelated migration | HD-3 mitigation §3.3 (a, b) depends on the current `route_registry` bucket key-shape; an unrelated migration may change the schema-extension audit surface. |

If **none** of T1..T7 occurs, this deep-dive remains valid as
written. The Tag-69 doc-form-only delivery is intentionally
**stable across the indefinite-deferral period** — it should not
need refresh-sweeps until a trigger fires.

### 4.3 What this section does NOT do

This section does **not**:

- Set a calendar date for re-evaluation (the deferral is
  *indefinite*, by design).
- Recommend that any of T1..T7 be accelerated.
- Claim that the deep-dive captures the full mitigation surface
  for RES-D4 (the Tag-67 §5 ten-mode inventory remains the
  exhaustive list; this deep-dive zooms on the three dominant
  residuals from §5.2 only).
- Imply that RES-D4 will ever be promoted; it is structurally
  possible that the federation does not grow to >=2 production-
  active peers within the Wakir-runtime lifetime, in which case
  RES-D4 remains in `post-cutover-reserve` indefinitely. That is
  not a failure of RES-D4 — it is the reserve being a reserve.

---

## 5. Cross-Anchor to Pre-Mortem and Promotion-Sequencing

### 5.1 Anchor map

This deep-dive is downstream of two upstream artifacts:

- **Tag-67 activation pre-mortem** (`wirelang-spec-v0-4-4-activation-pre-mortem.md`):
  - §5 — RES-D4 failure-mode inventory (A1..A5, B1..B5),
  - §5.2 — RES-D4 residual-risk analysis (`high` rating,
    conjunction A1 + B2 + B5),
  - §7.2 — cross-item hot spots (RES-D4 isolation hot spot),
  - §7.3 — residual-risk distribution (RES-D4 is the only
    `high`-rated item).
- **Tag-65 promotion-sequencing doc** (`wirelang-spec-v0-4-4-promotion-sequencing.md`):
  - §2.4 — RES-D4 promotion-touch surface and activation-trigger,
  - §3 — DAG hard-edge restatement (RES-D4 hard-depends on
    live-OTS),
  - §4 Step 5 — indefinite-deferral recommendation,
  - §5.2 — RES-D4 acceptance criteria (including v1→v2
    migration test extension),
  - §6.2 — rollback procedure (step-3 atomic-revert hot spot
    shared with RES-D2, RES-D3, RES-D5).

### 5.2 HARD-edge restatement

The Tag-65 §3 DAG identifies one HARD edge in the RES-D
promotion graph:

```
{anything} -> RES-D4  (HARD edge: live-OTS-anchor activation)
```

This deep-dive does not introduce new edges. It refines the HARD
edge by naming the three hard-deps (HD-1, HD-2, HD-3) that
collectively constitute its prerequisite. The single Tag-65 HARD
edge expands at Tag-69 into:

```
HD-1 + HD-2 + HD-3  -> RES-D4-promotion-PR-eligible
```

where the conjunction is **necessary but not sufficient**
(sufficiency is CEO-Triage hand). The conjunction is the deep-
dive's central planning claim.

### 5.3 Promotion-PR template hooks

When the day arrives that T1 + T2 + T3 are all satisfied and
CEO-Triage signals T4 (write the promotion-PR), the promotion-PR
author should fold this deep-dive's §3.1, §3.2, §3.3 mitigation
tables into the PR description as **mitigation-anchor citations**.
The PR description should not re-derive the mitigation strategy
from first principles; it should cite this doc and confirm each
of HD-1, HD-2, HD-3 as satisfied with an anchor pointer
(AR-authorisation doc anchor; peer-roster snapshot anchor;
Henrik audit-sample-config anchor).

This hook is not enforced by helper. It is editorial discipline
on the promotion-PR-author. The helper at Tag-69
(`tooling/audit/verify_res_d4_mitigation_doc.py`) verifies
**doc shape**, not promotion-PR shape.

---

## 6. OTS-Anchor Substrate Preparation (Audit-Only)

This section enumerates what can be **readied in advance** of
HD-1 clearing, without invoking AR-authorisation and without
emitting any live-OTS anchor. The intent is that on the day
AR-authorisation lands, the production substrate is not in a
cold-start state.

All items in this section are **audit-only**: they may be inspected,
documented, code-reviewed, and frame-tested in fixture mode, but
they **must not** emit live-OTS calendar traffic.

| Item | Audit-only readiness | Hand |
|---|---|---|
| Tag-60 OTS pre-activation stub | Already in place per Tag-60 PR #382. The stub resolves a fixture calendar URL and produces a `pending-anchor` marker. No live calendar traffic. | Reza-hand (already shipped). |
| Schema-extension fixture-frames | Add `registry-pointer-frame` fixture-frames to `tests/fixtures/wakir-ftd-vectors/` with `anchor-status: pending` markers, validating the producer-side frame shape without resolver invocation. | Reza-hand (Tag-69+ scope; not in this PR). |
| Verifier-acceptance rule (audit-only mode) | Verify-rule code path for `registry-pointer-frame` is implemented with an `audit-only` branch that accepts `anchor-status: pending` markers; the `live-emit` branch is gated by an ENV-flag default-off. | Reza-hand (Tag-69+ scope; not in this PR; promotion-PR scope). |
| ADR-0023a-compatible AR-authorisation request template | Pre-write the AR-authorisation request structure (what AR would need to see to authorise live-OTS emit), without actually requesting. The template lives in this deep-dive §6 as a sketch, not in `/decisions/` as a pending ADR. | Mira-hand (when AR-authorisation is actually pursued). |

### 6.1 AR-authorisation request template (sketch only)

The sketch is **not** an AR-authorisation request. It enumerates
what such a request would include, so that on the day Mira drafts
the real request, the structure is not derived from scratch.

- **Purpose statement:** RES-D4 promotion requires live-OTS-anchor
  resolution for `registry-pointer-frame` issuance; current Tag-60
  stub produces `pending-anchor` markers only.
- **Operational scope:** which calendar URL(s), what anchor-rate
  (per-frame vs. per-batch), what budget envelope (initial +
  post-promotion run-rate).
- **Rollback path:** procedure to revert to Tag-60 stub mode if
  live-OTS emit fails post-authorisation (Tag-65 §6.2 step-3
  rollback procedure cross-anchor).
- **Audit-trail visibility:** how Henrik Voss audit-sample
  inspects live-OTS-anchor activity post-authorisation.
- **Sandbox-boundary recital:** AR-authorisation does NOT include
  Reza-hand-emit; live-emit at promotion-PR-merge is Mira-hand at
  minimum, possibly AR-Hand depending on Tag-65 §4 Step 5
  re-reading at the time.

This sketch is intentionally not formatted as a draft-ADR or a
draft-decision-doc. It is a planning artifact for an event that
may never occur (per §4.3).

---

## 7. Peer-Roster Substrate Preparation (Audit-Only)

This section is the HD-2 analogue of §6. It enumerates what can
be readied in advance of HD-2 clearing (federation grows to >=2
production-active peers), without falsely claiming peer-count or
emitting fixture frames as production.

| Item | Audit-only readiness | Hand |
|---|---|---|
| Tag-60 federation-pair fixture catalogue | Already in place. Two fixture peers (peer-A, peer-B) with `kind: fixture` markers in `route_registry_nats_kv_backend.py`. | Reza-hand (already shipped). |
| `kind: production / fixture` schema field | The NATS-KV `route_registry` bucket key-shape includes a `kind` discriminator. Verifier-acceptance rule filters peer-count by `kind == production`. The Tag-67 §5.1 A2 / B2 mitigation anchors reference this filter. | Reza-hand (Tag-69+ scope; not in this PR; promotion-PR scope). |
| Peer-rotation audit-trail | The `roster-mutation` audit-trail entry pattern is documented in this deep-dive §3.2 as the mitigation; concrete implementation lives at promotion-PR scope. | Reza-hand (promotion-PR scope). |
| Cross-team handoff to Selin (federation owner) | Selin's federation work-stream owns the production-peer-count growth. This deep-dive does not direct Selin; it documents the cross-team handoff discipline (Tag-67 §7.1 cross-team coordination mode-family). | Selin-hand for production-peer growth; Reza-hand for the verifier-side mitigation. |

### 7.1 Strict-interpretation invariant

The Tag-65 §2.4 activation-trigger "minimum two peers identified"
is interpreted in the **strict** sense throughout this deep-dive:

- "minimum two peers" means count >= 2,
- "identified" means listed in the production-active roster with
  `kind: production`,
- "production" means **not** test-fixture, **not** catalogue-stub,
  **not** Tag-60-pre-activation-fixture.

The strict interpretation is the load-bearing definition. A
loose interpretation (e.g. counting fixtures as production) would
satisfy the literal trigger but defeat the operational purpose of
HD-2; the deep-dive treats loose interpretation as a B2 failure
mode (Tag-67 §5.1 B2).

---

## 8. Sandbox-Boundary

This deep-dive does **not** cross the following three boundaries.
The recital is intentional: a planning artifact for a deferred
promotion is exactly the kind of doc that risks scope-creep into
the deferred action itself. The boundaries are the discipline
that keeps Tag-69 doc-form-only.

### 8.1 Boundary 1 — No live-OTS calendar traffic

This deep-dive does **not**:

- Resolve any live OTS calendar URL.
- Emit any OTS-anchor request.
- Generate any `registry-pointer-frame` with `anchor-status:
  resolved`.
- Touch the Tag-60 OTS pre-activation stub configuration.

The §6 "OTS-Anchor Substrate Preparation" is **audit-only** in
the explicit sense: any code change implied by §6 lives in a
future Reza-PR scoped to schema-extension fixture frames and
verifier-rule audit-only branches, not in this Tag-69 PR.

### 8.2 Boundary 2 — No AR-authorisation request

This deep-dive does **not**:

- Request AR-authorisation for live-OTS-anchor activation.
- Draft a `/decisions/` ADR for AR-authorisation.
- Place an item on the AR meeting agenda.
- Imply that AR-authorisation should be granted or withheld.

The §6.1 "AR-authorisation request template sketch" is
**explicitly a sketch**, not a draft-request. The sketch lives
in-doc; no follow-on artifact is created.

### 8.3 Boundary 3 — No promotion-PR opening

This deep-dive does **not**:

- Open an RES-D4 promotion-PR.
- Pre-write spec text for `wirelang-spec-v0-4-4-draft.md` §8.5
  (RES-D4 normative section).
- Pre-write companion spec v2 for
  `wirelang/specs/schema-registry-spec.md`.
- Pre-write NATS-KV bucket schema extension code.
- Mutate any binding behaviour.

The promotion-PR exists only as a downstream consumer of T1 +
T2 + T3 + T4 (per §4.2). Until those triggers fire, no
promotion-PR work is in scope.

### 8.4 What this deep-dive IS allowed to do (positive scope recital)

For completeness, the boundaries above are paired with the
positive scope:

- Write doc-form text about RES-D4 mitigation strategies.
- Cross-anchor to Tag-67 and Tag-65 existing docs.
- Name hard-deps (HD-1, HD-2, HD-3) as planning labels.
- Enumerate re-evaluation triggers (T1..T7).
- Sketch audit-only readiness items per hard-dep.
- Recite sandbox-boundaries.

This is the entirety of the Tag-69 scope. Anything beyond this
is deferred to the appropriate downstream artifact.

---

## 9. Cross-Anchor (Citations)

- ADR-0007 (Persona-Engine Pin-Pack discipline) — Pin-Pack record
  allocation for any post-promotion ENV-flag landing.
- ADR-0014 (Audit-Sample Risk-Weighted Rotation) — HD-3
  prioritisation list amendment substrate.
- ADR-0023a (Sandbox-Boundary) — load-bearing for HD-1 live-OTS
  AR-authorisation requirement.
- ADR-0023b (Operator-Hand vs. AR-authorisation) — discipline for
  separating Reza-hand from AR-hand in §6 and §8.
- ADR-0025 (Three-axis performance measurement) — audit-sample
  rotation discipline for HD-3.
- GOVERNANCE.md §10 — informative-skizze posture for this doc.
- Tag-44 internal-audit Phase-3-Marathon pre-mortem (Henrik Voss,
  form-anchor pattern at one level up).
- Tag-58 PR — v0.4.3 freeze-seal probe.
- Tag-60 PR #382 — OTS pre-activation stub (HD-1 audit-only
  substrate).
- Tag-63 PR #403 — v0.4.4-draft RES-D1..D5 baseline (17 tests).
- Tag-64 PR #407 — v0.4.4-draft RES-D1..D5 sample-block coverage
  extension (19 tests).
- Tag-65 PR — RES-D promotion-sequencing doc (§2.4, §3 HARD-edge,
  §4 Step 5 indefinite-deferral, §5.2, §6.2).
- Tag-66 PR #421 — RES-D items OTS-probe coverage (HD-3
  audit-coverage substrate, 22 tests).
- Tag-67 PR — v0.4.4 activation pre-mortem doc (§5 RES-D4
  failure-mode inventory, §5.2 residual analysis, §7.2 hot spot,
  §7.3 distribution).
- Tag-68 PR #432 — pre-mortem coverage test-suite (163 tests,
  per-failure-mode coverage audit-trail).

-- Reza
