---
title: "REUSE-Wrap Pre-Merge Lint Enforce-Flip Readiness Plan (Tag-62)"
status: "active"
owner: "tomas"
audience: "operator,ar,engineering"
created: "2026-05-19"
tag: "tag-62"
predecessor: "docs/operations/branch-protection-required-checks-tag61-addendum.md"
related_adrs:
  - "ADR-0020"
  - "ADR-0036"
  - "ADR-0061"
related_docs:
  - "docs/operations/branch-protection-required-checks-tag59.md"
  - "docs/operations/branch-protection-required-checks-tag61-addendum.md"
  - "docs/operations/cross-repo-drift-enforce-flip-readiness.md"
related_prs:
  - "#389"
  - "#392"
related_memory:
  - "feedback_branch_protection_check_names.md"
  - "feedback_sandbox_host_trennung.md"
  - "feedback_anti_eskalations_drift.md"
---

# REUSE-Wrap Pre-Merge Lint - Enforce-Flip Readiness Plan (Tag-62)

**Status:** Living operations document (read by humans + parsed by
tests).
**Scope:** Flip-decision for `REUSE_WRAP_LINT_ENFORCE` repo-var
from `0` (advisory hint-mode default) to `1` (blocking enforce-
mode) for the workflow shipped in Tag-61 PR #392
(`.github/workflows/reuse-wrap-pre-merge-lint.yml`).
**Authored:** 2026-05-19 (Tomás, Tag-62 Marathon Continuous-Mode).
**Helper:** `tooling/ci/lint_reuse_ignore_wrap_pattern.py`
(extended in Tag-62 with `--mode enforce-flip-readiness`).
**Companion-tests:** `tests/ci/test_reuse_lint_enforce_flip_readiness_tag62.py`.

The Tag-62 helper-extension is the substance behind §2 of this
plan; the doc is the operator's checklist for the flip itself.
This document is doc-form-only, no settings mutation; the actual
flip is operator-hand under the Mira-Sandbox-vs-Host-Operations
rule (Memory `feedback_sandbox_host_trennung`).

---

## §1 - Scope (Enforce-Flip preconditions)

The Tag-61 PR #392 workflow currently runs in **hint mode**
(`REUSE_WRAP_LINT_ENFORCE` unset, helper called with `--mode hint`,
verdict surfaced but job exits 0). Flipping to enforce-mode means:

1. Stage-3 of the workflow exits non-zero on
   `REUSE-WRAP-MISSING`, turning the job red on the PR check-tab.
2. Once wired as a Required-Status-Check under Branch-Protection
   (see §4), a red workflow blocks PR merge.
3. The helper's `enforce` mode (existing since Tag-61) is the
   actual gate; the readiness-mode (new in Tag-62) is the
   *measurement* that tells us whether the flip is safe.

The flip is gated on three preconditions, each of which is a §
in this plan:

| # | Precondition | Owner | Section |
|---|---|---|---|
| (a) | Workflow ran N times green on `main` without flake | Operator | §3 |
| (b) | Required-Status-Check wired under Branch-Protection | Operator | §4 |
| (c) | Baseline Coverage-Audit: repo is REUSE-WRAP-INTACT today | Tomás | §2 |

All three must be satisfied before the flip step in §5 is run.
Skipping any precondition reds `main` on the first PR that
touches an unwrapped SPDX literal -- which is exactly the
failure mode the workflow was designed to *prevent*, so a
premature flip would undo its own value.

### §1.1 - Anti-goal: do not flip for cosmetic reasons

