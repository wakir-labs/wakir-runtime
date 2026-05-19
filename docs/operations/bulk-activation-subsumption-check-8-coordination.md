---
title: "Bulk-Activation Subsumption: Check #8 Coordination (Tag-64)"
status: "active"
owner: "tomas+kai"
audience: "operator,ar,engineering"
created: "2026-05-19"
tag: "tag-64"
predecessors:
  - "docs/operations/bulk-activation-pre-walk-recipe.md"
  - "docs/operations/reuse-wrap-enforce-flip-readiness-plan.md"
related_adrs:
  - "ADR-0020"
  - "ADR-0036"
  - "ADR-0061"
related_docs:
  - "docs/operations/branch-protection-required-checks-tag59.md"
  - "docs/operations/branch-protection-required-checks-tag61-addendum.md"
  - "docs/operations/bulk-activation-pre-walk-recipe.md"
  - "docs/operations/reuse-wrap-enforce-flip-readiness-plan.md"
related_prs:
  - "#389"
  - "#392"
  - "#394"
  - "#396"
  - "#401"
  - "#404"
related_memory:
  - "feedback_branch_protection_check_names.md"
  - "feedback_sandbox_host_trennung.md"
  - "feedback_anti_eskalations_drift.md"
related_zones:
  - "Zone-K (Tomás, REUSE-Wrap pre-merge lint)"
  - "Zone-J/CI (Kai, Branch-Protection wiring + Bulk-Activation)"
---

# Bulk-Activation Subsumption: Check #8 Coordination (Tag-64)

