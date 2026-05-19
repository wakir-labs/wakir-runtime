<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

# Wirelang-Spec v0.4.4-Draft Activation Pre-Mortem (Tag-67)

**Status:** pre-activation failure-mode inventory, doc-form only.
**Activation gate:** KW-24 cutover-T0 fired (no earlier).
**Activation policy:** sequence-promotion-only.
**Anchor draft:** [`wirelang/specs/wirelang-spec-v0-4-4-draft.md`](../../wirelang/specs/wirelang-spec-v0-4-4-draft.md).
**Owner:** Reza (Dev-Engineering-2).
**Mirror-twin:** none (this is the first activation-pre-mortem doc
for the v0.4.4 reserve-item axis; the Tag-44 Phase-3-Marathon
pre-mortem is the form-anchor pattern, but covers a different
axis — Phase-3-Cutover-Marathon, not spec-promotion).
**AR-authorisation required:** no (informative skizze in the
sense of GOVERNANCE.md §10; no audit-verdict, no normative
classification, no recommendation to defer or reorder).

---

## 1. Scope

This document is the **per-RES-Dn activation pre-mortem** for the
five reserve items RES-D1 .. RES-D5 collected in
`wirelang/specs/wirelang-spec-v0-4-4-draft.md` (`status:
post-cutover-reserve-draft`). It enumerates, for each item, the
failure modes that the activation step could trip — what could
go wrong during the per-item promotion PR, what could go wrong
post-merge, and where the mitigation anchors live.

It is **doc-form only**: no helper changes binding behaviour, no
spec frontmatter is flipped, no fixture is added. The pre-mortem
is an **informative skizze** (GOVERNANCE.md §10 pattern), not an
audit-verdict and not a recommendation to alter the Tag-65
sequence-order.

The structure follows the Tag-44 Phase-3-Marathon pre-mortem
pattern (Henrik Voss, 2026-05-18):

- Per-item failure-mode list with two classes:
  - **Class A — Technical / structural** (Ax: spec-text mismatch,
    fixture-tree clash, code-path divergence, etc.).
  - **Class B — Operative / procedural** (Bx: CEO-Triage
    sequencing miss, rollback-discipline gap, audit-trail
    omission, etc.).
- Per failure-mode: **likelihood / impact / mitigation anchor /
  detection path**.
- Aggregate-risk-map (§7) that aggregates the inventory across
  RES-D1..RES-D5 and identifies cross-item hot spots.

In scope:

- §1 — scope and posture declaration.
- §2 — RES-D1 (dual-path BIP32) failure-mode inventory (A1..A5,
  B1..B5).
- §3 — RES-D2 (`min-attenuation-depth`) failure-mode inventory.
- §4 — RES-D3 (bridge-audit 3-mode envelope) failure-mode
  inventory.
- §5 — RES-D4 (OTS-anchored multi-author registry) failure-mode
  inventory.
- §6 — RES-D5 (sharded recovery-drill leaf-projection) failure-
  mode inventory.
- §7 — aggregate-risk-map across all five items (cross-item hot
  spots, shared mitigation surfaces, residual risk after
  mitigation).

Out of scope:

- Any binding semantic change to v0.4.3 (`pre-cutover-freeze`).
- Any edit to `wirelang-spec-v0-4-4-draft.md` frontmatter or body.
- Any per-item normative-promotion **execution** (the per-item
  PR is a separate document, written at promotion-time under
  CEO-Triage hand; this doc only **inventories failure-modes**
  for those promotions).
- Any AR-authorisation request for live OTS-anchor activation
  (RES-D4 prerequisite; remains AR-Hand per ADR-0023a).
- Any audit-verdict classification, finding, or risk-rating in
  the audit sense; this is an informative skizze, not a Henrik-
  Voss audit-output.
- Schedule re-recommendation: the Tag-65 sequence-order remains
  the binding-by-default recommendation; this pre-mortem
  enumerates risks **per item** without re-ranking the schedule.

This doc is the Tag-67 follow-on to:

- Tag-63 PR #403 — v0.4.4-draft RES-D1..D5 baseline (17 tests).
- Tag-64 PR #407 — v0.4.4-draft RES-D1..D5 sample-block
  coverage extension (19 tests).