The flip is **not** a victory lap. It is a load-bearing change
that gives the workflow real teeth. If the readiness signal is
amber (CAUTION) the flip *can* still be done by operator-hand,
but only with a documented rationale (e.g. "two known
unwrapped fixture files are intentionally out-of-scope, see
§6.3 rollback plan").

---

## §2 - Current-Stand Audit (Score + Verdict)

The Coverage-Score is computed by the helper in its new
`enforce-flip-readiness` mode:

```bash
python tooling/ci/lint_reuse_ignore_wrap_pattern.py \
  --mode enforce-flip-readiness \
  tests
```

### §2.1 - Score model

```
score = 100 * files_clean / max(1, files_clean + files_missing_wrap)
```

* `files_clean` = `tests/**/*.py` files with at least one SPDX
  literal AND a correct REUSE-IgnoreStart/End wrap (i.e. zero
  helper findings).
* `files_missing_wrap` = files with at least one SPDX literal AND
  at least one helper finding.
* `files_no_spdx` = files with zero SPDX literals at all; these
  are out-of-scope and **not** in the denominator.

### §2.2 - Verdict thresholds

| Verdict | Score | Meaning |
|---|---|---|
| `ENFORCE-FLIP-READY` | `>= 95` | Flip is safe; proceed with §3-§5. |
| `ENFORCE-FLIP-CAUTION` | `>= 80, < 95` | Flip is possible but requires documented rationale for the known unwrapped files. |
| `ENFORCE-FLIP-BLOCKED` | `< 80` | Flip is unsafe; cleanup the unwrapped files first, then re-run readiness. |

The 95 % bar matches the Tag-59 OTS N-Run-Stability-Window
threshold (>= 3 consecutive green main-runs == 100 % over a
3-run sample). The 80 % bar is below which the workflow is more
likely to red a legit PR than catch a real hot-fix-pattern,
based on the three known precedent episodes
(Tag-56 / Tag-59-hot-fix / Tag-60-self-fix).

### §2.3 - Day-1 baseline (2026-05-19)

To be filled in by the operator after first running the readiness
mode against the post-Tag-62-merge tip of `main`. The expected
verdict is `ENFORCE-FLIP-READY` because the three precedent
hot-fixes already wrapped the only known unwrapped files. If the
actual verdict differs, the operator records the actual numbers
here and proceeds with §6.1 (cleanup-first).

```
date: 2026-05-19 (Tomás, Tag-62 pre-merge measurement on worktree)
verdict: ENFORCE-FLIP-READY
score: 100.00
files_scanned: 348
files_clean: 10
files_missing_wrap: 0
files_no_spdx: 338
```

The measurement was taken on the Tag-62 worktree branch
`tomas/tag-62-reuse-lint-enforce-flip-plan` against the
`origin/main` baseline. Post-merge re-measurement is expected to
match (the Tag-62 PR adds one test file with a wrapped-fixture
header, which is itself a `files_clean` candidate, not a
missing-wrap one). The operator confirms the post-merge number
in §3 once the N-counter starts ticking.

---

## §3 - N-Run-Stability-Window (analog Tag-59 OTS pattern)

The workflow must run **N times green on `main`** before the
flip. N is fixed to **3** by analogy with the Tag-59 OTS
N-Run-Stability-Window for Required-Status-Check activation
(see `docs/operations/branch-protection-required-checks-tag59.md`
§4 Risk-Map-Notiz, "kann verzögert werden bis >= 3 grüne main-Runs
ohne 5xx-Flake").

### §3.1 - Run counting

```bash
gh api /repos/wakir-labs/wakir-runtime/actions/workflows/reuse-wrap-pre-merge-lint.yml/runs \
  --jq '.workflow_runs[] | select(.head_branch == "main" and .conclusion == "success") | {id, head_sha, run_started_at}' \
  | head -10
```

Only runs on `main` (not on PR refs) count. The three runs must
be consecutive: a single failed/flaky run on `main` resets the
counter to zero. This is the Tag-59 pattern verbatim; the
rationale is that a flake on `main` typically signals an external
dependency issue (GHA runner, package mirror, ...) and the
enforce-flip should not happen on top of an unstable substrate.

### §3.2 - Flake-budget

A *flake* is any non-green conclusion on `main` that is not
caused by an actual `REUSE-WRAP-MISSING` finding. (Real findings
on `main` are not flakes; they are a §6.1 cleanup item.) Flakes
reset the N-counter; real findings move the work to §6.1.

### §3.3 - Day-1 N-Counter (2026-05-19)

To be filled in by the operator post-Tag-62-merge. The first
green run on `main` after the Tag-62 PR merge increments the
counter to 1.

```
N-counter: 0/3
last-green-run: <none yet>
last-flake-run: <none yet>
```

---

## §4 - Branch-Protection Wiring (cross-reference Kai #389)

The flip itself is two changes that must happen in **this exact
order**:

1. **First:** wire `REUSE-Wrap Pre-Merge Lint (Tag-61)` (the
   job-display-name from `reuse-wrap-pre-merge-lint.yml`
   `jobs.reuse-wrap-pre-merge-lint.name`) as a Required-Status-
   Check under Branch-Protection.
2. **Second:** flip `REUSE_WRAP_LINT_ENFORCE` repo-var to `1`.

The inverse order opens a window where the workflow is blocking
but Branch-Protection doesn't know about it -- meaning PRs that
fail the workflow can still be merged. That defeats the purpose.

### §4.1 - Job-Display-Name discipline (Memory cross-ref)

The Required-Status-Check name MUST be the verbatim
`Job-Display-Name`, not the workflow-name. From
`reuse-wrap-pre-merge-lint.yml`:

```yaml
jobs:
  reuse-wrap-pre-merge-lint:
    name: REUSE-Wrap Pre-Merge Lint (Tag-61)
```

The name with the `(Tag-61)` suffix is the literal Required-Check
name. The Tag-59 / Tag-61 doc-pair (Kai #389) calls out this
trap explicitly: Memory `feedback_branch_protection_check_names`.

### §4.2 - Tag-61-Addendum check-position

The `REUSE-Wrap Pre-Merge Lint (Tag-61)` check joins the existing
Tag-59 + Tag-61 Required-Check pool as **Check #8** in the
Tag-61-Addendum table-extension (PR #389). Tomás drafts the
Tag-62-Addendum-row; Kai (Branch-Protection-Owner) merges it
into the addendum doc on the next branch-protection-review cycle.

| # | Job-Display-Name (verbatim) | Workflow-File | Source-PR | Aktivierungs-Status |
|---|---|---|---|---|
| 8 | `REUSE-Wrap Pre-Merge Lint (Tag-61)` | `.github/workflows/reuse-wrap-pre-merge-lint.yml` | #392 (Tomás, Tag-61) | **PENDING-OPERATOR** (Tag-62 plan §5) |

### §4.3 - Sandbox-Gap

The Branch-Protection mutation is operator-hand. The claude-dev
sandbox does not have host-side `gh` settings-mutation rights;
this is the standing ADR-0020 §10 rule (Memory
`feedback_sandbox_host_trennung`). The Tag-62 substance ends at
the doc + helper; the actual settings flip is captured in §5 as
a recipe for the operator.

---

## §5 - Flip-Trigger Operator-Hand Recipe

The flip is exactly three commands, in order, run by the
operator on the host (not in claude-dev sandbox). All three
preconditions (§1 table a/b/c) must be ticked before step 1.

### §5.1 - Step 1: confirm preconditions

```bash
# (a) N-Run: at least 3 consecutive green on main
gh api /repos/wakir-labs/wakir-runtime/actions/workflows/reuse-wrap-pre-merge-lint.yml/runs \
  --jq '[.workflow_runs[] | select(.head_branch == "main")] | .[:3] | map(.conclusion) | unique == ["success"]'
# expected: true

# (b) Required-Status-Check wiring
gh api /repos/wakir-labs/wakir-runtime/branches/main/protection/required_status_checks \
  --jq '.contexts | index("REUSE-Wrap Pre-Merge Lint (Tag-61)")'
# expected: integer (a position index), not null

# (c) Coverage-Score: ENFORCE-FLIP-READY
python tooling/ci/lint_reuse_ignore_wrap_pattern.py \
  --mode enforce-flip-readiness tests \
  | grep -q '^ENFORCE-FLIP-READY'
# expected: exit 0
```

If any of the three fail, do NOT proceed to step 2.

### §5.2 - Step 2: flip the repo-var

```bash
gh variable set REUSE_WRAP_LINT_ENFORCE --body "1" \
  --repo wakir-labs/wakir-runtime
```

This makes Stage-3 of the workflow exit non-zero on
`REUSE-WRAP-MISSING`. Future PRs that introduce unwrapped SPDX
literals will see a red check.

### §5.3 - Step 3: smoke-test the flip

Follow the Tag-59 §5 Smoke-Test-Recipe pattern (test-PR-Branch
with a harmless touch). Expected outcome: the touch does not
introduce unwrapped SPDX literals; the workflow stays green; the
required-check passes; the smoke-PR is merged or closed without
incident.

If the smoke-PR reds unexpectedly, the verdict is a §6 rollback,
not "ignore the red and merge anyway".

---

## §6 - Rollback Plan (post-flip defect)

The rollback is the inverse of the flip, but with one extra step
on top: a `task-archive.md` entry and a Mira-inbox note so the
incident is logged.

### §6.1 - Cleanup-first variant (verdict CAUTION or BLOCKED)

If §2's readiness verdict is CAUTION or BLOCKED, do NOT flip.
Instead:

1. Run `python tooling/ci/lint_reuse_ignore_wrap_pattern.py
   --mode hint tests` (the existing Tag-61 helper) to enumerate
   the unwrapped files.
2. Open a cleanup-PR that wraps each unwrapped SPDX literal in
   `# REUSE-IgnoreStart` / `# REUSE-IgnoreEnd` markers.
3. Merge the cleanup-PR.
4. Re-run readiness; once verdict is READY, return to §3.

### §6.2 - Post-flip un-flip

If the flip is in place and a regression (false-positive)
appears, the operator un-flips immediately:

```bash
gh variable set REUSE_WRAP_LINT_ENFORCE --body "0" \
  --repo wakir-labs/wakir-runtime
```

This puts the workflow back into hint-mode. The Required-Status-
Check stays wired (it just doesn't fail anymore), so no
Branch-Protection settings need to be touched.

### §6.3 - Documented-exception variant

If the verdict is CAUTION because two or three files are
intentionally out-of-scope (e.g. fixture-payload generators
that *must* contain raw SPDX strings for their tests to mean
anything), the operator can:

1. Add a `# REUSE-IgnoreStart` / `# REUSE-IgnoreEnd` wrap by
   hand anyway -- the helper's heuristic doesn't require the
   payload to be a real license-identifier, just that it
   *looks* like one.
2. Or accept the CAUTION verdict and document the exception in
   this section. The flip then proceeds with the documented
   rationale on file.

This section is intentionally permissive: the goal is "the
gate catches the hot-fix pattern", not "the gate catches every
literal that looks like SPDX". A 95 % score with a documented
5 % is functionally equivalent to a 100 % score for the
hot-fix-pattern-defense purpose.

### §6.4 - Audit-Trail

Every flip and un-flip event is recorded in
`/var/home/fred/AI-Corp/activity-log.md` and (if applicable) in
the Mira inbox under `agents-workspaces/mira/inbox/`. The
audit-trail format follows the Tag-59 + Tag-61 precedent:

```
DATE TIME UTC: REUSE-WRAP-LINT enforce-mode flipped from N to M
by <operator>. Pre-conditions: score=<S>, N-counter=<C>/3,
branch-protection=<wired|unwired>. Reason: <free-form>.
```

---

## §7 - Open questions (Tag-62)

* **N=3 vs N=5:** Tag-59 picked N=3 by analogy with the OTS
  audit-only-to-required pattern. For a workflow with as light
  a side-effect surface as this one (no cross-repo clone, no
  network), N=3 seems sufficient. If the first 3 main-runs are
  flake-free, the operator can flip; if not, raise N to 5 and
  document. (Tomás recommendation: stick with N=3.)
* **Future Tag-N-Addendum:** when Tag-62 PR ships and the
  readiness mode is in tree, the Tag-61-Addendum should grow a
  Check #8 row. That edit is owned by Kai
  (Branch-Protection-Owner). Tomás drafts the row in §4.2 of
  this doc; Kai imports it into the addendum.
* **Cross-substrate parity:** the `wakir-protocol` mirror does
  not have an equivalent license-gate-adjacent workflow yet.
  If it gets one, the readiness-mode helper should be mirrored
  with a `.../protocol` root argument. Out of Tag-62 scope.

--- Tomás
