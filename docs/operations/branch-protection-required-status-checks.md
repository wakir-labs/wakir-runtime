<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Branch-Protection Required-Status-Checks — Cross-Repo Inventory

**Status:** Living operations document.
**Scope:** All three public repos under `wakir-labs/` org.
**Last audit:** 2026-05-17 (Kai, Tag-16 Pfad A path-filter precision-add;
widened the `cross-repo-drift-audit.yml` path-filter from the original
4-entry narrow set to an 8-entry set, closing the forever-PENDING
reach-asymmetry that hit PRs #153, #158, #160, #161 — each one had
needed an ad-hoc no-op `wirelang/__init__.py` touch as workaround).
Prior audit: 2026-05-17 (Kai, Sprint-Branch-Protection-cross-repo-
drift-Required-MINI; promoted §4.2 `cross-repo drift` from "recommendation"
to "ready-to-apply, Mira-Hand-pending", subsequently applied 04:35 CEST).
**Source of truth:** `gh api repos/wakir-labs/<repo>/branches/main/protection`.

---

## 1. Why this document exists

Branch-protection `required_status_checks` matches GitHub check-display-names
literally (job-`name`-field inside the workflow YAML, not the workflow-`name`
itself, not the workflow filename). A wrong string equals a forever-PENDING
PR, because the matcher silently waits for a check that never reports
under that name. The lesson is in `feedback_branch_protection_check_names`
(2026-05-16 ~17:08 CEST regression).

This document is the operator's cross-repo reference so that:

* a) the actual required-set in each repo is visible without an API call,
* b) the convergence-gap to a shared Sollstellung is visible,
* c) a Mira-Hand operator can re-apply the recommended set in one
  copy-paste step per repo when Branch-Protection drifts.

The document is hermetic (no live API calls); the consistency test
`tests/infra/test_branch_protection_consistency_audit.py` pins the
inventory below into CI so drift fails fast.

---

## 2. Current Required-Status-Check sets (2026-05-16)

### 2.1 `wakir-labs/wakir-runtime`

Post-§4.2-promotion stand (re-verified 2026-05-17 04:35 CEST via
`gh api repos/wakir-labs/wakir-runtime/branches/main/protection`):

| Check display-name | Defined in | Job-`name` field |
|---|---|---|
| `License-Hygiene Gate (ADR-0061)` | `.github/workflows/license-gate.yml` | `License-Hygiene Gate (ADR-0061)` |
| `wirelang suite with rfc8785 + jsonschema` | `.github/workflows/tests.yml` | `wirelang suite with rfc8785 + jsonschema` |
| `cross-repo drift (wakir-runtime ↔ wakir-protocol)` | `.github/workflows/cross-repo-drift-audit.yml` | `cross-repo drift (wakir-runtime ↔ wakir-protocol)` |