- Tag-65 PR — RES-D promotion-sequencing doc + helper + tests.
- Tag-66 PR #421 — RES-D items OTS-probe coverage (22 tests).

The Tag-44 pre-mortem (Henrik Voss, internal-audit/outbox/
2026-05-18-tag-44-pre-mortem.md) is the form-anchor; it covers
the Phase-3 cutover-marathon axis, not spec-promotion. The two
pre-mortems are complementary, not redundant.

---

## 2. RES-D1 — Identity-Substrate-Evolution (dual-path BIP32)

### 2.1 Failure-mode inventory

| Code | Failure mode | Likelihood | Impact | Mitigation anchor | Detection path |
|---|---|---|---|---|---|
| A1 | The `WAKIR_BIP32_OVERLAP_WINDOW_LEN` ENV-flag default (`256`) is committed to Pin-Pack record #1 before the federation-pair rotation policy is ratified — value-space is wrong at landing. | medium | medium | Tag-65 §4 Step 3 — rotation policy ratification is an activation-trigger condition; promotion PR must cite it. | Pre-merge: Tag-65 helper checks ratification anchor. Post-merge: Persona-Engine startup logs warn on mismatched window-len. |
| A2 | `vector-3a-rotation-overlap-dual-path.json` fixture, when added, collides with the existing `vector-3-rotation-overlap.json` shape, breaking downstream consumers that read the whole fixture-tree. | low | high | Fixture-family naming convention (Tag-64 sample established `vector-Na-...` suffix). Add fixture under same parent directory, do not rename existing fixture. | Pre-merge: hermetic fixture-load test runs against current consumers. Post-merge: 24h smoke-window monitors fixture-tree load failures. |
| A3 | Wirelang spec §3.2 → §3.2.1 insert text drifts from the draft §6.1 normative-shape during the promotion-PR rewrite (the draft uses `0.4.4-draft-RES-D1`, the promoted spec must drop the `-draft-RES-D1` suffix). | medium | medium | Tag-63 PR #403 + Tag-64 PR #407 anchor the canonical-form shape. Promotion PR diffs §6.1 → §3.2.1 line-by-line. | Pre-merge: doc-shape audit (helper checks `identity-substrate-version: 0.4.4` post-promotion, not `0.4.4-draft-RES-D1`). |
| A4 | Persona-Engine 0.5.3 production-readiness audit is closed-green, but the audit predates the dual-path implementation — the audit verdict does not actually cover the new BIP32 derivation path. | medium | high | Tag-63 audit citation is the activation-trigger anchor; the promotion PR must cite a refreshed Persona-Engine audit that explicitly covers dual-path derivation. | Pre-merge: ADR-class entry (A5 in Tag-65 §5.1) must cite the audit refresh. Post-merge: Persona-Engine startup audit-trail log shows dual-path discovery. |
| A5 | The second derivation path, once enabled, leaks key-material into federation-peer logs because the path is not under the same redaction policy as the primary path. | low | critical | Federation-pair redaction policy must be reviewed; Pin-Pack record #1 must declare both paths under redaction. | Pre-merge: explicit redaction-policy line in promotion PR. Post-merge: log-greps catch the path-prefix; Henrik Voss audit-sample. |
| B1 | CEO-Triage approves the RES-D1 promotion before the federation-pair rotation policy is ratified — the activation-trigger condition (Tag-65 §2.1) is bypassed under time pressure. | medium | medium | Tag-65 §2.1 cites the rotation policy as an activation-trigger condition. Pre-mortem inventory is the second-order reminder. | Pre-merge: Tag-65 helper subprocess (verify_promotion_sequencing_doc.py) checks Step-3 rationale anchor. |
| B2 | The promotion-PR ADR-class entry (Tag-65 §5.1 A5) is filed under an incorrect ADR number range, breaking the cross-anchor index. | low | low | ADR-naming convention is auto-enforced via the decisions/ folder pattern; the promotion PR references the ADR number explicitly in the §3.2.1 insert. | Pre-merge: ADR-numbering audit hook (Henrik Voss audit-sample pattern). |
| B3 | The 24h post-merge smoke-window is skipped because RES-D1 lands during a low-traffic window (week-end, EU holiday), and no operator is on-call to catch a regression. | medium | high | Tag-65 §4 timing recommendation (T0+7..14 days) avoids cutover-day; operator-on-call window must be scheduled before promotion. | Pre-merge: Tag-65 §4 timing cite. Post-merge: notify-log alerts on regression-pattern matches. |
| B4 | Rollback under §6.2 of Tag-65 re-cherry-picks the §6.1 reserve-text from the wrong parent commit (the v0.4.3-frozen parent, not the v0.4.4-draft parent), corrupting the freeze-seal baseline. | low | critical | Tag-58 freeze-seal probe is the canonical guard. Rollback procedure must read from `wirelang-spec-v0-4-4-draft.md@HEAD~1` of the promotion PR. | Pre-merge: rollback-rehearsal step (optional, recommended for first promotion). Post-revert: Tag-58 freeze-seal probe re-runs. |
| B5 | RES-D1 promotion silently lands without updating the Tag-63 + Tag-64 audit suites (Tag-65 §5.1 A3), leaving the `is_draft=True` markers stale and producing future audit false-positives. | medium | low | Tag-65 §5.1 A3 is the explicit acceptance criterion. Audit suites under `tests/audit/` carry `is_draft` flags that must flip post-promotion. | Pre-merge: A3 audit hook (Tag-65 helper coverage). |

