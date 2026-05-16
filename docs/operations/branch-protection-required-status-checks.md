<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Branch-Protection Required-Status-Checks — Cross-Repo Inventory

**Status:** Living operations document.
**Scope:** All three public repos under `wakir-labs/` org.
**Last audit:** 2026-05-16 (Kai, Sprint-CI-Gate-Konsolidierung).
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

| Check display-name | Defined in | Job-`name` field |
|---|---|---|
| `License-Hygiene Gate (ADR-0061)` | `.github/workflows/license-gate.yml` | `License-Hygiene Gate (ADR-0061)` |
| `wirelang suite with rfc8785 + jsonschema` | `.github/workflows/tests.yml` | `wirelang suite with rfc8785 + jsonschema` |

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

### 4.1 Recommended addition: Hash-Derivate-Drift Gate (wakir-runtime)

PR #101 (2026-05-15) added `hash-derivate-gate.yml` with job display-name
`Hash-Derivate-Drift Gate (Sprint-Stability Tag-3)`. This gate prevents
schema-fixture hash-derivative drift that would silently break the
external-verifier-conformance lane. It is a wakir-runtime-specific
concern (schema fixtures live there).

Recommendation: promote `Hash-Derivate-Drift Gate (Sprint-Stability Tag-3)`
to required on `wakir-runtime/main` after one green PR run confirms
the exact check-display-name (matcher discipline per
`feedback_branch_protection_check_names`).

### 4.2 Convergence-Score

The three-class Sollstellung yields a 3-axis score per repo
(license / code / security). Today:

| Repo | License | Code | Security | Score |
|---|---|---|---|---|
| `wakir-runtime` | 1 | 1 | 0 | 2/3 |
| `wakir-verify` | 1 | 1 | 1 | 3/3 |
| `wakir-protocol` | 1 | 1 | 1 | 3/3 |

Org-wide convergence-score: 8/9 = **0.889**. The remaining gap is
the CodeQL-promotion on wakir-runtime.

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

* Promote CodeQL `Analyze (python)` to required on `wakir-runtime`
  once the job-name matrix is confirmed identical to verify/protocol.
* Promote `Hash-Derivate-Drift Gate (Sprint-Stability Tag-3)` to
  required on `wakir-runtime` (Mira-Hand-Operator follow-up).
* Decide whether `e2e-vm-acceptance-gate` should ever enter the
  required-set — currently rated too flaky on hosted runners; live-VM
  lane is operator-hand per `feedback_live_bringup_sandbox_gap`.

— Kai
