<!--
SPDX-License-Identifier: BUSL-1.1
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# ADR-0068 Migration-Step-3 Runbook

**Owner:** Mira-Hand (operator-touch). Engineering authored by
Reza Tehrani (Tag-39).

**Anchors:**
- ADR-0068 (approved 2026-05-18, Status-Aggregator-Workflow als
  alleiniger Required-Status-Check)
- Script: `scripts/ci/adr-0068-migration-step-3-cutover.py`
- Tests: `tests/ci/test_adr_0068_migration_step_3.py`
- Tracker (Noa, PR #251): `scripts/observability/aggregator-failure-rate-tracker.py`
- Audit pin: `tests/ci/test_branch_protection_check_names_audit.py`

## 1. What this script does

Patches the GitHub branch-protection
`required_status_checks.contexts` list on `wakir-labs/wakir-runtime/main`
from the pre-cutover multi-name set:

- `License-Hygiene Gate (ADR-0061)`
- `wirelang suite with rfc8785 + jsonschema`
- `cross-repo drift (wakir-runtime ↔ wakir-protocol)`

to the post-cutover single-name set:

- `ci-aggregator`

(Source of truth for the pre-cutover set: live
`gh api repos/wakir-labs/wakir-runtime/branches/main/protection`
output, captured at 2026-05-18 09:15 CEST per the Tag-35 audit doc.
If new required names were added between then and the cutover, the
`--dry-run` output will surface them and the runbook should be
re-read against that live state. Note the auftrag mentioned "6
legacy names"; the audit doc and the test-pinned constant currently
list 3. The script captures whatever is live at cutover time into
the backup, so the discrepancy is non-blocking - but the operator
should reconcile it with the audit doc as part of the cutover.)

## 2. Prerequisites

Before running this script:

1. **Aggregator has been live ≥ 7 days.** ADR-0068 was approved
   2026-05-18; earliest cutover date is therefore 2026-05-25.
2. **Aggregator has been observed clean.** Noa's tracker
   (`scripts/observability/aggregator-failure-rate-tracker.py`)
   must report `summary.drift_event_count == 0` over at least the
   most recent 50 aggregator runs.
3. **Operator (Mira-Hand) authorization is explicit.** Either set
   `MIRA_HAND_AUTHORIZED=1` in the shell env, or pass
   `--mira-hand-authorized` on the command line.
4. **`gh` CLI is installed** and authenticated with admin scope on
   `wakir-labs/wakir-runtime` (the
   `repos/{owner}/{repo}/branches/{branch}/protection` endpoint
   requires repo-admin).
5. **You are in a fresh shell.** No leftover env vars from
   previous test runs.

## 3. Step-by-step procedure

### 3.1 Generate a fresh tracker snapshot

Run Noa's tracker against live aggregator runs and save the JSON
output:

```sh
python scripts/observability/aggregator-failure-rate-tracker.py \
    --runs 100 \
    --output-json /tmp/aggregator-tracker.json
```

(See Noa's PR #251 for tracker-specific flags. The relevant output
for this script is the JSON file path.)

### 3.2 Run the dry-run

```sh
python scripts/ci/adr-0068-migration-step-3-cutover.py \
    --dry-run \
    --tracker-json /tmp/aggregator-tracker.json \
    --mira-hand-authorized
```

Expected output:

```
ADR-0068 Migration-Step-3 Gate Report
=====================================
  [OK  ] gate-drift: drift_event_count=0 over <N> runs (>= min 50)
  [OK  ] gate-time: <N> day(s) since ADR-0068 approval (2026-05-18); >= min 7
  [OK  ] gate-operator: authorized via cli(--mira-hand-authorized)

Verdict: ALL GATES PASSED -- cutover may proceed.

Cutover plan for wakir-labs/wakir-runtime:
  Pre-cutover  contexts (3):
    - License-Hygiene Gate (ADR-0061)
    - wirelang suite with rfc8785 + jsonschema
    - cross-repo drift (wakir-runtime ↔ wakir-protocol)
  Post-cutover contexts (1):
    + ci-aggregator
  Backup file: backup/branch-protection-pre-migration-<TS>.json
```

**If any gate is `FAIL`, stop and read the detail message.** The
most likely failure modes:

- `gate-drift` failed: aggregator verdict diverged from legacy-name
  union at least once. Investigate the drift event, extend the
  observation window, do not cutover.
- `gate-time` failed: not yet 7 days since approval. Wait.
- `gate-operator` failed: forgot to set the env var or flag.
- "no rollup for `ci-aggregator`": the tracker JSON does not contain
  an entry for the aggregator workflow itself. Re-run the tracker
  with `--include ci-aggregator` or equivalent.

### 3.3 Apply the cutover

Once dry-run is green:

```sh
python scripts/ci/adr-0068-migration-step-3-cutover.py \
    --apply \
    --tracker-json /tmp/aggregator-tracker.json \
    --mira-hand-authorized
```

The script will:

1. Re-evaluate all three gates.
2. Read the current branch-protection state via `gh api`.
3. Atomic-write a timestamped backup to
   `backup/branch-protection-pre-migration-{YYYYMMDDTHHMMSSZ}.json`.
4. Issue the PATCH via
   `gh api --method PATCH .../branches/main/protection/required_status_checks`.

**Note:** This patch updates the `required_status_checks` sub-object
only. `enforce_admins`, `required_pull_request_reviews`,
`restrictions`, and other branch-protection settings are untouched.

### 3.4 Post-cutover verification

After `--apply` returns:

1. Re-read live state:
   ```sh
   gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
       --jq '.required_status_checks.contexts'
   ```
   Expected: `["ci-aggregator"]`.

2. Flip the test pin: open a new PR that sets
   `BRANCH_PROTECTION_MIGRATED = True` in
   `tests/ci/test_branch_protection_check_names_audit.py`. The
   merge of that PR is the canonical Mira-Hand-touch that marks
   the migration as Done.

3. Open a tiny no-op PR against `main` to confirm the new required
   check fires correctly (single `ci-aggregator` check shows on the
   PR's checks page, no forever-pending names appear). Close
   without merging.

4. Update `activity-log.md` with the cutover timestamp and the
   backup file path.

## 4. Rollback

If post-cutover monitoring shows aggregator regressions (e.g. the
aggregator starts failing on PRs that should pass, or it never
finishes for some workflow class), restore the legacy names:

```sh
python scripts/ci/adr-0068-migration-step-3-cutover.py \
    --rollback backup/branch-protection-pre-migration-<TS>.json \
    --mira-hand-authorized
```

This re-instates the exact `required_status_checks.contexts` list
that was live at cutover time. The rollback does NOT re-run the
three-gate read (rollback is an emergency operator action by
definition) but still requires operator authorization to avoid
accidental restoration during routine script invocation.

After a rollback:

1. Re-verify live state matches the backup:
   ```sh
   gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
       --jq '.required_status_checks.contexts'
   ```

2. Set `BRANCH_PROTECTION_MIGRATED = False` if you had previously
   flipped it. (The `test_migration_flag_pins_ci_aggregator_when_done`
   test will fail loudly if the flag and the live state disagree.)

3. Open an incident-note in `decisions/` describing why the
   rollback was needed; this informs the next-attempt readiness
   criteria.

## 5. Sandbox / hermetic-test mode

The script accepts two fixture-mode flags for offline testing:

- `--fixture-current-protection <path>`: read the current
  branch-protection JSON from a file instead of calling `gh api`.
- `--tracker-json <path>`: always reads from a file (no network
  call for this input).

When invoked under `--dry-run` with both fixture flags, the script
performs zero network I/O and exits with 0 (gates green) or 1
(gates not green). This is the mode used by
`tests/ci/test_adr_0068_migration_step_3.py`.

## 6. Common errors

| Symptom | Cause | Fix |
| --- | --- | --- |
| `error: --tracker-json is required` | Forgot to pass `--tracker-json` | Add the flag and a valid file path. |
| `tracker payload missing 'summary.drift_event_count'` | Tracker JSON was not produced by Noa's PR #251 script, or schema bumped without updating this gate | Re-run Noa's tracker; if schema bumped, file a follow-up to update `gate_drift`. |
| `gh CLI not found` | `gh` not in `PATH`, or wrong binary | Install GitHub CLI; or pass `--gh-path /full/path/to/gh`. |
| `gh api PATCH failed (exit 1): HTTP 404` | Token lacks repo-admin scope | Re-auth with `gh auth refresh --scopes admin:repo`. |
| `gh api PATCH failed (exit 1): HTTP 422` | Payload schema mismatch (e.g. unknown context name) | Re-read the live protection state; reconcile with `TARGET_REQUIRED_CONTEXTS`. |
| `Refusing to --apply: at least one gate failed` | Self-evident from gate-report output | Address the failing gate per §3.2. |
| `Refusing to rollback: operator authorization required` | Missing env / flag | Set `MIRA_HAND_AUTHORIZED=1` or pass `--mira-hand-authorized`. |

## 7. What this script will not do

- It will not touch `required_pull_request_reviews`,
  `enforce_admins`, `restrictions`, `allow_force_pushes`, or any
  other branch-protection setting outside
  `required_status_checks`.
- It will not write to any file outside `backup/` (and only inside
  the directory passed via `--backup-dir`).
- It will not create or delete branches.
- It will not call any GitHub endpoint other than the two it
  documents (`GET .../branches/main/protection` and
  `PATCH .../branches/main/protection/required_status_checks`).
- It will not silently downgrade `strict` from `true` to `false`.
  The PATCH always re-sends `"strict": true`.

— Reza