§4.2 promotion applied 2026-05-17 04:35 CEST (Mira-Hand-Operator, AR-
authorised via "Ja, aktiviere Branch-Protection wakir-runtime/main"
2026-05-16 17:08 CEST + §4.2 Mira-Hand-pending in PR #144 doc).

The Tag-3 candidate `Hash-Derivate-Drift Gate (Sprint-Stability Tag-3)`
was **not** promoted to required in the Tag-4 timeframe (intentional
withdrawal — see §4.4 anti-pattern). The workflow remains in-tree and
runs on its narrow path-filter, but its Required-status promotion was
held back because the path-filter is too tight to satisfy the
universal-trigger requirement (§4.5).

Other gates: `allow_force_pushes=false`, `allow_deletions=false`,
`strict=true` (require branches up-to-date), `required_signatures=false`,
`enforce_admins=false`.

### 2.2 `wakir-labs/wakir-verify`

| Check display-name | Defined in | Job-`name` field |
|---|---|---|
| `pytest (3.13)` | `.github/workflows/ci.yml` | matrix-expanded from `test:` job (python-version `3.13`) |
| `REUSE lint` | `.github/workflows/license-check.yml` | `REUSE lint` (job `reuse`) |
| `Analyze (python)` | `.github/workflows/codeql.yml` | CodeQL matrix-expanded display-name |

Other gates: identical to wakir-runtime (no force-push, no deletions,
strict=true, signatures+admins off).

### 2.3 `wakir-labs/wakir-protocol`

Identical to `wakir-verify` (same three checks, same workflow filenames,
same gate flags). The repo was split out of `wakir-verify` under
ADR-0062 Phase 2 and inherited the CI/protection topology 1:1.

Post-Tag-4 stand (re-verified 2026-05-16 ~19:36 CEST): unchanged from
the original 2026-05-16 audit; `wakir-verify` and `wakir-protocol`
required-sets remain at 3 contexts each.

---

## 3. Asymmetry-Map

Two axes of drift today:

**Axis A: License-Hygiene gating.**
Only `wakir-runtime` currently enforces an ADR-0061-shaped License-Hygiene
gate (the full LICENSING.md + LICENSES/ + LICENSE-BSL.md + pyproject
license-files audit). `wakir-verify` and `wakir-protocol` enforce
`REUSE lint` only — that catches missing SPDX-headers but does not
catch the broader BSL-Subtree-discipline or the WAT-Change-Date pin.

**Axis B: Code-suite breadth.**
`wakir-runtime` enforces a single Python lane
(`wirelang suite with rfc8785 + jsonschema`). `wakir-verify` and
`wakir-protocol` enforce a generic `pytest (3.13)` lane plus a
`Analyze (python)` CodeQL security-scan. `wakir-runtime` runs a
CodeQL workflow too (look in `.github/workflows/` for security
hooks) but it is **not** in the required-set as of 2026-05-16.

The net effect: each repo's required-set covers a different slice of the
quality bar. PRs that pass in one repo would not necessarily pass in
another.

---

## 4. Convergence-Sollstellung (proposed)

All three repos should converge on three classes of required-check:

1. **License/legal hygiene.**
   * `wakir-runtime`: keep `License-Hygiene Gate (ADR-0061)`.
   * `wakir-verify`, `wakir-protocol`: keep `REUSE lint` (sufficient
     for the leaner mono-license repos under ADR-0062 split).
   * No cross-repo job-name harmonisation here — the gate is
     intentionally repo-shaped.
2. **Code-correctness lane.**
   * `wakir-runtime`: keep `wirelang suite with rfc8785 + jsonschema`.
   * `wakir-verify`, `wakir-protocol`: keep `pytest (3.13)`.
3. **Security scan.**
   * `wakir-verify`, `wakir-protocol`: keep `Analyze (python)`.
   * `wakir-runtime`: **gap** — CodeQL workflow exists in the repo
     but is not in the required-set. Recommend promoting the
     CodeQL `analyze` job-name (exact display: `Analyze (python)`
     if the matrix mirrors the verify-side) to required after a
     burn-in PR confirms the check-name.

### 4.1 Withdrawn (Tag-3 → Tag-4): Hash-Derivate-Drift Gate

PR #101 (2026-05-15) added `hash-derivate-gate.yml` with job display-name
`Hash-Derivate-Drift Gate (Sprint-Stability Tag-3)`. Its functional
purpose — preventing schema-fixture hash-derivative drift that would
silently break the external-verifier-conformance lane — is sound and
the workflow stays in-tree.

The original 2026-05-16 audit recommended promoting this gate to
Required. **That recommendation is withdrawn** as of the post-Tag-4
refresh. Rationale: the workflow's path-filter is intentionally tight
(`wirelang/schemas/**`, `tests/fixtures/schema-registry/**`, the
hash-derivate test file, the workflow YAML itself). On any PR that
does **not** touch those paths — i.e. on most PRs — the workflow
does not trigger, the check never reports, and a Required-marker on
its display-name yields forever-PENDING blocks. The same Henne-Ei
failure mode hit PRs #102, #107, #117 today (path-filter expansion
PRs that did not themselves match the older path-filter and stalled
until the filter was widened).

See §4.4 for the anti-pattern statement and §4.5 for the path-filter-
reach rule that supersedes the §4.1 recommendation.

### 4.2 Score-bewegung — `cross-repo drift` Required-promotion (wakir-runtime)

**Status as of 2026-05-17: ready-to-apply, Mira-Hand-pending.**
(Promoted from "recommendation" to "ready-to-apply" after PR #105/#111/
#117 have been merged and the workflow has burned in for one stable
period without check-name drift.)

PR #105 (2026-05-16) shipped `cross-repo-drift-audit.yml` with job
display-name `cross-repo drift (wakir-runtime ↔ wakir-protocol)`.
The gate enforces that any classification-drift of a wirelang substance
on `wakir-runtime` is mirrored on `wakir-protocol` or explicitly
allowlisted in `.cross-repo-drift-allowlist.yaml`.

