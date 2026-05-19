---
title: "Bulk-Activation Pre-Walk Recipe (Tag-62)"
status: "active"
owner: "kai"
audience: "operator,ar"
created: "2026-05-19"
tag: "tag-62"
predecessor: "docs/operations/branch-protection-required-checks-tag61-addendum.md"
related_adrs:
  - "ADR-0020"
  - "ADR-0036"
related_docs:
  - "docs/operations/branch-protection-required-checks-tag59.md"
  - "docs/operations/branch-protection-required-checks-tag61-addendum.md"
related_prs:
  - "#375"
  - "#389"
related_memory:
  - "feedback_branch_protection_check_names.md"
  - "feedback_sandbox_host_trennung.md"
  - "feedback_live_bringup_sandbox_gap.md"
---

# Bulk-Activation Pre-Walk Recipe (Tag-62)

Tag-59 (PR #375) and Tag-61 (PR #389) together document the
7-Pool Required-Status-Check target plus the recommended activation
order. Tag-62 closes the loop on **operator readiness** with an
executable pre-walk recipe: a script that parses both wiring docs,
assembles the target context list, and emits a verifiable plan
envelope **before** the Operator-Hand actually mutates Branch-
Protection.

Form: the substantive logic is a stdlib-only Python planner
(`tooling/ops/_bulk_activate_required_checks.py`) wrapped by a
Bash script (`tooling/ops/bulk_activate_required_checks.sh`). The
script defaults to `--dry-run` (read-only); `--enforce` is gated
behind a sandbox-boundary detection block that refuses to run
inside CI runners or without the operator-hand-marker env var.

## §1 — Recipe form and modes

The script has three relevant modes:

| Mode | Surface | Read-only? | Sandbox-OK? |
|---|---|---|---|
| `--dry-run` (default) | human-readable plan | yes | yes |
| `--dry-run --plan-json` | JSON envelope | yes | yes |
| `--enforce` | gh-api PUT prep + manual-stop | no (intent) | **no** |

Invocation form (from repo root):

```bash
# Default: read-only dry-run, prints human plan + verdict.
bash tooling/ops/bulk_activate_required_checks.sh

# Same, with --plan-json for downstream consumption.
bash tooling/ops/bulk_activate_required_checks.sh --plan-json

# Enforce path. Refused unless run from an Operator-Workstation
# with BULK_ACTIVATE_OPERATOR_HAND=1 and a non-CI environment.
BULK_ACTIVATE_OPERATOR_HAND=1 \
  bash tooling/ops/bulk_activate_required_checks.sh --enforce
```

Verdicts surfaced by the planner:

- **`PLAN-CONSISTENT`** — both docs parsed cleanly; 7 contexts
  assembled; bilanz-table set-equal to combined-table set; no
  duplicates; no empties.
- **`BULK-ACTIVATION-DEFECT`** — at least one defect: doc parse
  error, row-count mismatch (Tag-59 §1 ≠ 5 rows, Tag-61 §1 ≠ 2 rows,
  bilanz ≠ 7 rows), duplicate display-name, empty display-name, or
  bilanz set ≠ §1 set.

The shell wrapper then maps the planner exit code to its own
verdict:

- **`BULK-ACTIVATION-READY`** — dry-run completed, planner exited
  0 (`PLAN-CONSISTENT`). Operator can proceed to the actual
  Branch-Protection PUT.
- **`BULK-ACTIVATION-DEFECT`** — planner non-zero. Fix the docs
  first, re-run the dry-run, only then proceed.

## §2 — Idempotency contract

GitHub Branch-Protection PUT is **full-replace** on the
`required_status_checks.contexts` field. The script honours this
by always emitting the full 7-context target — never a delta.
That keeps the recipe trivially idempotent: if all 7 are already
active, the PUT is a no-op for those entries, and the Operator
will see an empty `diff` between pre- and post-snapshots (apart
from ordering, which the GitHub API is allowed to re-sort).

Idempotency notes:

1. The planner cannot read the live `contexts` from inside the
   sandbox (no token, by design). Pre-snapshot fetching is the
   Operator's responsibility, documented in §3.
2. The PUT body the script prepares contains ONLY the
   `required_status_checks` block. The Operator must merge that
   block into the existing full-protection PUT body (carrying
   `enforce_admins`, `required_pull_request_reviews`,
   `restrictions`, etc.) before invoking `gh api -X PUT`. The
   script intentionally refuses to auto-merge: dropping an
   unrelated setting silently would be worse than the verbose
   manual step.
3. Re-running the dry-run is always safe — it makes no API calls
   and produces no side effects beyond stdout + the JSON envelope.

## §3 — Operator-Hand walk (outside sandbox)

This walk runs on the Operator-Workstation, NOT in the
Mira-Sandbox. ADR-0020 §10 + memory
`feedback_sandbox_host_trennung.md` apply.

```bash
# 1) Pre-snapshot of live Required-Check contexts.
gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
  --jq '.required_status_checks.contexts' \
  > /tmp/branch-protection-required-checks-snapshot-pre-tag62.json

# 2) Dry-run the planner. Compare its 7-list against the snapshot.
bash tooling/ops/bulk_activate_required_checks.sh --plan-json \
  > /tmp/tag62-plan-envelope.json
jq '.required_status_checks.contexts' < /tmp/tag62-plan-envelope.json

# 3) Build the FULL PUT body. The script's --enforce path prints
#    the required_status_checks block; the Operator merges in the
#    other fields from the pre-snapshot.
gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
  > /tmp/branch-protection-full-pre-tag62.json
# … merge required_status_checks from plan-envelope into full-pre …

# 4) Execute the PUT.
BULK_ACTIVATE_OPERATOR_HAND=1 \
  bash tooling/ops/bulk_activate_required_checks.sh --enforce
# The script stops at the payload print; Operator runs the final
# gh api -X PUT manually with the merged body.

# 5) Post-snapshot + diff.
gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
  --jq '.required_status_checks.contexts' \
  > /tmp/branch-protection-required-checks-snapshot-post-tag62.json
diff /tmp/branch-protection-required-checks-snapshot-pre-tag62.json \
     /tmp/branch-protection-required-checks-snapshot-post-tag62.json
```

Disziplin: the Tag-59-§4 + Tag-61-§4 activation ORDER is preserved
in the planner output (rows 1..7 in pool order, low → high risk).
The PUT itself is one atomic call — but if the Operator chooses
the staged single-check pattern from Tag-59-§4 (one check at a
time with a smoke-PR between each), the planner still produces
the same end-state target list; the Operator runs the PUT 7 times
with growing `contexts` arrays.

## §4 — Pre-walk validator workflow

`.github/workflows/bulk-activation-pre-walk-validator.yml` is the
hermetic CI surface for this recipe. Three stages:

1. **Stage 1** — run the dry-run from the wrapper. Verdict line
   captured into `$GITHUB_OUTPUT`.
2. **Stage 2** — run the planner with `--json`, then run
   `tooling/ci/validate_bulk_activation_envelope.py` to assert
   envelope shape (top-level keys present, `tag=tag-62`,
   `target_pool_size=7`, `contexts` is a 7-element list of unique
   non-empty strings).
3. **Stage 3** — combine the two outputs into a final verdict:
   `BULK-ACTIVATION-READY` if both green, `BULK-ACTIVATION-DEFECT`
   otherwise.

Trigger is `workflow_dispatch` only. The workflow declares
`permissions: contents: read` — no write scope can be reached
from this CI job.

A defensive `CI=true` assertion in Stage 0 guards the planner's
sandbox-boundary detection: if a future CI-env change ever
silently unset `$CI`, the planner's `--enforce` refusal would
also degrade, and that would be caught here before the unlocked
path ever lands.

## §5 — Sandbox-Boundary

Tag-59 §6 + Tag-61 §6 sandbox-boundary tables extend here. This
Tag-62 doc and its script live entirely in the Mira-Sandbox; the
**actual Branch-Protection PUT remains Operator-Hand**.

| Phase | Mira-Sandbox | Operator-Hand |
|---|---|---|
| Doc-Erstellung (Tag-62, this doc) | **JA** (Kai-Spawn) | nein |
| Script-Erstellung + dry-run | **JA** (Kai-Spawn) | nein |
| `gh-api` Branch-Protection PUT (Tag-62 7-Pool) | nein | **JA** (Operator-Workstation) |
| Pre/Post-Snapshot Audit (read-only `gh api`) | **JA** (read-only) | optional |
| CI pre-walk validator workflow run | **JA** (workflow_dispatch) | optional |
| `--enforce` invocation | **nein** (refused by wrapper) | **JA** (with `BULK_ACTIVATE_OPERATOR_HAND=1`) |

Refusal mechanism (planner shell wrapper):

- `BULK_ACTIVATE_OPERATOR_HAND` env var must be `1`.
- `$CI` must NOT be set (CI runners are sandbox-class).
- `gh` CLI must be installed AND `gh auth status` must succeed.

Each missing precondition causes the wrapper to exit code 2 with
a `REFUSED:` line on stderr. The CI workflow asserts `$CI=true`
in Stage 0 to verify the detection contract still holds.

Memory cross-refs:

- `feedback_sandbox_host_trennung.md` — Mira-Sandbox never holds
  Operator-write scope.
- `feedback_branch_protection_check_names.md` — the planner copies
  display-names verbatim from the docs to avoid PR #102-style
  forever-pending bugs.
- `feedback_live_bringup_sandbox_gap.md` — live PUT belongs on the
  Operator-Workstation; CI validators are doc-form only.
- ADR-0020 §10 — "Kein Push auf Remote-Repos ohne explizite
  CEO-Freigabe pro Push". Branch-Protection-PUT is inherently
  Operator-Hand, not Kai-Hand.

— Kai (Tag-62, 2026-05-19)