### 2.2 RES-D1 residual risk

After mitigation, the residual risk profile for RES-D1 is
**medium-low**. The Identity-Substrate surface is high-trust,
but the dual-path layout is reversible (the default emit-path is
unchanged), so a post-merge regression has a clean rollback story.
The dominant residual risk is A4 (audit-coverage drift): the
Persona-Engine audit refresh must explicitly cover the new
derivation path, not just inherit the prior audit verdict.

---

## 3. RES-D2 — Capability-Token-Refinements (`min-attenuation-depth`)

### 3.1 Failure-mode inventory

| Code | Failure mode | Likelihood | Impact | Mitigation anchor | Detection path |
|---|---|---|---|---|---|
| A1 | Catalogue-row-17 (`min-attenuation-depth`) is allocated in v0.4.4 §3 but not back-allocated in v0.4.3 §3 carry-forward, breaking the catalogue cross-spec invariant. | medium | medium | Tag-65 §5.2 RES-D2 acceptance: row-17 added to both v0.4.3 §3 and v0.4.4 §3. | Pre-merge: catalogue-row-numbering audit hook. |
| A2 | The `predicate-interval-empty` error is emitted by the producer but not by the verifier — single-sided enforcement creates a silent acceptance gap. | medium | high | Promotion-PR producer + verifier code must land together; Tag-65 §2.2 promotion-touch surface cites both. | Pre-merge: catalogue-row negative-test (Tag-65 §5.2 RES-D2). Post-merge: federation-diff `n3_chain_walker` reports asymmetry. |
| A3 | The federation-diff `n3_chain_walker` policy-layer approximation is not deprecated in lockstep with the wire-level predicate, creating two parallel enforcement layers that drift over time. | medium | high | Tag-65 §2.2 activation-trigger: deprecation path must be agreed by CEO-Triage before promotion. | Pre-merge: deprecation-decision ADR cite. Post-merge: federation-diff log audit. |
| A4 | The `under-attenuated` verifier verdict collides with an existing verdict name in the verifier's verdict-enum, causing serialization-incompat downstream. | low | medium | Verdict-enum is enumerated in the verifier spec; promotion-PR audit checks for collision. | Pre-merge: enum-uniqueness audit hook. |
| A5 | The catalogue-row-17 sample (Tag-64) is correct in shape but cites a stale row-16 (`max-attenuation-depth`) example that has since been edited, producing a documentation-drift. | low | low | Catalogue carry-forward audit (Tag-64 helper). | Pre-merge: doc-shape audit. |
| B1 | CEO-Triage approves RES-D2 promotion in parallel with RES-D1, overloading the post-merge smoke window — two promotion regressions could overlap and confuse triage. | medium | medium | Tag-65 §3 DAG declares RES-D1, RES-D2, RES-D3 as parallel-allowed; Tag-65 §4 schedule sequences them as 3 / 2 / 1 (D3 first). The pre-mortem reiterates that parallel-allowed is not parallel-recommended. | Pre-merge: promotion-PR cite of Tag-65 §4 timing recommendation. |
| B2 | The federation-diff deprecation path requires a Júlia / Selin coordination decision; if that decision is not synchronised, the promotion PR lands without the policy-layer deprecation, producing the §3.1 A3 drift. | medium | high | Cross-team coordination is a Tag-65 §2.2 activation-trigger condition. | Pre-merge: cross-team decision-anchor cite. |
| B3 | The post-merge regression-detection signal for RES-D2 is the federation-diff log, which is not under continuous monitoring during the EU off-hours window. | low | high | Notify-log alerting must cover federation-diff regression patterns during the 24h smoke window. | Pre-merge: notify-log alert-pattern audit. Post-merge: alert-trigger smoke-test. |
| B4 | Rollback of RES-D2 leaves catalogue-row-17 allocated in v0.4.3 §3 but unallocated in v0.4.4 §3, producing the inverse of the A1 invariant violation. | low | medium | Rollback procedure (Tag-65 §6.2 step 3) must revert both catalogue allocations atomically. | Post-revert: catalogue-row-numbering audit re-run. |
| B5 | The Henrik Voss audit-sample misses RES-D2 in the post-promotion audit-cycle because the audit-sample rotation lands on RES-D3 by chance. | low | low | Audit-sample coverage is risk-weighted (ADR-0014 + ADR-0025 audit pattern); high-impact items get priority. | Audit-sample rotation log; Henrik Voss own discipline. |

