# Quality-Gate — Pre-Cutover Acceptance-Pyramide Run-Order (Tag-57)

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Active — canonical run-order map for the six-layer Acceptance-Pyramide across Welle-1..Welle-7 of the Phase-3c-Welle-Marathon. |
| Phase | 3c (pre-cutover): per-Welle sequencing contract for the 167-hermetic-test acceptance-pyramide. |
| Source | Tag-57 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode); roll-up of Tag-53 (Pyramide-doc-refresh) + Tag-54 (Marathon-Final-Acceptance consolidation) + Tag-55 (Cosign-Strict-Mode G3+G5) + Tag-56 (Live-Verify-Gate, watch-day-practice-run, Rollback-workflow, engine-0.5.2-audit); ADR-0066 four-Wochen-Cadence (KW-24..KW-27); ADR-0058 §Nachtrag (live-VM-acceptance-lane operator-hand boundary). |
| Date | 2026-05-19 (Tag-57) |
| Test-File (this doc's hermetic anchor) | `tests/ci/test_pyramide_run_order_doc_tag57.py` |
| Helper (verdict aggregator) | `tooling/ci/aggregate_pyramide_run_order_verdict.py` |
| Companion (6-Layer Pyramide structural map) | `docs/quality-gates/marathon-acceptance-pyramide.md` (Tag-53) |
| Companion (Final-Acceptance consolidated DoD) | `docs/quality-gates/phase-3-marathon-final-acceptance.md` (Tag-54) |
| Companion (Pre-Cutover-Final-Sanity-Gate runbook) | `docs/ci/pre-cutover-final-sanity-gate-runbook.md` (Tomas Tag-53) |
| Companion (Marathon-Live-Verify-Gate) | `.github/workflows/marathon-final-acceptance-live-verify.yml` (Amara Tag-56) |
| Companion (Doppel-Welle-4-5 spec) | `docs/quality-gates/phase-3c-doppel-welle-4-5.md` |
| Companion (Doppel-Welle-6-7 spec) | `docs/quality-gates/phase-3c-doppel-welle-6-7.md` |
| Audit-Boundary | Zone N: this doc is QA-domain artefact (run-order invariants, system-behaviour sequencing). Henrik consumes the per-Welle run-order table + the failure-mode-cascade-matrix as Audit-Evidence-Index. No overlap with WAT/OTS Audit-Trail or governance-layer compliance. |

## 1. Scope, anchors, and what this doc is not

### 1.1 Scope

This document is the **canonical run-order specification** for the
six-layer Acceptance-Pyramide across the seven Welle-slots of the
Phase-3c-Welle-Marathon (ADR-0066 four-Wochen-Cadence, KW-24 -> KW-27).

It captures, in a single artefact:

- **§2** — 6-Layer inventory with current Tag-57 test-counts.
- **§3** — Per-Welle (Welle-1..Welle-7) run-order: which layer fires
  Pre-Welle (Monday 05:00 UTC), which fires Welle-Day (Wednesday), and
  which fires Post-Welle (Friday sign-off).
- **§4** — Cross-Layer-Dependency-Edges: the explicit Layer-A -> Layer-B
  dependency-graph that the run-order respects.
- **§5** — Run-Sequencing-Pattern: which edges are parallel-safe and
  which are serial-required.
- **§6** — Failure-Mode-Cascade-Matrix: if Layer-X fails on Welle-N,
  what is triggered (block-downstream, retry-isolated, escalate-AR).
- **§7** — Acceptance-Verdict-Aggregation: how per-Welle and Global
  verdicts are computed from the six-layer outputs.
- **§8** — Sandbox-Boundary: what this doc-class artefact governs vs.
  what is operator-hand-only (live-VM-acceptance-lane).

### 1.2 Anchors (verified Tag-57)

| Anchor | Source | Role |
|---|---|---|
| ADR-0058 §Nachtrag | `decisions/0058-*.md` | Live-VM-acceptance-lane operator-hand boundary. |
| ADR-0066 | `decisions/0066-*.md` | Four-Wochen-Cadence KW-24..KW-27, Doppel-Welle structure. |
| Marathon-Final-Acceptance-Spec | `docs/quality-gates/phase-3-marathon-final-acceptance.md` | Five-surface conjunction (Surface-1..5 + Surface-Pre). |
| 6-Layer Pyramide structural map | `docs/quality-gates/marathon-acceptance-pyramide.md` | Layer-1..6 layer-definitions and test-files. |

### 1.3 What this doc is NOT

- This doc does **not** redefine the layer-contracts (those live in
  `marathon-acceptance-pyramide.md`).
- This doc does **not** redefine AC-1..AC-5 (those live in the
  marker workflow).
- This doc does **not** replace the live-VM-acceptance-lane runbook
  (operator-hand-territory).
- This doc does **not** introduce new tests or layers; it sequences
  what already exists on `main` as of Tag-56 (PR #358 landed).

## 2. 6-Layer Inventory (Tag-57 snapshot)

The Acceptance-Pyramide consists of six hermetic test-layers,
totaling 167 tests as of Tag-57:

| Layer | Name | Tag-Anchor | Test-File | Test-Count | Role in run-order |
|---|---|---|---|---|---|
| 1 | State-Machine | Tag-40 | `tests/phase_3c/test_phase_3_final_regression.py` | 28 | Aggregate marker-emit-gate, fires Post-Welle-7 (Global). |
| 2 | Per-Day | Tag-41 | `tests/phase_3c/test_cutover_day_e2e_drill.py` | 45 | Per-Welle Cutover-Mittwoch sign-off-record producer. |
| 3 | Marathon | Tag-43 | `tests/phase_3c/test_marathon_schluss_acceptance_drill.py` | 27 | Four-Wochen-sequence threading, fires Post-Welle-7 (Global). |
| 4 | Anti-Pattern | Tag-44 | `tests/phase_3c/test_marathon_anti_patterns.py` | 20 | Control-plane rejection (10 AP-axes), fires Pre-Welle-1 once + before each Welle-N. |
| 5 | Pre-Mortem Coverage | Tag-45 | `tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py` | 25 | Failure-mode-coverage attestation, fires Pre-Welle-1 once. |
| 6 | Defence-in-Depth Run-Suite | Tag-52 | `tests/phase_3c/test_defence_in_depth_layer_6.py` | 22 | A1 cross-Welle defence composition, fires Pre-Welle-1 once + smoke-rerun before each Doppel-Welle. |
| Sum | | | | **167** | |

Counts are **descriptive**, not prescriptive: the contract is the
per-layer invariant (per `marathon-acceptance-pyramide.md` §2), not
the cardinality. A future test-add in any layer does not invalidate
this doc; only a layer-rename or layer-removal does.

## 3. Per-Welle Run-Order (Welle-1 .. Welle-7)

The Phase-3c-Welle-Marathon consists of seven Welle-slots distributed
across four KW (KW-24..KW-27) per ADR-0066:

| Welle | KW | Cutover-Mittwoch (ADR-0066) | Sign-off-Freitag |
|---|---|---|---|
| Welle-1 | KW-24 | 2026-06-10 | 2026-06-12 |
| Welle-2 | KW-24 | 2026-06-10 (Doppel-Welle-1+2) | 2026-06-12 |
| Welle-3 | KW-25 | 2026-06-17 | 2026-06-19 |
| Welle-4 | KW-26 | 2026-06-24 | 2026-06-26 |
| Welle-5 | KW-26 | 2026-06-24 (Doppel-Welle-4+5) | 2026-06-26 |
| Welle-6 | KW-27 | 2026-07-01 | 2026-07-03 |
| Welle-7 | KW-27 | 2026-07-01 (Doppel-Welle-6+7) | 2026-07-03 |

Note: KW-24/KW-26/KW-27 carry Doppel-Wellen (two Wellen on one
Cutover-Mittwoch with focus-MODUL disjointness enforced by Layer-1
and Layer-6). KW-25 carries a single Welle.

### 3.1 Per-Welle run-order pattern

For each Welle-N, the run-order is:

```
Pre-Welle-N      (Monday 05:00 UTC, before Cutover-Mittwoch)
   |
Welle-N-Day      (Wednesday, Cutover-Mittwoch)
   |
Post-Welle-N     (Friday 17:00 CEST, sign-off-Freitag)
```

The per-Welle layer-firing matrix is:

| Layer | Pre-Welle-N | Welle-N-Day | Post-Welle-N |
|---|---|---|---|
| Layer-1 (State-Machine) | smoke-subset (structural-only, hermetic) | n/a | full-suite (Post-Welle-7 ONLY: aggregate marker-emit-gate) |
| Layer-2 (Per-Day) | dry-run-fixtures (hermetic) | live-VM-acceptance-lane (operator-hand, §8) + hermetic-shadow | sign-off-record validation (per-Welle-N) |
| Layer-3 (Marathon) | n/a | n/a | full-suite (Post-Welle-7 ONLY: four-Wochen-sequence threading) |
| Layer-4 (Anti-Pattern) | full-suite (Pre-Welle-1 ONLY) + smoke-rerun (Pre-Welle-N>=2) | n/a | n/a |
| Layer-5 (Pre-Mortem Coverage) | full-suite (Pre-Welle-1 ONLY) | n/a | n/a |
| Layer-6 (Defence-in-Depth) | full-suite (Pre-Welle-1 ONLY) + smoke-rerun before each Doppel-Welle (Pre-Welle-2, Pre-Welle-5, Pre-Welle-7) | n/a | n/a |

Rationale:

- **Layer-1 and Layer-3** fire **only** Post-Welle-7 (Global), because
  their contract is aggregate over the full seven-record sequence;
  running them mid-marathon would require synthetic record-padding.
- **Layer-2** fires per Welle-N, producing the per-Welle sign-off-
  record consumed by Layer-1 and Layer-3 at Post-Welle-7.
- **Layer-4, Layer-5, Layer-6** are control-plane structural attestations;
  their contracts are time-invariant within the four-Wochen-Cadence,
  so a single Pre-Welle-1 fire suffices for the marathon. Layer-4 and
  Layer-6 get smoke-reruns to catch drift introduced by intra-marathon
  PRs (e.g. a substrate refactor mid-marathon that lands a regression
  on an anti-pattern axis or a defence-layer).

### 3.2 Per-Welle run-order table (canonical)

| Welle | Pre-Welle (Mon 05:00 UTC) | Welle-Day (Wed) | Post-Welle (Fri 17:00 CEST) |
|---|---|---|---|
| Welle-1 | L4-full, L5-full, L6-full, L1-smoke, L2-dryrun | L2-live (operator-hand) + L2-shadow | L2-record-validation |
| Welle-2 | L4-smoke, L6-smoke (Doppel-Welle entry), L1-smoke, L2-dryrun | L2-live (operator-hand) + L2-shadow | L2-record-validation |
| Welle-3 | L4-smoke, L1-smoke, L2-dryrun | L2-live (operator-hand) + L2-shadow | L2-record-validation |
| Welle-4 | L4-smoke, L1-smoke, L2-dryrun | L2-live (operator-hand) + L2-shadow | L2-record-validation |
| Welle-5 | L4-smoke, L6-smoke (Doppel-Welle entry), L1-smoke, L2-dryrun | L2-live (operator-hand) + L2-shadow | L2-record-validation |
| Welle-6 | L4-smoke, L1-smoke, L2-dryrun | L2-live (operator-hand) + L2-shadow | L2-record-validation |
| Welle-7 | L4-smoke, L6-smoke (Doppel-Welle entry), L1-smoke, L2-dryrun | L2-live (operator-hand) + L2-shadow | **L1-full + L3-full** + L2-record-validation (Global Acceptance-Verdict) |

The **Global Acceptance-Verdict** fires at Post-Welle-7 only,
after L1-full (aggregate marker-emit-gate) and L3-full (four-Wochen-
sequence threading) both pass over the seven sign-off-records
produced by L2 across Welle-1..Welle-7.

## 4. Cross-Layer-Dependency-Edges (Dep-Graph)

The six layers form a **directed acyclic dependency-graph**. An edge
`Layer-A -> Layer-B` means: Layer-B's contract assumes Layer-A's
substrate exists and is well-defined. A failure on Layer-A may
invalidate Layer-B's run.

### 4.1 Edge inventory

| Edge | Type | Description |
|---|---|---|
| L2 -> L1 | data-producer | L2 produces the per-Welle sign-off-record that L1 consumes at the aggregate-level. |
| L2 -> L3 | data-producer | L3 threads the seven L2-records into the four-Wochen-sequence. |
| L1 -> L3 | predicate-consumer | L3 fires the marker-emit-gate (AC-1..AC-5) defined and asserted by L1. |
| L1 -> L4 | substrate-existence | L4 asserts the marker-emit-gate rejects ten anti-patterns; assumes the gate exists (L1). |
| L1..L4 -> L5 | coverage-introspection | L5 attests the union of L1..L4 covers the 23 Pre-Mortem failure-modes; assumes all four substrates exist. |
| L1..L4 -> L6 | defence-composition | L6 composes four A1 defence-layers from L1 (substrate-disjointness), L2 (per-day fixtures), L4 (anti-pattern axes), L5 (coverage); assumes all exist. |
| L6 -> L1 | dynamic-cross-check | L6's defence-in-depth smoke-rerun cross-checks Doppel-Welle disjointness at runtime; feeds back into L1's aggregate-level assumption. |

### 4.2 Dep-graph (text form)

```
                    L2  ----+
                    |       |
                    v       v
              +---> L1 ---> L3
              |     |
              |     v
              +---- L4
              |     |
              |     v
              +---> L5
              |
              +---> L6 ---+
                          |
                          +--> L1 (dynamic cross-check)
```

### 4.3 Acyclicity

The graph is a DAG modulo the L6 -> L1 dynamic-cross-check edge,
which is **not a substrate-existence edge** (L1 exists independently
of L6) but a **runtime feedback edge** (L6 asserts L1's disjointness
claim at smoke-rerun time). This is not a cycle in the substrate-
existence sense; the substrate-existence subgraph is a strict DAG
with topological order: L2 -> L1 -> L4 -> L5 -> L3 / L6.

## 5. Run-Sequencing-Pattern (parallel-safe vs serial-required)

### 5.1 Pre-Welle-1 (Marathon-entry)

**Serial-required:**
- L1-smoke MUST run before L4-full (L4 asserts marker-emit-gate exists).
- L1-smoke + L2-dryrun + L4-full MUST run before L5-full (L5 attests
  L1..L4 coverage).
- L1-smoke + L2-dryrun + L4-full MUST run before L6-full (L6 composes
  L1..L4).

**Parallel-safe:**
- L4-full and L5-full and L6-full CAN run in parallel once L1-smoke and
  L2-dryrun complete (they are read-only over the substrate).
- L1-smoke and L2-dryrun CAN run in parallel (no edge between them at
  smoke-level; the L2 -> L1 edge is data-producer at full-suite-level
  only, post-Welle-7).

### 5.2 Pre-Welle-N (N >= 2)

**Serial-required:**
- L4-smoke MUST run before L6-smoke when Welle-N is a Doppel-Welle-entry
  (Welle-2, Welle-5, Welle-7) (L6 cross-checks L4's anti-pattern axes
  for the Doppel-Welle structural constraint).

**Parallel-safe:**
- L1-smoke and L2-dryrun and L4-smoke CAN run in parallel.
- L6-smoke runs after L4-smoke for Doppel-Welle entries.

### 5.3 Welle-N-Day (Cutover-Mittwoch)

**Serial-required:**
- L2-live (operator-hand, live-VM-acceptance-lane, §8) and L2-shadow
  (hermetic CI-mirror) MUST run in the same Mittwoch window. L2-shadow
  is the hermetic-CI counterpart that validates L2-live's record-shape
  in CI-substrate without executing the live VM.

**Parallel-safe:**
- L2-live and L2-shadow CAN run in parallel (different substrates:
  live-VM vs CI-hermetic).

### 5.4 Post-Welle-N (Sign-off-Freitag)

**Serial-required (Post-Welle-1..6):**
- L2-record-validation runs serial per Welle (consumes the Welle-N
  L2-output).

**Serial-required (Post-Welle-7 Global):**
- L2-record-validation (Welle-7) MUST complete before L1-full and
  L3-full (L1 and L3 consume the full seven-record sequence including
  Welle-7).
- L1-full MUST complete before L3-full (L3 consumes L1's marker-emit-
  gate predicate at runtime).

**Parallel-safe (Post-Welle-7 Global):**
- After L1-full passes, the Marathon-Final-Acceptance-Live-Verify-Gate
  (Tag-56, PR #358) can run in parallel with L3-full as a Surface-1..5
  cross-attestation.

## 6. Failure-Mode-Cascade-Matrix

If Layer-X fails on Welle-N, the following cascade triggers. The
cascade is **deterministic** and encoded in `aggregate_pyramide_run_order_verdict.py`.

### 6.1 Pre-Welle failure cascade

| Failure | Effect on this Welle | Effect on downstream Wellen | Verdict-Aggregator action |
|---|---|---|---|
| L1-smoke RED | BLOCK Welle-N-Day | BLOCK all downstream Wellen until L1-smoke green | Escalate to Mira (AR-notify via `build_marathon_rollback_ar_notify.py`). |
| L2-dryrun RED | BLOCK Welle-N-Day | BLOCK Welle-N only; downstream Wellen unaffected if L2-dryrun-Welle-N+1 green | Escalate to Tomas (operative). |
| L4-smoke RED (any Welle) | BLOCK Welle-N-Day | BLOCK all downstream Wellen until L4-smoke green | Escalate to Mira (anti-pattern regression). |
| L4-full RED (Pre-Welle-1) | BLOCK marathon-entry | n/a (marathon does not start) | Escalate to Mira + AR. |
| L5-full RED (Pre-Welle-1) | BLOCK marathon-entry | n/a (marathon does not start) | Escalate to Mira + Henrik (failure-mode-coverage regression). |
| L6-full RED (Pre-Welle-1) | BLOCK marathon-entry | n/a (marathon does not start) | Escalate to Mira + AR (defence-in-depth regression). |
| L6-smoke RED (Doppel-Welle entry) | BLOCK Doppel-Welle-N-Day | BLOCK only the Doppel-Welle pair; downstream Wellen unaffected if next Doppel-Welle entry green | Escalate to Mira. |

### 6.2 Welle-Day failure cascade

| Failure | Effect on this Welle | Effect on downstream Wellen | Verdict-Aggregator action |
|---|---|---|---|
| L2-live RED (operator-hand) | Welle-N sign-off-record RED | Downstream Wellen MAY proceed; Global Acceptance-Verdict at Post-Welle-7 will be RED unless rollback-recovers L2-live (ADR-0066 Doppel-Welle-Rollback-Cadence) | Escalate to operator + Mira; trigger `phase-3-marathon-rollback.yml` (Tomas Tag-56). |
| L2-shadow RED (hermetic) | Welle-N sign-off-record SUSPECT | Downstream Wellen proceed; investigate hermetic-CI substrate-drift | Escalate to Amara + Tomas. |
| L2-live and L2-shadow disagree | Welle-N sign-off-record RED (caller-required-cross-check semantic) | Investigate substrate-drift; rollback Welle-N | Escalate to Mira + Henrik (Zone-N substrate-drift = audit signal). |

### 6.3 Post-Welle failure cascade

| Failure | Effect | Verdict-Aggregator action |
|---|---|---|
| L2-record-validation RED (per-Welle-N) | Welle-N sign-off-record REJECTED | Block Welle-N sign-off-Freitag; trigger rollback. |
| L1-full RED (Post-Welle-7 Global) | Global Acceptance-Verdict RED; Phase-3-COMPLETE-marker DOES NOT FIRE | Escalate to Mira + AR (Marathon failure). |
| L3-full RED (Post-Welle-7 Global) | Global Acceptance-Verdict RED; Phase-3-COMPLETE-marker DOES NOT FIRE | Escalate to Mira + AR (Marathon failure). |
| Live-Verify-Gate RED (Post-Welle-7 Global) | Global Acceptance-Verdict CAUTION (Surface-1..5 cross-attestation drift); does not block marker if L1-full + L3-full green, but logs as Zone-N substrate-drift signal | Escalate to Amara + Henrik (audit-evidence-index drift). |

### 6.4 Cascade-aggregation principle

A single Layer-X RED **never** silently blocks the marathon; the
Verdict-Aggregator (see §7) explicitly emits a per-Welle verdict and
a Global verdict, and the escalation-path is encoded in the helper-
script. There is no implicit fall-through.

## 7. Acceptance-Verdict-Aggregation

### 7.1 Per-Welle Verdict

Each Welle-N produces a verdict in {GREEN, CAUTION, RED} computed by
`aggregate_pyramide_run_order_verdict.py --welle N`:

```
per_welle_verdict(N) =
    GREEN   if  all_required_layers_green(N)
    CAUTION if  L2_shadow_disagrees_but_L2_live_green
                OR L4_smoke_green_with_known_drift_flag
    RED     otherwise
```

Required-layers per Welle:
- All Wellen: L1-smoke (Pre), L2-dryrun (Pre), L2-live + L2-shadow
  (Day), L2-record-validation (Post).
- Welle-1 additionally: L4-full, L5-full, L6-full (Pre, marathon-entry).
- Welle-N (N >= 2): L4-smoke (Pre).
- Doppel-Welle-entry Welle-N (Welle-2, Welle-5, Welle-7): L6-smoke (Pre).

### 7.2 Global Verdict (Post-Welle-7 only)

```
global_verdict =
    GREEN   if  all(per_welle_verdict(N) in {GREEN}) for N in 1..7
                AND L1_full_green
                AND L3_full_green
                AND Live_Verify_Gate_green
    CAUTION if  all required green BUT Live_Verify_Gate CAUTION
    RED     otherwise
```

The Global Verdict GREEN is the necessary-and-sufficient condition
for the Phase-3-COMPLETE-marker to fire (per Surface-1..5 conjunction
in `phase-3-marathon-final-acceptance.md` §1).

### 7.3 Verdict-emission contract

The helper-script `aggregate_pyramide_run_order_verdict.py` emits a
JSON envelope:

```json
{
  "schema_version": "1.0.0",
  "doc_version": "tag-57",
  "welle_id": "welle-N" | "global",
  "verdict": "GREEN" | "CAUTION" | "RED",
  "required_layers": [...],
  "layer_outcomes": {"L1-smoke": "GREEN", ...},
  "escalation": {"target": "Mira" | "Tomas" | "AR" | null,
                 "reason": "..."},
  "doc_anchor": "docs/quality-gates/pre-cutover-acceptance-run-order.md"
}
```

The envelope is **read-only** for downstream consumers (Tomas
operative-eskalation, Henrik audit-evidence-index, Mira AR-summary).
Modifying it constitutes a doc-version bump.

## 8. Sandbox-Boundary

### 8.1 Operator-hand-only items (NOT this doc's scope)

The following items are **operator-hand-territory** (ADR-0058 §Nachtrag)
and are NOT governed by this doc:

- **L2-live (live-VM-acceptance-lane on Cutover-Mittwoch).** This doc
  specifies that L2-live runs in parallel with L2-shadow on each Welle-
  N-Day, but the **execution-substrate** of L2-live (the live VM, the
  network-fixtures, the production-mirror) is operator-hand.
- **Force-push resolution on PR-stack collisions.** When this PR
  (Tag-57) needs a force-push to resolve a stack-collision, the
  Mira-hand-authorisation clause applies (`feedback_force_push_bundle_merge_ok`).
- **Self-merge via gh-API PUT.** This doc does not authorize self-merge;
  the Tag-57 PR uses gh-API PUT under Continuous-Mode (Mira-hand authorised
  in the Tag-57 Auftrag).

### 8.2 Hermetic-CI-only items (THIS doc's scope)

All other items in this doc are **hermetic-CI-territory**:

- The 167-test hermetic substrate (Layer-1..6 test-files).
- The L2-shadow CI-mirror.
- The Verdict-Aggregator helper-script.
- The per-Welle Pre-Welle and Post-Welle CI-runs.

### 8.3 Zone-N audit boundary

Henrik (Internal Audit) consumes this doc as **Audit-Evidence-Index**:

- §3 per-Welle run-order table -> Audit-Sample-Index (which CI-runs
  Henrik samples for the Welle-N audit).
- §6 Failure-Mode-Cascade-Matrix -> Audit-Compliance-Check (Henrik
  verifies escalations happened per the matrix).
- §7 Verdict-Aggregation -> Audit-Verdict-Cross-Check (Henrik
  independently cross-checks the global verdict).

Henrik does **not** modify this doc; modifications go through Amara
(QA-domain owner) with Zone-N cross-check.

---

*Doc-Owner: Amara Osei (QA). Created Tag-57 (2026-05-19). Companion
test-file: `tests/ci/test_pyramide_run_order_doc_tag57.py`. Companion
helper: `tooling/ci/aggregate_pyramide_run_order_verdict.py`.*

*Cross-Review items (NOT executed in this PR, marked per Zone-Disziplin):*
- *Zone-M with Tomas: validate the per-Welle run-order against the
  Marathon-Final-Acceptance-Live-Verify-Gate workflow (Tag-56 PR #358).*
- *Zone-N with Henrik: validate §6 Failure-Mode-Cascade-Matrix
  against the Pre-Mortem 23-failure-mode coverage doc.*
- *Zone-M with Noa: validate §3 Per-Welle run-order against the
  SLO-MARATHON-1..7 SLI emission cadence.*
