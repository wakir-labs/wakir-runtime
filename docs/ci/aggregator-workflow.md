<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# CI Aggregator Workflow — Operator Documentation

**Status:** Active (ADR-0068 approved 2026-05-18).
**Owner:** Tomás Reinhart (Dev-Engineering).
**Source:** `.github/workflows/ci-aggregator.yml` + `scripts/ci/ci_aggregator.py`.

## 1. What this workflow does

The `ci-aggregator` workflow is the single Required-Status-Check on the
`main` branch of `wakir-runtime` (post-migration; see §4). It runs on
every pull request and every push to `main`, with no path-filter of its
own.

Its job is to look at the PR's changed-files set, decide which of the
six "critical sub-workflows" should be expected to fire under their
own path-filters, poll the GitHub-Actions REST API for their verdicts,
and emit a single aggregator verdict: `success`, `failure`, or
`pending` (the polling loop continues from `pending`).

### Why it exists

Before ADR-0068, the `main` branch had six Required-Status-Checks,
each with its own `paths:` filter. When a PR's changed-files set did
not intersect a Required-Check's filter, GitHub reported the check as
"never reported", and Branch-Protection treated that as `PENDING
forever`. The only way out was an admin-merge or a "trigger-file
touch" workaround PR. Tag-34/35/36 hit this pattern hard
(PRs #228, #232, #236, plus four Mira-Hand workaround PRs in two days).

The aggregator structurally eliminates this class of bug: it always
fires, so it always reports.

## 2. How it works

```
PR opened / synchronized                push to main
        |                                    |
        +------------------+-----------------+
                           |
                           v
                +-------------------+
                | ci-aggregator job |
                +-------------------+
                           |
                           v
        fetch changed-files via GitHub API
                           |
                           v
        for each sub-workflow in SUB_WORKFLOWS:
            decide expected/skip-ok via path_filter_triggers
                           |
                           v
        for each expected sub-workflow:
            poll workflow_runs API (head_sha)
            wait for completed status
            resolve per-job verdict by display-name
                           |
                           v
        aggregate verdicts:
          - any expected = (failure|cancelled|timed_out|missing) => FAILURE
          - any expected = pending                                => PENDING (re-poll)
          - all expected = success, rest = skip-ok                => SUCCESS
                           |
                           v
        emit markdown table to $GITHUB_STEP_SUMMARY
        exit 0 on success, 1 on failure
```

### Sub-Workflow Inventory (current)

The six sub-workflows the aggregator watches are declared in
`scripts/ci/ci_aggregator.py::SUB_WORKFLOWS`:

| # | Workflow | Job Display Name |
|---|---|---|
| 1 | `license-gate.yml`             | `License-Hygiene Gate (ADR-0061)` |
| 2 | `tests.yml`                    | `wirelang suite with rfc8785 + jsonschema` |
| 3 | `tests.yml`                    | `wirelang suite without rfc8785 / jsonschema (shadow)` |
| 4 | `tests.yml`                    | `production-vs-sandbox drift envelope` |
| 5 | `cross-repo-drift-audit.yml`   | `cross-repo drift (wakir-runtime ↔ wakir-protocol)` |
| 6 | `phase-2-validation-gate.yml`  | `Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)` |

These are exactly the six Required-Status names that Mira-Hand will
remove from Branch-Protection at migration Step 3 (see §4).

## 3. Adding a new sub-workflow

When a new critical sub-workflow lands (e.g. a future Welle-validation
that promotes from "advisory" to "Required"), add it to the inventory:

1. Edit `scripts/ci/ci_aggregator.py::SUB_WORKFLOWS` and append a new
   `SubWorkflow(...)` row. Fields:
   - `workflow_file`: the YAML file name under `.github/workflows/`.
   - `check_name`: the **exact** job display-name as shown on the PR
     check-run-tab. Branch-Protection check-name disambiguation
     applies here (see `feedback_branch_protection_check_names.md`).
   - `path_globs`: tuple of `paths:`-filter globs from the
     sub-workflow's `on.pull_request.paths` declaration.
   - `required`: set `True` only if this sub-workflow is/was a
     Branch-Protection Required-Status seed. New sub-workflows added
     after the Mira-Hand-Folge migration should leave this `False` —
     they participate in the aggregator's verdict without needing
     their own Branch-Protection entry.
2. Add a new hermetic test in
   `tests/ci/test_ci_aggregator_workflow.py` that pins the expected
   sub-workflow's path-filter behaviour.
3. Smoke-test locally:

   ```sh
   echo 'your/changed/path.py' >/tmp/changed.txt
   python scripts/ci/ci_aggregator.py \
       --mode=decide-only --changed-files=/tmp/changed.txt
   ```

4. Open a PR. The aggregator will exercise the new inventory entry
   on its own run (self-evidence pattern, same as ADR-0068's
   acceptance criterion).

## 4. Mira-Hand-Folge — Branch-Protection migration

The aggregator workflow itself lands on `main` first (this PR). Then
the cutover proceeds in four steps:

### Step 1 — Aggregator lives alongside existing Required-Status

After this PR merges, both run in parallel:
- the six existing Required-Status-Checks (license-gate, tests x3,
  cross-repo-drift, phase-2)
- the new `ci-aggregator` job (not yet Required)

### Step 2 — Observation window (~1 week, 2-3 PRs)

Mira observes the first 2-3 follow-up PRs:
- Does the aggregator's verdict match the union of the six legacy
  verdicts? (False-positive / false-negative check.)
- Do the per-sub-workflow `expected/skip-ok` decisions match the
  intuitive "would this sub-workflow fire on this changed-files set?"
- Do the polling-timings stay within the 75-minute job-level timeout?

### Step 3 — Cutover (Mira-Hand, GitHub-Repo-Settings)

Once observation is clean, Mira:
1. Adds `ci-aggregator` to the Branch-Protection Required-Status
   set.
2. Removes the six legacy names:
   - `License-Hygiene Gate (ADR-0061)`
   - `wirelang suite with rfc8785 + jsonschema`
   - `wirelang suite without rfc8785 / jsonschema (shadow)`
   - `production-vs-sandbox drift envelope`
   - `cross-repo drift (wakir-runtime ↔ wakir-protocol)`
   - `Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)`

After this point, the Forever-Pending class is structurally
impossible.

### Step 4 — Cleanup (optional, low priority)

The per-sub-workflow `paths:` filters remain in place. They still gate
**whether** the sub-workflow runs (cost control). The aggregator
handles the "what does it mean when a sub-workflow does not fire"
question.

If a sub-workflow's path-filter changes (e.g. a new directory added),
**also** update the corresponding `path_globs` tuple in
`SUB_WORKFLOWS`. The hermetic test
`test_inventory_workflow_files_exist_on_disk` catches missing files;
the `path_filter_triggers` tests cover the glob shapes. Drift between
the YAML `paths:` and the inventory `path_globs` is a known operator
risk — see §5.

## 5. Debugging

### Aggregator is RED — how to diagnose

1. Open the failed `ci-aggregator` run on the PR.
2. Scroll to the `$GITHUB_STEP_SUMMARY` markdown table.
3. Identify the sub-workflow with `Status = failure` (or `cancelled`,
   `timed_out`, `missing`).
4. Click the `Run` link in that table row.
5. **Do not admin-bypass.** The structural premise of ADR-0068 is
   that the aggregator's RED reflects a real sub-workflow failure;
   bypassing recreates the original problem on a different axis.

### Aggregator is `missing` for a sub-workflow

`missing` = the aggregator expected the sub-workflow to fire (its
path-filter matched), but no run was produced on the head SHA within
the polling window.

Common causes:
- The sub-workflow's `paths:` filter was tightened in a recent edit
  but the aggregator's `path_globs` inventory was not updated. Fix:
  update `SUB_WORKFLOWS` to match.
- A GitHub-Actions runner outage delayed the run beyond the polling
  window (75 min). Fix: re-run the aggregator job via
  workflow_dispatch.
- The sub-workflow file was renamed but the inventory still points
  to the old name. Fix: update `workflow_file` in the inventory and
  ensure `test_inventory_workflow_files_exist_on_disk` covers the
  new name.

### Aggregator is `pending` for >60 minutes

`pending` = at least one expected sub-workflow is still in progress
or queued. The aggregator's polling loop continues until completion
or the 75-minute job-level timeout.

If the aggregator times out at 75 min, the underlying sub-workflow
is likely stuck (queue-backed-up, runner-pool-saturation). Re-run via
workflow_dispatch after the underlying queue clears.

### Aggregator decision-table disagrees with intuition

Run the decide-only mode locally to inspect the decision:

```sh
git diff --name-only origin/main..HEAD > /tmp/changed.txt
python scripts/ci/ci_aggregator.py \
    --mode=decide-only \
    --changed-files=/tmp/changed.txt
```

If the table disagrees with what you expect, the inventory's
`path_globs` for the surprising row is likely out-of-sync with the
sub-workflow YAML's `paths:` filter. Fix the inventory.

## 6. Limitations and known risks

- **Single-point-of-failure:** the aggregator is **the** Required-
  Status. A bug in the aggregator itself (or in
  `scripts/ci/ci_aggregator.py`) blocks every merge. Mitigations: the
  hermetic test suite covers all decision-logic; bugs that escape
  into the I/O layer can be diagnosed via the `decide-only` mode
  and fixed via workflow_dispatch + temporary admin-bypass
  (Mira-Hand only). See ADR-0068 §"Risiken und Annahmen" item 1.

- **GitHub-API rate-limit:** at the default polling cadence (5s
  exponential to 60s, 60 attempts), one aggregator run makes ~20-40
  API calls per sub-workflow. With six sub-workflows and a typical
  10-PR day, ~1200-2400 API calls/day against a 5000/hr GITHUB_TOKEN
  quota. Headroom is comfortable. Surge scenarios (Phase-3c Cutover
  with 30+ PRs in a day) stay under quota.

- **`SubWorkflow.path_filter_triggers` is not a 1:1 GitHub-Actions
  reimplementation:** GitHub-Actions uses minimatch (Bash glob) with
  some custom extensions; we use `fnmatch.fnmatch` plus a few directory-
  prefix shortcuts. For the six current sub-workflows this is exact;
  for future entries with exotic globs (negation, `?`, character
  classes) a test in `tests/ci/test_ci_aggregator_workflow.py` should
  pin the expected behaviour.

## 7. Cross-references

- ADR-0068 — Status-Aggregator-Workflow als alleiniger Required-
  Status-Check (`decisions/0068-status-aggregator-workflow-required-check.md`).
- Tomás-Audit Tag-35 PR #231 — root-cause analysis of the path-
  filter / display-name double-axis problem
  (`docs/audit/branch-protection-check-names-audit-2026-05-18.md`).
- `feedback_branch_protection_check_names.md` — operator memory
  item documenting the display-name pitfall.
- `feedback_live_bringup_sandbox_gap.md` — sibling memory item that
  motivates the live-VM-acceptance-gate; that gate is **not** part
  of the aggregator's inventory because it is operator-hand-only
  (sandbox-vs-host separation, see `feedback_sandbox_host_trennung.md`).