### 3.2 RES-D2 residual risk

After mitigation, the residual risk profile for RES-D2 is
**medium**. The dominant residual risk is A3 (policy-layer
mirror drift): the wire-level predicate only earns its keep if
the federation-diff approximation is retired in lockstep. If
both layers persist, the silent double-spec creates a
maintenance liability that compounds over time.

---

## 4. RES-D3 — Bridge-Audit-Cleanup (3-mode envelope)

### 4.1 Failure-mode inventory

| Code | Failure mode | Likelihood | Impact | Mitigation anchor | Detection path |
|---|---|---|---|---|---|
| A1 | Pin-Pack record #10 value-space lists three modes (`python`, `rust-native`, `shim-fallback`) but the precedence rule (`rust-native > shim-fallback > python`) is mis-encoded in the spec text. | low | high | Tag-65 §2.3 substrate-already-pinned cites the precedence rule explicitly. Promotion PR diff against draft §6.3. | Pre-merge: doc-shape audit (precedence string match). Post-merge: bridge-audit writer startup logs the active mode. |
| A2 | The Rust-native bridge-audit writer 14-day production-stability window closes-green on metrics, but a latent regression in shim-fallback restart-path is not exercised during the window. | medium | high | Tag-65 §2.3 activation-trigger: 14-day stability window is a precondition. Production-stability monitor must include shim-fallback restart traces. | Pre-merge: stability-window audit-anchor cite. Post-merge: shim-fallback restart smoke-test. |
| A3 | The bridge-audit envelope `outer-metadata.mode` field is optional in the JSON schema but mandatory in the spec text — schema and spec disagree, producing silently-malformed envelopes. | low | high | Tag-65 §5.2 RES-D3 acceptance: negative-test rejects envelope when `outer-metadata.mode` absent. | Pre-merge: schema-vs-spec audit. Post-merge: envelope-rejection metric. |
| A4 | The bridge-audit writer image-build pipeline (cited as activation-trigger) is enforcing under main-branch protection, but the pipeline pinning is on a stale image-tag — image-drift surfaces post-promotion. | medium | medium | Tag-65 §2.3 activation-trigger cites the image-build pipeline. Image-pin refresh must precede promotion. | Pre-merge: image-pin audit hook (Tag-66 OTS-probe). |
| A5 | The restart-rule (under §6.3 of the draft) interacts with the operator runbook's graceful-degradation switch procedure: switching modes mid-flight produces a partial-emit envelope that the verifier cannot reconstruct. | low | high | Operator runbook addition (Tag-65 §2.3 promotion-touch surface). Mode-switch must drain in-flight envelopes before applying. | Pre-merge: runbook-completeness audit. Post-merge: partial-emit metric. |
| B1 | RES-D3 is recommended as Step 1 in the Tag-65 schedule (lowest surface change), but CEO-Triage reorders to start with RES-D1 — RES-D1 has higher rollback complexity, raising the cumulative risk if both early-promotion steps regress. | low | medium | Tag-65 §4 schedule is non-binding but the rationale (lowest-surface-first) is informative. Pre-mortem inventory reiterates the rationale. | Pre-merge: CEO-Triage decision-anchor cite. |
| B2 | The bridge-audit writer image-build pipeline pinning is under Tomás-Pin-Pack discipline; Reza cannot edit it. Coordination miss with Tomás delays promotion. | medium | low | Tag-65 §7.2 declares Pin-Pack as out-of-Sandbox-scope. Cross-team handoff is normal mode. | Pre-merge: cross-team decision-anchor. |
| B3 | The 14-day stability window is reset by a sub-fix landing in the Rust-native writer during the window — operator interpretation of "window closed-green" diverges from the spec intent. | low | medium | Stability-window definition must be tight (no resets shorter than 7 days). Tag-65 §2.3 activation-trigger language is precise. | Pre-merge: window-definition audit. |
| B4 | Rollback of RES-D3 leaves Pin-Pack record #10 in the three-mode value-space, but the spec §4.1.10a sub-row is reverted — Pin-Pack drift. | low | high | Rollback procedure must revert Pin-Pack value-space atomically. | Post-revert: Pin-Pack consistency audit. |
| B5 | The graceful-degradation switch procedure (operator runbook) is authored at promotion-time but not exercised in a live drill — first live use post-promotion is the first real test. | medium | medium | Pre-promotion drill is recommended but not required. | Post-merge: drill-execution audit. |