Its path-filter (after Tag-16 Pfad A precision-add, 2026-05-17):

```
wirelang/**
wirelang-rust/**
pyproject.toml
tests/**
scripts/**
dashboards/**
.cross-repo-drift-allowlist.yaml
.github/workflows/cross-repo-drift-audit.yml
```

Reach analysis (§4.5, post-Tag-16): the filter covers `wirelang/**`,
`wirelang-rust/**`, `pyproject.toml`, `tests/**`, `scripts/**`, and
`dashboards/**`, which together intersect every code-, test-, and
dashboard-substance PR in the repo. Doc-only PRs (`docs/**`) and
foreign-workflow-only PRs (other than this workflow itself) do **not**
trigger by design: a doc-only PR is not a substance-classification PR
and a PR that only edits, say, `release.yml` is by construction out-
of-scope of the cross-repo-drift substance audit. The non-reach is
acceptable because (a) the gate is by intent a substance-level gate,
and (b) the other Required gates (`wirelang suite`,
`License-Hygiene Gate`) cover doc-only PR-class semantics for any
license/legal-hygiene drift that could ride in via documentation
edits.

**Tag-16 Pfad A rationale.** The original 4-entry path-filter (only
`wirelang/**` + `pyproject.toml` + allowlist + own YAML) left every
PR that did not touch those paths in forever-PENDING — the Required
context never reported because the workflow never ran. This shape hit
four PRs in one operator-stretch (#153, #158, #160, #161) and was
worked around each time by a no-op `wirelang/__init__.py` touch. The
expansion to the 8-entry filter above is the permanent fix: the
substance-classification audit itself stays narrow (the job still
audits only the curated mirror-pair table; the filter only governs
WHEN the job runs, not WHAT it audits). TV-BPC-13 + TV-BPC-14 pin
the new shape against accidental re-narrowing.

**Score impact.** Adds a fourth axis to the Sollstellung
(cross-repo-classification-symmetry) and moves the `wakir-runtime`
slot from 2/3 → 3/4 on the 4-axis reading. The org-wide score moves
from 8/9 = 0.889 → 9/9 = 1.0 once promotion is applied (the
4-axis cross-repo-symmetry slot is intentionally not counted on
`wakir-verify` / `wakir-protocol`, since they have no second repo to
mirror against). See §4.3 for both readings.

**Pre-flight checklist (Mira-Hand-Operator must confirm before
applying):**

1. PR #105, #111, #117 all merged into `wakir-labs/wakir-runtime/main`
   and stable for at least one operator-stretch (no revert, no
   path-filter re-narrowing).
2. At least one green run of `cross-repo-drift-audit.yml` on a topic
   branch confirms the exact check-display-name is
   `cross-repo drift (wakir-runtime ↔ wakir-protocol)`. The Unicode
   arrow `↔` (U+2194, LEFT RIGHT ARROW) must round-trip through `gh
   api -F`. Re-confirm with `gh pr checks <num>` — the name string
   must match byte-for-byte including the spaces around the arrow.
3. The hermetic test `tests/infra/test_branch_protection_consistency_audit.py`
   vector TV-BPC-11 is green (covered today already), and the
   post-promotion target-state fixture `_RUNTIME_PROTECTION_POST_PROMOTION`
   matches the operator's intent. Run:
   `pytest tests/infra/test_branch_protection_consistency_audit.py -v`.

**Mira-Hand-Operator command block.** Run literally, one repo, one
branch (no force-flags, no `-y`). Note the Unicode arrow `↔` (U+2194)
in the context string — copy-paste directly from this block; do not
re-type:

```sh
# Step 1 — re-confirm the exact check-display-name from a recent
# green PR (replace <num> with the PR-id used for burn-in):
gh pr view <num> --repo wakir-labs/wakir-runtime \
  --json statusCheckRollup \
  --jq '.statusCheckRollup[] | select(.name | contains("cross-repo drift")) | .name'

# Expected output (one line, byte-exact):
#   cross-repo drift (wakir-runtime ↔ wakir-protocol)

# Step 2 — apply the expanded required-set (all three contexts must be
# listed; PATCH replaces the contexts array atomically, so re-include
# the existing two contexts to avoid drift to a 1-element set):
gh api -X PATCH \
  repos/wakir-labs/wakir-runtime/branches/main/protection/required_status_checks \
  -F strict=true \
  -F 'contexts[]=License-Hygiene Gate (ADR-0061)' \
  -F 'contexts[]=wirelang suite with rfc8785 + jsonschema' \
  -F 'contexts[]=cross-repo drift (wakir-runtime ↔ wakir-protocol)'

# Step 3 — verify the new required-set:
gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
  --jq '.required_status_checks.contexts | sort'

# Expected output (three entries, sorted):
#   [
#     "License-Hygiene Gate (ADR-0061)",
#     "cross-repo drift (wakir-runtime ↔ wakir-protocol)",
#     "wirelang suite with rfc8785 + jsonschema"
#   ]

# Step 4 — open a no-op PR (touch wirelang/** trivially) to confirm
# all three contexts gate the merge as expected (no forever-PENDING).
```

**Post-apply doc-sync (same operator session):** update §2.1
Required-set table to include the third entry, update §4.3 score-table
to mark `wakir-runtime` cross-repo-symmetry axis = 1, and toggle the
TV-BPC-01 fixture from `_RUNTIME_PROTECTION` to
`_RUNTIME_PROTECTION_POST_PROMOTION` in the consistency-audit test
(see test file's NOTE block). Without the doc-sync, TV-BPC-01 will
fail the next CI run — by design.

**Roll-back (if forever-PENDING).** Per §5.4: remove the offending
context, re-derive the canonical display-name via §5.1, re-apply.
Most common cause for a forever-PENDING on this specific check is
arrow-character drift (ASCII `<->` vs. Unicode `↔` vs. typographic
`⟷`). Only `↔` (U+2194) is correct.

CodeQL `Analyze (python)` on `wakir-runtime` remains an Open Item
(§7); it is a parallel security-axis closure but its workflow file
is not yet in the runtime tree, so it is out-of-scope for this
sprint.

### 4.3 Convergence-Score (updated, two readings)

The Sollstellung uses two reading-modes:

* **Uniform-3-axis reading** (legacy, pre-2026-05-17). Every repo
  scores against the same three axes {license, code, security}.
  Denominator 3 per repo. The 8/9 = 0.889 baseline lives here.
* **In-scope-axes reading** (canonical from 2026-05-17). Each repo
  scores against its in-scope axes only. `wakir-verify` and
  `wakir-protocol` keep {license, code, security}. `wakir-runtime`
  swaps the still-open security axis (§7 CodeQL gap, out-of-scope
  for this sprint) for the cross-repo-symmetry axis, since the
  Mira-Hand-§4.2 promotion is what is actually achievable in the
  current operator-stretch. Denominator stays 3 per repo; the
  org-wide denominator stays 9.

**Today's stand (pre-promotion of §4.2):**

| Repo | License | Code | Security | Cross-Repo-Sym | Uniform-3-axis | In-scope-axes |
|---|---|---|---|---|---|---|
| `wakir-runtime` | 1 | 1 | 0 | 0 | 2/3 | 2/3 |
| `wakir-verify` | 1 | 1 | 1 | n/a | 3/3 | 3/3 |
| `wakir-protocol` | 1 | 1 | 1 | n/a | 3/3 | 3/3 |

Org-wide uniform-3-axis: 8/9 = **0.889** (unchanged since the
2026-05-16 baseline). Org-wide in-scope-axes: 8/9 = **0.889** too,
because pre-promotion the runtime's cross-repo-symmetry slot is also
0 and the swap of {security → cross-repo-symmetry} on runtime is
0-for-0.

**Post-promotion stand (once §4.2 Mira-Hand-Operator command-block
is applied):**

| Repo | License | Code | Security | Cross-Repo-Sym | Uniform-3-axis | In-scope-axes |
|---|---|---|---|---|---|---|
| `wakir-runtime` | 1 | 1 | 0 | **1** | 2/3 | **3/3** |
| `wakir-verify` | 1 | 1 | 1 | n/a | 3/3 | 3/3 |
| `wakir-protocol` | 1 | 1 | 1 | n/a | 3/3 | 3/3 |

Org-wide uniform-3-axis (post-promotion): unchanged at 8/9 = 0.889,
because the uniform reading does not count cross-repo-symmetry. The
3-axis 9/9 closure is unreachable until §7's CodeQL gap closes.

Org-wide in-scope-axes (post-promotion): (3 + 3 + 3) / 9 = **9/9 =
1.000**. This is the canonical post-promotion target — the runtime
trades its currently-uncloseable security-axis slot for the
operator-achievable cross-repo-symmetry slot.

**Decision recorded.** This sprint adopts the **in-scope-axes reading
as the canonical 9/9 score**, with the uniform-3-axis reading retained
for backward-compatibility with the §4.3 regression-anchor on the
consistency test. Both readings are pinned in CI:

* TV-BPC-05 pins the uniform-3-axis 8/9 = 0.889 baseline (today's
  live state). It does not change under §4.2 promotion.
* TV-BPC-12c (new, 2026-05-17) pins the in-scope-axes 9/9 = 1.000
  target as the post-promotion convergence under a separate fixture
  (`_RUNTIME_PROTECTION_POST_PROMOTION`). The fixture is **not**
  the live state — it is the operator's intended state. The vector
  fails if the documented post-promotion required-set ever drifts
  away from the 9/9 shape, forcing a deliberate doc + test update
  alongside any Sollstellung change.

**Future score-shape (out-of-scope for this sprint).** Once §7's
CodeQL gap closes on `wakir-runtime`, the runtime denominator can
grow to 4 in the in-scope-axes reading (license + code + security
+ cross-repo-symmetry all in-scope) and the org-wide denominator
grows to 10. The target then becomes 10/10 = 1.000 under the
in-scope-axes reading, or 9/9 = 1.000 under the uniform-3-axis
reading. Either way: a single sprint per gap. The path 8/9 → 9/9 →
10/10 is the staged convergence-trajectory documented here.

### 4.4 Anti-Pattern: Required-check with narrow path-filter

**Statement.** A workflow whose `on: pull_request: paths:` filter is
narrower than "every PR class that the trust-perimeter cares about"
must **not** be marked as a Required status check. GitHub will not
trigger the workflow on PRs that miss the filter, the check will not
report under its display-name, and the Required-matcher will wait
forever (PR stays at `pending`, merge is blocked).

**Concrete example (in-tree today).** `hash-derivate-gate.yml` has
path-filter `wirelang/schemas/**`, `tests/fixtures/schema-registry/**`,
its own test file, its own YAML. A PR touching only `wirelang/wat/**`
(legitimate Merkle-tree work) does not trigger this workflow. If the
gate were Required, that PR would stall forever-PENDING. The
2026-05-15 Tag-3 recommendation to promote this gate predated the
path-filter-reach analysis below and is withdrawn (§4.1).

**Concrete failure-history.** Three PRs today exhibited the
forever-PENDING shape because Required checks did not match the
PR's path-class: PR #102, PR #107, PR #117 — each one fixing a
path-filter on an upstream workflow so that the workflow would
actually run on the changes that needed to be gated. The Henne-Ei
loop ("the path-filter-expansion PR does not match the old
path-filter, so the gate that requires it does not trigger, so the
PR cannot merge") cost two iterations to close in each case.

**Operator-hand prevention.** Before promoting any check to Required,
the operator runs the §4.5 reach-mapping below. If a PR-path-class
exists that the workflow does not trigger on **and** that class is
in-scope of the gate's purpose, the workflow is not yet shape-fit
for Required-status. Either: (a) widen the path-filter to cover the
missing class, or (b) keep the check unrequired (run-by-trigger only).

### 4.5 Path-Filter-Reach mapping (typical PR classes)

The repo carries five typical PR-path-classes today. Required-checks
should be evaluated against all five. The mapping below shows which
of today's gate-candidates triggers on which class.

PR-path-classes:

* **`code-only`** — modifies `wirelang/**` (excluding schemas+fixtures
  to isolate from hash-derivate scope), `pyproject.toml`, top-level Python.
* **`test-only`** — modifies `tests/**`, no production code touched.
* **`workflow-only`** — modifies `.github/workflows/<some>.yml` with
  no code touched.
* **`doc-only`** — modifies `docs/**`, `README.md`, no code.
* **`dashboard-only`** — modifies `dashboards/**`, no code.

Reach-matrix (✓ = workflow triggers on this PR-class, ✗ = does not):

| Workflow | code-only | test-only | workflow-only | doc-only | dashboard-only |
|---|---|---|---|---|---|
| `tests.yml` (wirelang suite) | ✓ | ✓ | ~ (only listed workflows) | ✓ | ✓ |
| `license-gate.yml` (License-Hygiene) | ✓ | ✓ | ~ (only listed workflows) | ✓ | ✓ |
| `hash-derivate-gate.yml` | ~ (only schemas+fixtures) | ~ (only its test) | ~ (only itself) | ✗ | ✗ |
| `cross-repo-drift-audit.yml` (post Tag-16 Pfad A) | ✓ (via `wirelang/**` + `wirelang-rust/**`) | ✓ (via `tests/**`) | ~ (only itself) | ✗ (by design) | ✓ (via `dashboards/**`) |
| `phase-2-validation-gate.yml` | ~ (only `wirelang/**`) | ~ (only its test) | ~ (only itself) | ~ (only `docs/quality-gates/**`) | ✗ |

Legend: ✓ = full class triggers; ~ = partial trigger; ✗ = no trigger.

The two current Required gates on `wakir-runtime` (`tests.yml`,
`license-gate.yml`) are reach-clean (full ✓ on every class except
the workflow-only edge — and the workflow-only class is by construction
self-contained because the workflow YAML being changed lists itself
in its own filter). They are appropriate as Required.

`hash-derivate-gate.yml` has ✗ on the dashboard-only and doc-only
classes and partial on the rest — **not Required-fit** per §4.4.

`cross-repo-drift-audit.yml` (post Tag-16 Pfad A path-filter
precision-add, 2026-05-17): now ✓ on code-only, test-only, dashboard-
only; ✗ on doc-only (intentional — see Path-Filter-Reach-Mapping
below) and on foreign-workflow-only (intentional — by construction
out-of-scope of the substance audit). Required-fit unconditionally
under §4.5 reach analysis. Pre-Tag-16 it was ✓ only on code-only and
classified as conditionally-fit (§4.2-pending); the path-filter
expansion closed the reach-asymmetry that caused forever-PENDING
blocks on PRs #153, #158, #160, #161.

`phase-2-validation-gate.yml` is currently not a Required candidate
and per the reach-matrix it should not become one without a path-filter
widen (or a deliberate decision that Phase-2 validation only matters
on `wirelang/**` PRs — defensible but should be explicit).

#### Path-Filter-Reach-Mapping (Tag-16 update, 2026-05-17)

The `cross-repo-drift-audit.yml` workflow path-filter is the
operational lesson of Tag-16. The original 4-entry narrow filter
worked-by-design for substance-classification PRs but failed-by-
design for every other PR-class once the workflow's display-name was
promoted to a Required-status-check on `wakir-runtime/main` (§4.2,
2026-05-17 04:35 CEST applied). Every PR that did not touch
`wirelang/**` or `pyproject.toml` stalled at forever-PENDING and was
unblocked by an ad-hoc no-op `wirelang/__init__.py` touch (PRs #153,
#158, #160, #161 — four occurrences in one operator-stretch).

The Tag-16 Pfad A precision-add widens the filter to also cover
`wirelang-rust/**` (Rust crate sibling of the Python `wirelang/`
package), `tests/**` (so test-only PRs no longer need the workaround
touch), `scripts/**` (so scripts-only PRs likewise), and
`dashboards/**` (so dashboard-only PRs likewise). `doc-only` PRs
remain non-reach by design: a doc-only PR is not a substance-
classification PR and the cross-repo-drift gate has no business
gating it. Foreign-workflow-only PRs (e.g. an edit to `release.yml`)
also remain non-reach by design.

**Reach-closure regression-anchors.** TV-BPC-09 +
TV-BPC-11 + TV-BPC-13 + TV-BPC-14 in
`tests/infra/test_branch_protection_consistency_audit.py` pin the
post-Tag-16 reach shape. Any future YAML-edit that drops a Pfad-A
entry surfaces under a single-entry-failure message ("entry X is
missing") in TV-BPC-13. Any future re-addition of the workflow to
the narrow-by-design cohort surfaces in TV-BPC-14. Any new
non-reach drift on the in-scope classes (code-only, test-only,
dashboard-only) surfaces in TV-BPC-09 / TV-BPC-11.

**Why the gate's job stays narrow.** The path-filter only governs
WHEN the workflow runs, not WHAT it audits. The substance audit
itself (the curated mirror-pair table in the workflow job) is
unchanged; widening the filter does not widen the audit surface,
it only lets the audit gate run on more PR-classes so that the
Required-status-marker can report instead of stalling.

**Universal-trigger rule.** Going forward: a workflow is Required-fit
only if it triggers on every PR-class that is in-scope of its purpose.
The §6 consistency test pins this rule with vectors TV-BPC-09 through
TV-BPC-12.

---

## 5. Mira-Hand operator steps

These steps are **not** automated. Branch-protection edits sit with
the operator under the continuous-mode rule
`feedback_anti_eskalations_drift` (operator-touch on Mira-Hand-Operator,
no AR sighting needed for routine apply).

### 5.1 Re-discover the exact check-display-name

Before adding any check to the required-set, run one green PR through
the workflow, then:

```sh
gh pr view <num> --repo wakir-labs/<repo> \
  --json statusCheckRollup \
  --jq '.statusCheckRollup[] | select(.conclusion=="SUCCESS") | .name'
```

The strings printed are the canonical check-display-names. Copy them
verbatim (including parentheses, version suffixes, spaces).

### 5.2 Apply the required-set

```sh
gh api -X PATCH repos/wakir-labs/<repo>/branches/main/protection/required_status_checks \
  -F strict=true \
  -F 'contexts[]=<exact-check-name-1>' \
  -F 'contexts[]=<exact-check-name-2>' \
  -F 'contexts[]=<exact-check-name-3>'
```

### 5.3 Verify

```sh
gh api repos/wakir-labs/<repo>/branches/main/protection \
  --jq '.required_status_checks.contexts'
```

Output must list exactly the intended set, in any order. A trailing
PR run on a topic branch should show all listed contexts as required
in the PR check-rollup (`gh pr checks <num>`).

### 5.4 Roll-back

If a freshly-added required-check stalls at PENDING for a known-green
workflow, the name is almost certainly mis-cased or mis-suffixed.
Remove the offending entry:

```sh
gh api -X DELETE repos/wakir-labs/<repo>/branches/main/protection/required_status_checks/contexts \
  -F 'contexts[]=<mis-spelled-name>'
```

Then re-derive per 5.1 and re-apply per 5.2.

---

## 6. Drift-detection in CI

The hermetic test `tests/infra/test_branch_protection_consistency_audit.py`
pins the expected required-sets per repo into the CI suite. If
operations changes a required-set, the test must be updated in the same
PR (or the PR will fail the wakir-runtime test-lane). This is the
intended coupling: operations-drift surfaces immediately, no silent
re-shape of the trust-perimeter.

The test does **not** make live API calls; it consumes mock-fixtures
shaped exactly like the real `gh api` JSON output. The fixtures are
embedded in the test file.

---

## 7. Open items

* **Ready-to-apply (Mira-Hand-Operator-pending, 2026-05-17):** promote
  `cross-repo drift (wakir-runtime ↔ wakir-protocol)` to required on
  `wakir-runtime/main`. Pre-flight checklist + Mira-Hand-Operator
  command-block in §4.2. Score-bewegung 8/9 (3-axis) → 9/9 (4-axis).
  Post-apply doc-sync: update §2.1 + §4.3 table + flip TV-BPC-01
  fixture in the consistency test (§4.2 last paragraph).
* Promote CodeQL `Analyze (python)` to required on `wakir-runtime`
  once a CodeQL workflow is shipped to the runtime repo with a
  matrix-identical job-name to verify/protocol. (Workflow file does
  not yet exist in-tree — out-of-scope for this sprint.)
* Hash-Derivate-Drift Gate Required-promotion **withdrawn** (§4.1,
  §4.4). Re-consider only if the workflow's path-filter is widened
  to cover every PR-path-class the gate's purpose addresses; today
  it would be a forever-PENDING risk.
* Decide whether `e2e-vm-acceptance-gate` should ever enter the
  required-set — currently rated too flaky on hosted runners; live-VM
  lane is operator-hand per `feedback_live_bringup_sandbox_gap`. Also
  fails §4.5 reach (workflow trigger conditions narrow).
* Decide whether `phase-2-validation-gate` becomes Required after a
  path-filter audit (§4.5 row) — currently reach is too partial for
  Required-status.

— Kai
