<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Branch-Protection Required-Status-Checks — Cross-Repo Inventory

**Status:** Living operations document.
**Scope:** All three public repos under `wakir-labs/` org.
**Last audit:** 2026-05-16 (Kai, Sprint-Branch-Protection-Symmetrie-MINI;
post-Tag-4 refresh of the 2026-05-16 Sprint-CI-Gate-Konsolidierung audit).
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

Post-Tag-4 stand (re-verified 2026-05-16 ~19:36 CEST via
`gh api repos/wakir-labs/wakir-runtime/branches/main/protection`):

| Check display-name | Defined in | Job-`name` field |
|---|---|---|
| `License-Hygiene Gate (ADR-0061)` | `.github/workflows/license-gate.yml` | `License-Hygiene Gate (ADR-0061)` |
| `wirelang suite with rfc8785 + jsonschema` | `.github/workflows/tests.yml` | `wirelang suite with rfc8785 + jsonschema` |

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

### 4.2 Recommended addition: Mira-Hand-Operator score-bewegung — `cross-repo drift` (wakir-runtime)

PR #105 (2026-05-16) shipped `cross-repo-drift-audit.yml` with job
display-name `cross-repo drift (wakir-runtime ↔ wakir-protocol)`.
The gate enforces that any classification-drift of a wirelang substance
on `wakir-runtime` is mirrored on `wakir-protocol` or explicitly
allowlisted in `.cross-repo-drift-allowlist.yaml`.

Its path-filter (after PR #107 expansion):

```
wirelang/**
pyproject.toml
.cross-repo-drift-allowlist.yaml
.github/workflows/cross-repo-drift-audit.yml
```

Reach analysis (§4.5): the filter covers `wirelang/**` and
`pyproject.toml`, which together intersect every code-substance PR in
the repo. Test-only PRs (`tests/**`) do **not** trigger; workflow-only
PRs (other than this workflow itself) do not trigger; doc-only and
dashboard-only PRs do not trigger.

**Score-bewegung recommendation (Mira-Hand-Operator):** promote
`cross-repo drift (wakir-runtime ↔ wakir-protocol)` to required on
`wakir-runtime/main` once one green PR run confirms the exact
check-display-name. This adds a fourth axis to the Sollstellung
(cross-repo-classification-symmetry) and moves the org-wide score
from 8/9 → 9/9 on the §4.3 baseline below.

The reach-asymmetry is acceptable because the gate is by intent a
substance-level gate (not a test/doc/workflow gate). A PR that only
touches `tests/**` is by construction not a substance-classification
PR and does not need the cross-repo-drift check. The other Required
gates (`wirelang suite`, `License-Hygiene Gate`) cover those slices
already (§4.5 mapping).

CodeQL `Analyze (python)` on `wakir-runtime` remains an Open Item
(§7); it is a parallel security-axis closure but its workflow file
is not yet in the runtime tree, so it is out-of-scope for this
sprint.

### 4.3 Convergence-Score (updated)

The three-class Sollstellung yields a 3-axis score per repo
(license / code / security). Post-Tag-4 stand:

| Repo | License | Code | Security | Score |
|---|---|---|---|---|
| `wakir-runtime` | 1 | 1 | 0 | 2/3 |
| `wakir-verify` | 1 | 1 | 1 | 3/3 |
| `wakir-protocol` | 1 | 1 | 1 | 3/3 |

Org-wide convergence-score: 8/9 = **0.889** (unchanged since the
2026-05-16 baseline). The §4.2 cross-repo-drift addition would
introduce a fourth Sollstellung-axis specific to `wakir-runtime` —
it does not change the 3-axis 8/9 baseline above but adds a
runtime-specific bonus-axis. If we re-shape the Sollstellung to
4 axes (license / code / security / cross-repo-symmetry),
`wakir-runtime` becomes 3/4 once cross-repo-drift is Required, and
the org-wide score moves to (3 + 3 + 3) / 9 = 9/9 by ignoring the
cross-repo-symmetry axis on verify/protocol (which have nothing to
mirror against).

The decision how to shape the score-table (3-axis vs. 4-axis) is
operator-hand. This document records both readings; the consistency
test (§6) pins the 3-axis 8/9 baseline as the regression-anchor.

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
| `cross-repo-drift-audit.yml` | ✓ (via `wirelang/**`) | ✗ | ~ (only itself) | ✗ | ✗ |
| `phase-2-validation-gate.yml` | ~ (only `wirelang/**`) | ~ (only its test) | ~ (only itself) | ~ (only `docs/quality-gates/**`) | ✗ |

Legend: ✓ = full class triggers; ~ = partial trigger; ✗ = no trigger.

The two current Required gates on `wakir-runtime` (`tests.yml`,
`license-gate.yml`) are reach-clean (full ✓ on every class except
the workflow-only edge — and the workflow-only class is by construction
self-contained because the workflow YAML being changed lists itself
in its own filter). They are appropriate as Required.

`hash-derivate-gate.yml` has ✗ on the dashboard-only and doc-only
classes and partial on the rest — **not Required-fit** per §4.4.

`cross-repo-drift-audit.yml` has ✗ on three classes — but its
purpose is by intent narrow (substance-classification only), and
the other Required gates already gate the missing classes. It is
Required-fit **conditionally** (§4.2): operator must confirm via
one green PR run.

`phase-2-validation-gate.yml` is currently not a Required candidate
and per the reach-matrix it should not become one without a path-filter
widen (or a deliberate decision that Phase-2 validation only matters
on `wirelang/**` PRs — defensible but should be explicit).

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

* Promote `cross-repo drift (wakir-runtime ↔ wakir-protocol)` to
  required on `wakir-runtime/main` once one green PR run on a
  `wirelang/**`-touching topic-branch confirms the exact
  check-display-name (Mira-Hand-Operator follow-up; §4.2).
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