### 4.2 RES-D3 residual risk

After mitigation, the residual risk profile for RES-D3 is
**medium-low**. The dominant residual risk is A2 (latent
regression in shim-fallback restart-path): the production-
stability window must explicitly exercise the shim-fallback
restart, not just measure rust-native uptime. The 14-day
window is necessary but not sufficient.

---

## 5. RES-D4 — Schema-Registry-v2-Prep (OTS-anchored multi-author)

### 5.1 Failure-mode inventory

| Code | Failure mode | Likelihood | Impact | Mitigation anchor | Detection path |
|---|---|---|---|---|---|
| A1 | RES-D4 promotion is attempted before AR-authorisation has crossed live OTS-anchor activation from audit-only stub (Tag-60) to live-emit — the `registry-pointer-frame` verifier-acceptance rule fails at-issuance because the OTS-anchor does not resolve. | medium | critical | Tag-65 §4 Step 5 explicitly marks RES-D4 as `indefinite-deferral`, AR-authorisation per ADR-0023a required. | Pre-merge: AR-authorisation anchor cite. Pre-merge: live-OTS resolver smoke-test. |
| A2 | Federation-peer-identity catalogue lists two peers, but the verifier-acceptance rule treats the catalogue as live (with TOCTOU on peer-rotation) — a peer rotating mid-verification produces a transient acceptance gap. | low | high | Verifier-acceptance rule must read the catalogue snapshot at issuance, not at verification. Tag-65 §2.4 promotion-touch surface cites this. | Pre-merge: TOCTOU audit on verifier-acceptance code. |
| A3 | OTS-anchor courtesy-budget (CFO ratification cited in Tag-65 §2.4) is allocated, but the per-anchor cost exceeds budget due to network-fee volatility; promotion lands but anchoring is rate-limited, producing a `pending-anchor` queue. | medium | medium | Courtesy-budget allocation must include a 2x headroom factor. Tag-65 §2.4 promotion-touch surface cites CFO ratification. | Pre-merge: budget-allocation review. Post-merge: anchor-queue depth metric. |
| A4 | NATS-KV bucket `route_registry` schema extension (`registry-pointer-record` key-shape) collides with existing key-shape used by `route_registry_nats_kv_backend.py` for federation-pair discovery. | low | high | Schema extension must be a strict superset of the existing key-shape. Tag-65 §2.4 substrate-already-pinned references the existing backend. | Pre-merge: schema-extension compatibility audit. Post-merge: NATS-KV consistency check. |
| A5 | Companion spec `wirelang/specs/schema-registry-spec.md` revised to v2, but the v1 → v2 migration path is not documented — existing v1 consumers break silently on first v2-registry encounter. | medium | high | Companion-spec revision must include a migration appendix. Tag-65 §5.2 RES-D4 acceptance must extend to v1→v2 migration test. | Pre-merge: migration-appendix audit. Post-merge: v1-consumer compatibility smoke. |
| B1 | AR-authorisation for live OTS-anchor activation is granted asynchronously, and RES-D4 promotion is scheduled before the authorisation lands — promotion PR opens but cannot complete. | low | medium | Tag-65 §4 Step 5 marks indefinite-deferral; promotion is gated by AR-authorisation. | Pre-merge: AR-authorisation anchor must be present. |
| B2 | The "minimum two peers" condition (Tag-65 §2.4 activation-trigger) is interpreted loosely — two peers are claimed but the second peer is a test-fixture, not a real federation peer. | medium | high | Tag-65 §2.4 activation-trigger language is precise: "minimum two peers identified". Pre-mortem inventory reiterates that "identified" means "production-active, not fixture". | Pre-merge: federation-peer roster audit. |
| B3 | CFO ratification of OTS-anchor courtesy-budget is granted but the budget envelope is unclear about post-promotion costs (only initial anchoring is budgeted). | medium | medium | CFO ratification must include explicit post-promotion run-rate. | Pre-merge: budget-envelope audit. |
| B4 | Rollback of RES-D4 leaves the NATS-KV bucket extension in place (forward-compatible schema), but the spec §8.5 is reverted — schema-vs-spec drift. | low | high | Rollback procedure must revert NATS-KV bucket schema atomically (or document the forward-compat schema-only state explicitly). | Post-revert: schema-vs-spec audit. |
| B5 | Henrik Voss audit-sample misses RES-D4 in the post-promotion audit-cycle, but RES-D4 is the highest-impact item due to live-OTS dependency — audit-coverage gap. | low | critical | Audit-sample must prioritise live-OTS-dependent items per ADR-0025 risk-weighted rotation. | Audit-sample rotation log. |