This doc is a **cross-persona coordination record** between
Tomás (Zone-K REUSE-Wrap pre-merge lint, Tag-61 PR #392 +
Tag-62 PR #394 + Tag-63 PR #404) and Kai (Bulk-Activation
Pre-Walk Recipe, Tag-62 PR #396, and Walking-Skeleton Test,
Tag-63 PR #401). It pins down **who owns what** when the
REUSE-Wrap pre-merge lint workflow (`Check #8` in Tomás's
Enforce-Flip plan-doc) is folded into Kai's bulk-activation
walk for the Required-Status-Check pool.

The Tomás Tag-63 lieferbericht §3 (PR #404 `Annahmen, die wir
noch nicht geprüft haben`) flagged this coordination as "Tag-64+
planning cycle". This doc is the Tag-64 closure.

This is **doc-form-only**. No workflow mutation, no allowlist
change, no `gh variable set`, no `gh api` PUT. The actual
bulk-walk that includes Check #8 is operator-hand under the
Mira-Sandbox-vs-Host-Operations rule.

---

## §1 - Scope

### §1.1 - Three substrates converge here

| # | Substrate | Owner | Anchor PR(s) |
|---|---|---|---|
| (a) | Bulk-Activation Pre-Walk Recipe (Tag-62) — the planner + shell wrapper that assembles the 7-Pool target | Kai | #396 |
| (b) | Walking-Skeleton Test (Tag-63) — mock-API-mode hermetic verification of (a) | Kai | #401 |
| (c) | REUSE-Wrap Pre-Merge Lint Enforce-Flip plan (Tag-61 → Tag-63) — the Check #8 lifecycle (workflow ships Tag-61, plan doc Tag-62 + Tag-63) | Tomás | #392, #394, #404 |

Tag-64 is the coordination point at which substrates (a) + (b)
become **subsumption candidates** for substrate (c)'s §7.3
"single-mutation flip command".

### §1.2 - The subsumption question (Tag-63 §10 Open-Question)

The Tomás Tag-63 plan-doc §10.A (`Open Question (Tag-62 +
Tag-63)`) asks:

> Does the next operator bulk-walk (Kai's #396 recipe) pull in
> Check #8 (the REUSE-Wrap workflow), or does Check #8 ship
> as a separate single-context PUT after its own Stability-
> Window-Probe?

This Tag-64 doc answers it: **separate single-context PUT,
after Stability-Window-Confirmed, optionally batched in a
later bulk-walk if Check #8 is not yet wired by then**.

The detailed reasoning is in §3.

### §1.3 - 7-Pool composition (Tag-59 + Tag-61) pinned

The 7-Pool target is the union of:

| Pool | Doc | Display-Name |
|---|---|---|
| Tag-59 §1 #1 | `branch-protection-required-checks-tag59.md` §1 | `wakir-runtime tests` |
| Tag-59 §1 #2 | (same) | `wakir-runtime spec-format` |
| Tag-59 §1 #3 | (same) | `wakir-runtime brand-pin-guard` |
| Tag-59 §1 #4 | (same) | `wakir-runtime adr-pin-guard` |
| Tag-59 §1 #5 | (same) | `wakir-runtime adr-cross-link-guard` |
| Tag-61 §1 #6 | `branch-protection-required-checks-tag61-addendum.md` §1 | `wakir-runtime audit-log-corruption-replay` |
| Tag-61 §1 #7 | (same) | `wakir-runtime nats-jetstream-schema` |

The 7-Pool is the **closed set** that Kai's PR #396 bulk-walk
targets. Check #8 (REUSE-Wrap Pre-Merge Lint, display-name
`REUSE-Wrap Pre-Merge Lint (Tag-61)`) is **outside the 7-Pool
by design** — it ships in Tag-61 PR #392 with its own
hint/enforce gating substrate (the `REUSE_WRAP_LINT_ENFORCE`
repo-var), and its activation is gated on the §7 Stability-
Window-Confirmed handshake from the Tomás plan-doc.

### §1.4 - Out of scope for this doc

- The actual `gh api PUT` that activates the 7-Pool. Operator-
  hand only. See `bulk-activation-pre-walk-recipe.md` §1 +
  `branch-protection-required-checks-tag59.md` §2.1.
- The actual `gh variable set REUSE_WRAP_LINT_ENFORCE 1` flip.
  Operator-hand only. See `reuse-wrap-enforce-flip-readiness-
  plan.md` §7.3.
- Any mutation of the Tag-61 REUSE-Wrap workflow itself
  (`.github/workflows/reuse-wrap-pre-merge-lint.yml`). Untouched
  here. Tag-61 PR #392 is the substrate-of-record.
- The OPEN-K3 V-907 baseline-metadata carry-forward (separate
  carry-forward record in this same Tag-64 PR; see `open-k3-
  v907-baseline-metadata-carry-forward.md`).

---

## §2 - Coordination Protocol — Kai + Tomás Roles

### §2.1 - Ownership matrix

| Surface | Owner | Cross-Reviewer |
|---|---|---|
| Bulk-Activation planner + shell wrapper (`tooling/ops/_bulk_activate_required_checks.py` + `bulk_activate_required_checks.sh`) | Kai | Tomás (operations review only) |
| Walking-Skeleton Test workflow + fixtures (`bulk-activation-walking-skeleton-test.yml` + `tests/observability/fixtures/branch-protection-walking-skeleton/`) | Kai | Tomás (operations review only) |
| REUSE-Wrap pre-merge lint workflow (`reuse-wrap-pre-merge-lint.yml`) | Tomás | Kai (Branch-Protection wiring review only) |
| REUSE-Wrap helper script (`lint_reuse_ignore_wrap_pattern.py`) | Tomás | Kai (no review, internal helper) |
| Enforce-Flip plan-doc (`reuse-wrap-enforce-flip-readiness-plan.md`) | Tomás | Kai (cross-anchor review only) |
| Stability-Window-Probe workflow (`reuse-wrap-enforce-flip-stability-window-probe.yml`) | Tomás | none |
| Rollback mock-substrate (`mock_reuse_lint_rollback.py`) | Tomás | none |
| This coordination doc (Tag-64) | Tomás (author) + Kai (co-signatory by reference; no edit needed for Tag-64) | none — Mira-mediated if conflict |
| OPEN-K3 carry-forward doc (Tag-64) | Tomás + Selin (Zone-K cross-review surface) | none — already cross-reviewed in Tag-59 seal |
| 7-Pool target docs (`branch-protection-required-checks-tag59.md` + `tag61-addendum.md`) | Kai | Tomás (Required-Check pool composition review) |

### §2.2 - Decision authority

| Decision | Authority | Escalation |
|---|---|---|
| Whether the next bulk-walk run includes Check #8 | Operator (with Kai + Tomás concurrence) | Mira if no concurrence |
| Whether to delay the bulk-walk to align with Check #8 readiness | Operator (with Kai + Tomás concurrence) | Mira if no concurrence |
| Whether to split the bulk-walk into 7-Pool first, Check #8 later | Default (this doc §3) | none |
| Stability-Window-Confirmed verdict | Tomás §7.1 probe (Tag-63 workflow) | none |
| 7-Pool plan-consistent verdict | Kai §1 planner (Tag-62 + Tag-63 walking-skeleton) | none |
| Actual `gh api PUT` | Operator-hand | none (sandbox-boundary, Mira rule) |

### §2.3 - Communication channels

- **Default channel:** PR comments on the relevant substrate
  PRs. Kai's #396 + #401 are the bulk-walk anchors; Tomás's
  #392 + #394 + #404 are the Check #8 anchors.
- **Coordination doc updates:** if either persona needs to
  rewrite this doc, the rewrite is a single PR by either Kai
  or Tomás, with the other persona invited as a reviewer for
  cross-zone consistency only (no veto power on the other
  persona's domain).
- **Conflict resolution:** Mira-mediated only if the operator
  flags an actual deadlock. Tag-64 has no deadlock; this doc
  records the agreed default.

---

## §3 - Activation Order Update — Check #8 after Stability-Window-Confirmed

### §3.1 - The recommended order

```
Step 1: Operator runs Kai's bulk-walk for the 7-Pool
        (display-names Tag-59 §1 + Tag-61 §1).
        Verdict required: PLAN-CONSISTENT (Kai §1).
        Walking-Skeleton verdict required: WALKING-SKELETON-INTACT
        (Kai PR #401).

Step 2: Operator activates the 7-Pool via gh api PUT
        (single bulk PUT replacing the contexts list).
        Smoke-test per Tag-59 §5.

Step 3: Operator OR Tomás triggers the REUSE-Wrap
        Stability-Window-Probe (Tomás §7.1).
        Verdict required: STABILITY-WINDOW-CONFIRMED (3
        consecutive workflow_dispatch runs READY).

Step 4: Operator confirms three Tomás §7.2 preconditions
        (a) workflow N times green on main without flake
            (already confirmed in Step 3 as a side-effect),
        (b) Required-Status-Check wired under Branch-
            Protection — this is the Step 5 action below,
        (c) Baseline Coverage-Audit REUSE-WRAP-INTACT (the
            Tag-62 helper `--mode enforce-flip-readiness`
            verdict; Tomás-hand).

Step 5: Operator runs ONE OF:

        Option-A (single-context PUT, recommended):
        Use the Tag-59 §2.1 recipe to PUT a single-context
        update appending the Check #8 display-name to the
        existing 7-Pool list, resulting in an 8-Pool
        Required-Status-Check set.

        Option-B (next bulk-walk includes Check #8):
        If Kai schedules a fresh bulk-walk that re-targets
        the 8-Pool set (with Check #8 added to Kai's planner
        as Pool #8), the next bulk-walk subsumes the §7.3
        single-mutation flip command. The bulk-walk MUST be
        re-tested via Walking-Skeleton with an updated
        `expected-post-snapshot.json` carrying 8 contexts.

Step 6: Operator runs the §7.3 flip command:
        gh variable set REUSE_WRAP_LINT_ENFORCE 1.
        Verdict required: workflow turns red on the first PR
        that introduces an unwrapped SPDX literal.

Step 7: Tomás runs §7.5 audit-trail seal (commit a record to
        docs/operations/reuse-wrap-enforce-flip-actuated.md).
```

### §3.2 - Why Check #8 is not folded into the initial bulk-walk

Three reasons.

**(i) Stability-Window not yet confirmed at the time of the
initial bulk-walk.** The Tomás §7.1 Stability-Window-Probe
runs three consecutive workflow_dispatch dry-runs on `main`
after PR #404 has merged. The probe's verdict
`STABILITY-WINDOW-CONFIRMED` is the precondition for Check #8
to be a candidate for activation. The initial bulk-walk runs
**before** the probe; the bulk-walk's 7-Pool is therefore the
right scope for the initial walk.

**(ii) Check #8 has its own three preconditions (Tomás §7.2)
that the bulk-walk does not check.** Kai's planner verifies
PLAN-CONSISTENT — the display-names parse cleanly and the
combined set is the expected 7. It does **not** verify
Tomás's §7.2 preconditions (workflow N-times-green, Required-
Check wired, REUSE-WRAP-INTACT score). Folding Check #8 into
the initial bulk-walk would skip these three preconditions.

**(iii) The bulk-walk is a full-replace PUT, not an append.**
Kai's planner emits an `expected-post-snapshot.json` that is
the **complete** contexts list. If the bulk-walk PUTs 7
contexts, the GitHub API treats it as a replace — any existing
contexts (e.g. if Check #8 had been activated earlier by a
single-context PUT) would be removed. Therefore the bulk-walk
must always have the **complete** target set as its
post-snapshot. The default Tag-64 posture is: the bulk-walk
targets 7 contexts, the §7.3 flip is a separate single-context
append, and any future bulk-walk that targets 8 contexts must
update the walking-skeleton fixtures first.

### §3.3 - When to choose Option-B (next bulk-walk includes Check #8)

Option-B is the right choice if **all** of the following hold:

1. The §7.1 Stability-Window-Probe has reached
   STABILITY-WINDOW-CONFIRMED **before** Kai schedules the
   next bulk-walk.
2. The §7.2 three preconditions are all satisfied at the time
   of the next bulk-walk.
3. There is a substantive reason to bundle Check #8 into the
   next bulk-walk rather than running it as a single-context
   PUT (for example: the next bulk-walk is itself a re-wire
   of the existing pool due to a display-name rename or a
   pool expansion to 8+; folding Check #8 in saves one PUT
   round-trip).

Absent (3), the default Option-A is strictly simpler: each
flip is a single point of mutation, separately auditable.

### §3.4 - The bulk-walk-with-Check-#8 fixture refresh recipe

If the operator chooses Option-B, the following fixture refresh
is required **before** the bulk-walk:

1. Update `tests/observability/fixtures/branch-protection-
   walking-skeleton/expected-post-snapshot.json` to carry 8
   contexts (current 7 plus `REUSE-Wrap Pre-Merge Lint
   (Tag-61)`).
2. Update Kai's planner default target list to include Pool #8.
3. Re-run the Walking-Skeleton workflow (`bulk-activation-
   walking-skeleton-test.yml`) and confirm verdict
   `WALKING-SKELETON-INTACT` against the updated expected
   post-snapshot.
4. Update Tag-59 §1 or Tag-61-addendum §1 — whichever doc has
   the canonical pool list — to mention Check #8 as Pool #8.
5. PR the change with both Kai and Tomás as required reviewers.

This recipe is doc-form-only in this Tag-64 PR. The actual
fixture refresh is a future operator-hand action.

---

## §4 - Pool-Sync Pattern (Tag-59 doc + Tag-61 addendum + Tag-64 Coord)

### §4.1 - The pool-sync invariant

The Required-Status-Check pool is documented in **three layers**:

| Layer | Doc | Role |
|---|---|---|
| Layer 1 | `branch-protection-required-checks-tag59.md` | Foundational 5-Pool (display-names #1-#5) |
| Layer 2 | `branch-protection-required-checks-tag61-addendum.md` | Delta to 7-Pool (display-names #6-#7) |
| Layer 3 | this doc, §1.3 | Bilanz table of the 7-Pool + Check #8 candidacy |

The **pool-sync invariant** is: the union of layer-1 + layer-2
canonical pool tables = layer-3 §1.3 bilanz table. The Tag-63
Walking-Skeleton workflow (Kai PR #401) is the **automated
enforcement** of this invariant; the planner's
PLAN-CONSISTENT verdict is set-equality between layer-1+layer-2
union and layer-3 (the planner's "combined-table set"; see
`bulk-activation-pre-walk-recipe.md` §1 verdict definitions).

### §4.2 - How to extend the pool (post-Tag-64)

If a future PR introduces a new Required-Check that should
join the pool:

1. Add a new layer-2-style addendum doc (e.g. `branch-
   protection-required-checks-tagNN-addendum.md`).
2. Update Kai's planner to parse the new addendum doc.
3. Update the walking-skeleton fixtures
   (`expected-post-snapshot.json`).
4. Update this coordination doc §1.3 bilanz table.
5. PR with both Kai and Tomás reviewers.

The pattern is intentionally **append-only at the doc layer**.
The Tag-59 + Tag-61 docs are not rewritten; new pool entries
land in new addendum docs.

### §4.3 - Why the doc layer is layered

A flat single-doc pool would be simpler in one respect (no
union-arithmetic) but worse in two:

- Audit-trail: each addendum doc has its own PR + commit, so
  the provenance of each pool entry is byte-anchored to a
  single PR. A flat doc would lose this provenance unless
  every edit carried a §-history note (which the Tag-59 doc
  intentionally does not — its scope is the 5-Pool initial
  set, and freezing it as the foundational doc is the value).
- Spawn-collision: in a high-tempo spawn environment
  (Memory `feedback_high_tempo_spawn_collision`), two parallel
  spawns editing a flat pool doc would race. Layered addenda
  serialise naturally.

The layered pattern is the **same pattern** the Persona-Engine
manifest layer uses (`MANIFEST-0.5.2-final-pre-cutover.md`
carries-forward across `0.5.3-rc1` and `0.5.3`; the §0
Version-Header is the only Tag-62 mutation, and the §0.1
history sub-section preserves the rc1 stamp verbatim).

---

## §5 - Sandbox Boundary

This doc is documentation only. The companion test suite
(`tests/ci/test_k3_and_bulk_subsumption_tag64.py` §Subsumption
group) is pure read-only assertions over substrate files. No
mutation of:

- `.github/workflows/reuse-wrap-pre-merge-lint.yml` (Tag-61
  workflow, Tomás-hand).
- `.github/workflows/bulk-activation-walking-skeleton-test.yml`
  (Tag-63 workflow, Kai-hand).
- `.github/workflows/reuse-wrap-enforce-flip-stability-window-
  probe.yml` (Tag-63 workflow, Tomás-hand).
- `tooling/ops/_bulk_activate_required_checks.py` (Tag-62
  planner, Kai-hand).
- `tooling/ci/lint_reuse_ignore_wrap_pattern.py` (Tag-61 helper,
  Tomás-hand).
- `tests/observability/fixtures/branch-protection-walking-
  skeleton/expected-post-snapshot.json` (Tag-63 fixture,
  Kai-hand).
- Repo-variables (`REUSE_WRAP_LINT_ENFORCE`,
  `BULK_ACTIVATE_OPERATOR_HAND`). Sandbox cannot read or
  write these.
- Branch-Protection `required_status_checks.contexts`. Sandbox
  cannot mutate.

The Mira-Sandbox-vs-Host-Operations rule (Memory `feedback_
sandbox_host_trennung`) is preserved. The §3.1 Step 1, 2, 5,
6 operator-hand actions are explicitly outside the sandbox
boundary. The §3.4 fixture refresh, if invoked, is a future
operator-hand PR — not this Tag-64 PR.

---

*Tomás Reinhart, Dev-Engineering-Agent, Zone-K cross-coordination author.*
*Co-signed by reference to: Kai Hoffmann, Dev-Engineering-3 (#396, #401, Bulk-Activation owner).*
*Tag-64 cross-persona coordination record.*
*2026-05-19.*
