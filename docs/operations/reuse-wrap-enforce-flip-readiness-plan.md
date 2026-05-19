---
title: "REUSE-Wrap Pre-Merge Lint Enforce-Flip Readiness + Actual-Plan (Tag-62 + Tag-63)"
status: "active"
owner: "tomas"
audience: "operator,ar,engineering"
created: "2026-05-19"
tag: "tag-63"
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
  - "#394"
  - "#396"
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

## §7 - Actual-Flip-Execution-Recipe (Tag-63)

This section is the **executable** version of §5. §5 is the
human-readable recipe; §7 is the same recipe expressed as a
sequence of verifiable assertions, each of which the operator
can copy-paste verbatim into a host shell. Every assertion is
designed to short-circuit fast if a precondition is missing -- no
"forge ahead anyway" path.

### §7.1 - Pre-flip Stability-Window-Probe handshake

Before any settings mutation, the operator runs the new Tag-63
Stability-Window Probe workflow exactly once:

```bash
gh workflow run \
  reuse-wrap-enforce-flip-stability-window-probe.yml \
  --repo wakir-labs/wakir-runtime \
  --ref main \
  -f run_count=3
```

The probe runs the Tag-61 helper in
`--mode enforce-flip-readiness` three times back-to-back on the
current `main` workspace. It emits exactly one of three
verdicts:

| Probe verdict | Meaning | Next step |
|---|---|---|
| `STABILITY-WINDOW-CONFIRMED` | All 3 runs READY | Proceed to §7.2. |
| `STABILITY-WINDOW-NOT-YET` | At least one CAUTION/BLOCKED | Stop. Run §6.1 cleanup-first. |
| `STABILITY-WINDOW-DEFECT` | Helper crashed in probe | Stop. File bug; do not flip. |