### 5.2 RES-D4 residual risk

After mitigation, the residual risk profile for RES-D4 is
**high** — the only RES-Dn item that warrants this rating. The
dominant residual risk is the conjunction of A1 (live-OTS-anchor
dependency), B2 (federation-peer roster integrity), and B5
(audit-coverage gap on a critical item). Tag-65 §4 Step 5
explicitly recommends indefinite-deferral; the pre-mortem
reaffirms that this is the right default. RES-D4 promotion
without all three mitigation anchors in place is the highest-
risk single step in the v0.4.4-draft activation surface.

---

## 6. RES-D5 — Recovery-Drill-Leaf-Projection-v2 (sharded)

### 6.1 Failure-mode inventory

| Code | Failure mode | Likelihood | Impact | Mitigation anchor | Detection path |
|---|---|---|---|---|---|
| A1 | The `shard-id` / `shard-count` encoding clashes with an existing recovery-drill envelope field, causing back-compat envelopes to mis-parse. | low | high | Encoding must reserve a new field, not overload an existing one. Tag-65 §2.5 substrate-already-pinned cites single-shard back-compat. | Pre-merge: envelope-parsing audit. Post-merge: back-compat smoke. |
| A2 | The canonical-concat invariant (multi-shard envelope concatenation produces the single-shard byte-equivalent) holds in unit tests but fails on edge-case shard-count values (`shard-count: 1` overflow, `shard-count: 256+`). | medium | medium | Tag-65 §5.2 RES-D5 acceptance: concat-byte-equality invariant test. Range-test must cover edge cases. | Pre-merge: edge-case test coverage. Post-merge: drill-execution byte-comparison. |
| A3 | The `incomplete-projection` verdict is emitted on observing only `shard-id: 0` of an `n > 1` drill, but the verifier does not retry: the verdict is treated as terminal even when later shards may arrive. | medium | medium | Verifier must distinguish "incomplete-now" from "incomplete-final". Tag-65 §2.5 promotion-touch surface cites the verdict path. | Pre-merge: retry-semantics audit. Post-merge: drill-completion metric. |
| A4 | `WAKIR_RECOVERY_DRILL_SHARD_COUNT` ENV-flag default (`1`) is correct, but Pin-Pack record entry for the flag is missing — single-shard back-compat lands but multi-shard is silently disabled. | low | low | Pin-Pack record must be allocated for the new ENV-flag. Tag-65 §2.5 promotion-touch surface cites the ENV-flag. | Pre-merge: Pin-Pack record audit. |
| A5 | Soft-dependency on RES-D1 (fixture-tree co-location) is violated: RES-D5 promotes before RES-D1, forcing a fixture-tree reshuffle PR mid-promotion. | medium | low | Tag-65 §3 DAG soft-edge cites RES-D1 → RES-D5. Sequence-order recommendation respects this. | Pre-merge: Tag-65 §4 schedule cite. |
| B1 | The Phase-4 sharding-day plan is not ratified when RES-D5 promotes — the multi-shard envelope spec lands but no sharding event is scheduled, producing dead spec surface. | medium | low | Tag-65 §2.5 activation-trigger: Phase-4 sharding-day plan must be ratified. | Pre-merge: sharding-day plan ratification anchor cite. |
| B2 | Phase-3c recovery-drill substrate frozen-green status is asserted, but a Tag-53 v0.4.3 parent regression is in-flight at promotion time — RES-D5 inherits the regression. | low | high | Tag-65 §2.5 activation-trigger: Phase-3c substrate frozen-green. Phase-3c parent must be regression-free at promotion. | Pre-merge: Phase-3c parent regression check. |
| B3 | CEO-Triage approves RES-D5 promotion in parallel with RES-D1, violating the soft-edge — fixture-tree reshuffle PR lands but breaks an unrelated downstream consumer of the fixture-tree. | medium | medium | Tag-65 §4 schedule sequences RES-D5 after RES-D1 (T0+14..28 days, after RES-D1). Pre-mortem reiterates. | Pre-merge: CEO-Triage decision-anchor cite. |
| B4 | Rollback of RES-D5 leaves the `shard-count: 1` back-compat path enabled but reverts the multi-shard verifier code — producing a "fail-on-multi-shard, accept-single-shard" partial state that is semantically confusing. | low | medium | Rollback must be atomic across spec + verifier. Tag-65 §6.2 step 3 rollback procedure. | Post-revert: verifier behaviour smoke. |
| B5 | The recovery-drill verifier-code change is shipped without operator training — first sharding-day execution post-promotion finds operators unfamiliar with the `incomplete-projection` verdict. | medium | low | Operator runbook must be authored alongside promotion PR. | Post-promotion: training-anchor cite (out-of-sandbox). |

### 6.2 RES-D5 residual risk

After mitigation, the residual risk profile for RES-D5 is
**low-medium**. The dominant residual risk is B1 (dead spec
surface): if Phase-4 sharding-day is not actually scheduled, the
multi-shard envelope adds spec-text without operational use.
Tag-65 §2.5 activation-trigger correctly requires the sharding-
day plan ratification before promotion, but the pre-mortem
reiterates that this is the load-bearing prerequisite.

---

## 7. Aggregate-Risk-Map

### 7.1 Cross-item failure-mode aggregation

| Mode-family | Items affected | Worst residual rating | Mitigation-surface |
|---|---|---|---|
| Spec-text drift between draft §6 and promoted spec body | All five (A3 in §2, §4; A1 in §3, §4) | medium | Tag-65 §5 acceptance criteria + helper audit |
| Fixture-tree clash on family-naming | RES-D1 (A2), RES-D5 (A5 soft) | low (after RES-D1 → RES-D5 ordering) | Tag-65 §3 DAG soft-edge |
| ENV-flag value-space drift between Pin-Pack and spec | RES-D1 (A1), RES-D5 (A4) | low | Pin-Pack audit pattern (Tomás-led) |
| Cross-layer enforcement asymmetry (producer vs. verifier) | RES-D2 (A2), RES-D5 (A3) | medium | Promotion-PR atomic-code-change discipline |
| Audit-coverage gap post-promotion | RES-D1 (A4), RES-D4 (B5) | high (RES-D4 only) | Risk-weighted audit-sample rotation (ADR-0025) |
| Live-OTS dependency | RES-D4 (A1) | critical | AR-authorisation per ADR-0023a |
| 24h post-merge regression detection gap | RES-D1 (B3), RES-D2 (B3) | high | Notify-log alert coverage |
| Rollback-atomicity miss | RES-D2 (B4), RES-D3 (B4), RES-D4 (B4), RES-D5 (B4) | medium | Tag-65 §6.2 step 3 rollback procedure tightening |
| Cross-team coordination miss (Tomás Pin-Pack, Selin federation, CFO budget) | RES-D2 (B2), RES-D3 (B2), RES-D4 (B3) | medium | Standard cross-team handoff discipline |
| Schedule-order deviation under CEO-Triage discretion | RES-D2 (B1), RES-D3 (B1), RES-D5 (B3) | medium | Tag-65 §4 schedule is non-binding by design |