The probe is the *sandbox-side* expression of §3's N-Run-Stability-
Window precondition. It does NOT replace the §3 main-branch
N-counter: the §3 counter is the *history* (three real green main
runs after Tag-62 merge), the §7.1 probe is the *handshake*
(three back-to-back probe runs on the operator's chosen ref).
Both must agree before the flip.

### §7.2 - Pre-flip three-precondition handshake

The operator confirms all three preconditions from §1, in this
order, exiting non-zero on any failure:

```bash
set -euo pipefail

# (a) N-Run: at least 3 consecutive green main-runs of the
# Tag-61 workflow (this is the §3 history check, not the §7.1
# probe).
GREEN_RUNS=$(gh api \
  /repos/wakir-labs/wakir-runtime/actions/workflows/reuse-wrap-pre-merge-lint.yml/runs \
  --jq '[.workflow_runs[] | select(.head_branch == "main")] | .[:3] | map(.conclusion)')
if ! echo "${GREEN_RUNS}" | grep -q '\["success","success","success"\]'; then
  echo "PRECONDITION-A-FAIL: last 3 main runs not all success -- ${GREEN_RUNS}"
  exit 1
fi

# (b) Required-Status-Check wiring under Branch-Protection
WIRED=$(gh api \
  /repos/wakir-labs/wakir-runtime/branches/main/protection/required_status_checks \
  --jq '.contexts | index("REUSE-Wrap Pre-Merge Lint (Tag-61)") // "null"')
if [ "${WIRED}" = "null" ]; then
  echo "PRECONDITION-B-FAIL: Required-Status-Check not wired"
  exit 1
fi

# (c) Coverage-Score: ENFORCE-FLIP-READY on current workspace
python tooling/ci/lint_reuse_ignore_wrap_pattern.py \
  --mode enforce-flip-readiness tests \
  | tee /tmp/reuse-flip-readiness.txt
if ! grep -q '^ENFORCE-FLIP-READY' /tmp/reuse-flip-readiness.txt; then
  echo "PRECONDITION-C-FAIL: readiness verdict not READY"
  exit 1
fi

echo "ALL-PRECONDITIONS-OK: proceed to §7.3 flip command."
```

If the script exits non-zero anywhere, the flip does NOT happen.
The operator inspects the failing precondition, fixes it (or
defers the flip), and re-runs.

### §7.3 - Flip command (single point of mutation)

The flip is exactly one `gh` call, recorded in the activity-log
*before* it is executed (so the audit-trail timestamp brackets
the actual change):

```bash
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "${NOW} REUSE-WRAP-LINT enforce-mode FLIP 0 -> 1 by operator" \
  >> /var/home/fred/AI-Corp/activity-log.md

gh variable set REUSE_WRAP_LINT_ENFORCE \
  --body "1" \
  --repo wakir-labs/wakir-runtime
```

This is the only command in the entire flip recipe that mutates
host state. Everything before it is read-only; everything after
it is verification.

### §7.4 - Post-flip verification

Within ten minutes of the flip, the operator triggers a
no-op smoke PR (e.g. whitespace-only edit on a docs file) and
confirms the workflow check shows up green:

```bash
gh pr create --title "smoke: post-flip verify (Tag-63)" \
  --body "Post-flip smoke test, no substance." \
  --base main --head smoke/post-flip-verify-tag63

# Wait for the Tag-61 check to settle
gh pr checks <PR-NUMBER> --watch \
  --required \
  | grep "REUSE-Wrap Pre-Merge Lint (Tag-61)"
```

Expected: the check shows up, conclusion `success`. If it shows
up as `failure`, the operator immediately runs §8 (Rollback).

### §7.5 - Audit-trail seal

After the smoke PR is merged or closed, the operator appends a
final audit-line:

```bash
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
SHA=$(git -C /var/home/fred/AI-Corp/agents-workspaces/mira rev-parse HEAD)
echo "${NOW} REUSE-WRAP-LINT enforce-mode SEALED post-smoke ${SHA}" \
  >> /var/home/fred/AI-Corp/activity-log.md
```

The seal-line is the document-of-record that the flip completed
cleanly. Without it, an auditor sees an unfinished episode.

---

## §8 - Rollback-Procedure (Tag-63 deepening of §6)

§6 listed the rollback variants; §8 turns them into a single
ordered procedure with a decision-routing helper. The mock-
substrate in `tooling/ci/mock_reuse_lint_rollback.py` exercises
the decision-logic hermetically; the host commands are the same
as in §6, but here they are sequenced with explicit hand-off
points.

### §8.1 - Decision routing via the mock-substrate

The operator first runs the mock-substrate against the current
workflow-run-history to get a canonical rollback verdict:

```bash
# Fetch the last 5 main-branch runs of the Tag-61 workflow
RUNS=$(gh api \
  /repos/wakir-labs/wakir-runtime/actions/workflows/reuse-wrap-pre-merge-lint.yml/runs \
  --jq '[.workflow_runs[] | select(.head_branch == "main")] | .[:5] | map({conclusion, head_sha})')

# Get current enforce state
STATE=$(gh variable get REUSE_WRAP_LINT_ENFORCE \
  --repo wakir-labs/wakir-runtime --json value -q .value)

# Run the decision-helper
python tooling/ci/mock_reuse_lint_rollback.py \
  --mode decide \
  --enforce-state "${STATE}" \
  --runs "${RUNS}" \
  --flake-budget 1 \
  --format text
```

Verdict routing:

| Mock verdict | Action |
|---|---|
| `MOCK-ROLLBACK-NO-OP` | Enforce already off. Nothing to do. |
| `MOCK-ROLLBACK-HOLD` | Reds fit flake-budget. Watch one more cycle, do not roll back. |
| `MOCK-ROLLBACK-RECOMMEND` | Run §8.2 un-flip immediately. |
| `MOCK-ROLLBACK-ESCALATE` | Run §8.2 un-flip AND notify Mira via inbox. |

### §8.2 - Un-flip command (single point of mutation)

The un-flip is the exact inverse of §7.3:

```bash
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "${NOW} REUSE-WRAP-LINT enforce-mode UN-FLIP 1 -> 0 by operator" \
  >> /var/home/fred/AI-Corp/activity-log.md

gh variable set REUSE_WRAP_LINT_ENFORCE \
  --body "0" \
  --repo wakir-labs/wakir-runtime
```

The Required-Status-Check wiring under Branch-Protection stays
in place; only the workflow's Stage-3 enforce-mode switch is
toggled. This means new PRs still *see* the check, it just goes
back to advisory-green-on-finding behavior.

### §8.3 - Post-rollback inspection

Within one hour of the un-flip, the operator runs:

```bash
python tooling/ci/lint_reuse_ignore_wrap_pattern.py \
  --mode hint tests \
  | tee /tmp/reuse-rollback-inspection.txt
```

This enumerates the unwrapped files that triggered the
regression. The operator then either:

* opens a cleanup-PR (§6.1 path), OR
* documents an exception (§6.3 path), OR
* if the helper itself is broken: opens a helper-fix PR.

The choice is recorded in the Mira inbox under
`agents-workspaces/mira/inbox/YYYY-MM-DD-reuse-rollback-<reason>.md`
following the Tag-59 / Tag-61 audit-trail format.

### §8.4 - Re-flip preconditions

After a rollback, a *second* flip attempt requires re-running the
entire §7 recipe from the top. There is no shortcut: a rollback
event means at least one precondition was wrong, and the operator
has no way to know which one without redoing the handshake.

The §7.1 Stability-Window-Probe is particularly important for
re-flip, because the rollback typically happens after a real
hot-fix landed on main, which means the readiness verdict may
have changed.

---

## §9 - Cross-Anchors

This section pins the cross-references that other docs and PRs
rely on. Anchors are listed in chronological order.

### §9.1 - Kai PR #389 (Tag-61, Branch-Protection-Wiring-Doc)

`docs/operations/branch-protection-required-checks-tag61-addendum.md`
is the addendum that holds the Required-Status-Check pool table
which §4 of this plan extends with Check #8. Kai is the Branch-
Protection-Owner; Tomás drafts the row in §4.2 and Kai imports.

Quote from the addendum (§4 of #389): "the Job-Display-Name MUST
match verbatim, including the `(Tag-NN)` suffix." This document
satisfies that rule -- §4.1 cites the literal name
`REUSE-Wrap Pre-Merge Lint (Tag-61)`.

### §9.2 - Kai PR #396 (Tag-62, Bulk-Activation Pre-Walk Recipe)

`tooling/ci/validate_bulk_activation_envelope.py` + supporting
doc. The bulk-activation recipe is the *general* operator-pattern
for adding multiple Required-Status-Checks at once; this plan
follows the *single-check* slice of that recipe (Check #8 only).
Once §7 here ships and the smoke-PR is green, Kai's next bulk-
activation cycle can subsume the manual §7.3 step into the bulk
pre-walk template. Until then, the Tag-63 recipe is canonical
for this one workflow.

### §9.3 - Tag-59 OTS N-Run-Stability-Window (precedent)

`docs/operations/branch-protection-required-checks-tag59.md` §4
established the N=3 pattern. §3 and §7.1 of this plan inherit
that constant. Any future change to N must update both docs in
the same commit -- divergence would create a precedent-vs-
practice gap that the next auditor would have to reconcile.

### §9.4 - Tag-62 PR #394 (predecessor)

`docs/operations/reuse-wrap-enforce-flip-readiness-plan.md` is
this document; PR #394 introduced §1-§6 and the
`enforce-flip-readiness` helper-mode. Tag-63 extends with §7-§9.
The Tag-62 18-test suite
(`tests/ci/test_reuse_lint_enforce_flip_readiness_tag62.py`)
remains in tree, unmodified; the new Tag-63 15-test suite
(`tests/ci/test_reuse_lint_enforce_flip_actual_plan_tag63.py`)
pins the §7-§9 additions + the mock-substrate.

### §9.5 - Mira Memory entries (rule-cross-refs)

* `feedback_sandbox_host_trennung` -- the host-side `gh variable
  set` is operator-hand; everything in this doc that does not
  mutate host state can live in claude-dev sandbox.
* `feedback_branch_protection_check_names` -- the exact-name
  rule for Required-Status-Check contexts (§4.1, §9.1).
* `feedback_anti_eskalations_drift` -- the flip itself is an
  operative-hygiene item; it does not need AR pre-approval, only
  the documented recipe and the audit-trail seal.

---

## §10 - Open questions (Tag-62 + Tag-63)

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
* **(Tag-63) Stability-Window-Probe trigger cadence:** the new
  `reuse-wrap-enforce-flip-stability-window-probe.yml` workflow is
  `workflow_dispatch` only. After enforce is live and the first
  cleanup-cycle has shipped, this could become a weekly cron
  to surface any quiet drift; that decision is post-Phase-3 and
  belongs in the next Tag-N planning cycle.
* **(Tag-63) Mock-substrate flake-budget default:** the rollback-
  decision mock defaults to `flake_budget=0`. Real operator use
  in §8.1 passes `--flake-budget 1` to absorb a single GHA-runner
  blip without an immediate rollback. The "right" default is
  empirical -- track the first month of post-flip runs and pick
  the budget that minimises both false-positive rollbacks
  (rolling back on a real flake) and false-negative holds
  (holding through a real defect).

--- Tomás