### 7.2 Cross-item hot spots

Three cross-item patterns warrant elevated attention:

- **Rollback-atomicity hot spot.** Four of five items (RES-D2,
  RES-D3, RES-D4, RES-D5) have a B4 failure-mode about rollback
  leaving Pin-Pack / NATS-KV / catalogue state non-atomic with
  spec state. The Tag-65 §6.2 rollback procedure is currently
  text-only; a rollback-rehearsal step (optional, recommended
  for first promotion) would close this hot spot.
- **Cross-layer enforcement asymmetry hot spot.** RES-D2 (A2)
  and RES-D5 (A3) both describe failure modes where the producer
  / verifier code change lands asymmetrically. The promotion-PR
  discipline of atomic-code-change (producer + verifier in same
  PR) is the common mitigation; the pre-mortem reiterates that
  this is a per-promotion gate, not a one-time setup.
- **RES-D4 isolation hot spot.** RES-D4 is the only item with a
  critical residual rating (high). It is also the only item
  with a HARD dependency on live OTS-anchor activation
  (ADR-0023a AR-authorisation). The Tag-65 §4 Step 5
  indefinite-deferral recommendation is the right default; the
  pre-mortem reaffirms that RES-D4 should not be promoted
  before AR-authorisation lands, even if the other four items
  have promoted green.

### 7.3 Residual-risk distribution

| Item | Residual rating | Dominant residual driver |
|---|---|---|
| RES-D1 | medium-low | A4 audit-coverage drift (dual-path) |
| RES-D2 | medium | A3 policy-layer mirror drift |
| RES-D3 | medium-low | A2 shim-fallback latent regression |
| RES-D4 | high | A1 + B2 + B5 (live-OTS + peer-roster + audit) |
| RES-D5 | low-medium | B1 dead spec surface (sharding-day) |

The aggregate residual-risk profile is **medium**, dominated by
RES-D4. The other four items, if promoted in the Tag-65 §4
recommended order with the mitigation anchors in place, present
a manageable risk surface. The recommendation **not** to
re-rank the schedule remains; this pre-mortem is informative
input to CEO-Triage, not a counter-recommendation.

### 7.4 Cross-anchor

- ADR-0007 (Persona-Engine Pin-Pack discipline).
- ADR-0014 (Audit-Sample Risk-Weighted Rotation).
- ADR-0023a (Sandbox-Boundary).
- ADR-0023b (Operator-Hand vs. AR-authorisation).
- ADR-0025 (Three-axis performance measurement).
- GOVERNANCE.md §10 (informative skizze vs. audit-verdict).
- Tag-44 internal-audit Phase-3-Marathon pre-mortem
  (Henrik Voss, form-anchor pattern).
- Tag-58 PR — v0.4.3 freeze-seal probe.
- Tag-60 PR #382 — OTS pre-activation stub.
- Tag-63 PR #403 — v0.4.4-draft RES-D1..D5 baseline (Reza, 17 tests).
- Tag-64 PR #407 — v0.4.4-draft RES-D1..D5 sample-block coverage
  extension (Reza, 19 tests).
- Tag-65 PR — RES-D promotion-sequencing doc + helper + tests (Reza).
- Tag-66 PR #421 — RES-D items OTS-probe coverage (Reza, 22 tests).

-- Reza
