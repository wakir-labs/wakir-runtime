---
title: "Branch-Protection Required Status Checks (wakir-runtime)"
status: "active"
owner: "kai"
audience: "operator,maintainers"
updated: "2026-09-14"
related_adrs:
  - "ADR-0020"
  - "ADR-0068"
  - "ADR-0072"
related_docs:
  - "docs/ci/aggregator-workflow.md"
  - "docs/operations/branch-protection-required-status-checks.md"
---

<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Branch-Protection Required Status Checks (wakir-runtime)

Canonical inventory of the `required_status_checks.contexts` set on
`wakir-labs/wakir-runtime` `main`, plus the operator recipe for
changing it. Branch protection matches the **job display name**
(`jobs.<id>.name` in the workflow file), not the workflow name and
not the file name. A context that no job reports under leaves every
PR pending forever.

Verified by `tooling/ci/verify_branch_protection_required_checks_doc.py`
and `tests/ci/test_branch_protection_check_names_audit.py` (every
`ACTIVE` context below must exist as a job display name in
`.github/workflows/`).

## §1 — Required-check inventory

State as of **2026-09-14**, read via
`gh api repos/wakir-labs/wakir-runtime/branches/main/protection`:
**13 contexts, all ACTIVE**, `enforce_admins: false` (enforcement scope
`non_admins`, so a repository admin can still merge past a red check).

The 2026-09-11 revision of this table said 12 rows with three
`PENDING-OPERATOR`. That was drift in two directions: the operator had
already activated all three Phase-4 contexts (rows 5, 11, 12), and
`secret-scan` (row 13) had been required for longer than this document
has existed without ever being inventoried. Both corrected here.

| # | Job display name (verbatim) | Workflow file | Trigger reach | Since | Status |
|---|---|---|---|---|---|
| 1 | `License-Hygiene Gate (ADR-0061)` | `.github/workflows/license-gate.yml` | every PR + push to `main` (no path filter) | 2026-05 | ACTIVE |
| 2 | `wirelang suite with rfc8785 + jsonschema` | `.github/workflows/tests.yml` | every PR + push to `main` (no path filter) | 2026-05 | ACTIVE |
| 3 | `wirelang suite without rfc8785 / jsonschema (shadow)` | `.github/workflows/tests.yml` | every PR + push to `main` (no path filter) | 2026-05 | ACTIVE |
| 4 | `production-vs-sandbox drift envelope` | `.github/workflows/tests.yml` | every PR + push to `main` (no path filter) | 2026-05 | ACTIVE |
| 5 | `cross-repo compatibility (protocol ↔ runtime ↔ verify)` | `.github/workflows/cross-repo-compat.yml` | every PR + push to main (no path filter) | 2026-09 (W4, replaces the cross-repo drift context) | ACTIVE (context swap done, see §2.3) |
| 6 | `verify-containerfile-base-image-digest-pins` | `.github/workflows/containerfile-digest-pin-gate.yml` | Containerfiles | 2026-05 | ACTIVE |
| 7 | `cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)` | `.github/workflows/cross-substrate-parity-gate.yml` | policies + quadlet + engine | 2026-05 | ACTIVE |
| 8 | `wirelang spec v0.4.3 freeze-seal probe` | `.github/workflows/wirelang-spec-freeze-seal-probe.yml` | spec directory | 2026-05 | ACTIVE |
| 9 | `cosign verify SPIRE images` | `.github/workflows/cosign-verify-images.yml` | image pins | 2026-05 | ACTIVE |
| 10 | `Cosign-Keyless-OIDC-Drift-Probe (daily)` | `.github/workflows/cosign-keyless-oidc-drift-probe.yml` | schedule + trust-root | 2026-05 | ACTIVE |
| 11 | `runtime acceptance gates` | `.github/workflows/runtime-acceptance-gates.yml` | every PR + push to `main` (no path filter) | 2026-09 (renamed from the Phase-2 aggregator) | ACTIVE |
| 12 | `proof-path` | `.github/workflows/proof-path.yml` | every PR + push to `main` (no path filter) | 2026-09 (ADR-0072 Phase 4 W3) | ACTIVE |
| 13 | `secret-scan` | `.github/workflows/secret-scan.yml` | every PR + push to `main` (no path filter) | pre-2026-09 (never inventoried until 2026-09-14) | ACTIVE |

**Invariant: a required aggregator job carries `if: always()` and
checks every `needs.<job>.result`.**
A job that declares `needs:` without a job-level `if: always()` is
*skipped* when a dependency fails, and GitHub does not block a merge on
a skipped required check — the gate fails open exactly when it matters.
`always()` alone is not enough: the job must also turn each
`needs.<job>.result` into its own exit code, before it runs its own
substance, or a green aggregate step reports the context green over a
red dependency. Both halves are pinned by
`tests/workflows/test_required_context_error_propagation.py`. Rows 11
(`runtime acceptance gates`) and 3 (`production-vs-sandbox drift
envelope`) were both in the fail-open shape until 2026-09-14.

**Invariant: a required workflow carries no `paths:` filter.**
A required status context that never reports leaves the pull request
pending forever, so every workflow feeding a required context fires on
every pull request and every push to `main`. Since ADR-0072 W5 this
holds for `license-gate.yml`, `tests.yml` and
`runtime-acceptance-gates.yml` (the filters were removed there), and it
already held for `cross-repo-compat.yml` and `proof-path.yml`. The
mirror of this invariant on the aggregator side is the `("**",)`
path-glob of every required row in `scripts/ci/ci_aggregator.py`
(`SUB_WORKFLOWS`); adding a `paths:` filter to a required workflow
without changing both places re-opens the forever-pending class.

Removed in Phase 4 W1 (workflows deleted, contexts removed from
protection by the operator on 2026-09-11):
`Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)` (renamed,
see row 11), `pyramide layer-dependency DAG verify (6 layers, 16 edges)`,
`pyramide cross-run stability pin (5 fixtures, 3 runs each)`,
`g1-g2 operator-recipe smoke-validation`, `E2E verdict (READY / DRIFT / DEFECT)`,
`alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)`.

Row 12 (`proof-path`) is the Phase-4 proof-path gate (ADR-0072 4b): it
runs `make demo-proof` on a clean runner with a pinned wakir-verify and
hard-fails through `scripts/ci/validate_demo_proof_report.py` unless all
five steps are `ok` with exit code `0` and step details that agree with
those statuses, and the report names the commit under test. Active
since the operator step of §3 item 4.

Row 5 is the W4 replacement of `cross-repo drift (wakir-runtime ↔ wakir-protocol)`
(byte-level drift audit, removed together with
`cross-repo-drift-allowlist-audit.yml`); the swap described in §2.3 has
been carried out.

Trigger discipline — **required contexts must never be path-filtered**:
a required context is matched per PR head commit; if the workflow that
reports it declares `paths:` under `pull_request:` and the PR does not
touch those paths, the check never reports and the PR stays pending
forever (`mergeStateStatus: BLOCKED`, see memory
`feedback_branch_protection_check_names`). Every workflow in the table
above therefore fires on every pull request and every push to `main`
without a `paths:` filter (removed in Phase 4 W1 for rows 6–10). If a
required workflow has expensive steps, skip the substance inside the job
via a change-detection step — the job itself must always run and end in
`success`. `workflow_dispatch` runs on the branch do not attach to the
PR rollup and cannot substitute for a `pull_request` run.

Display-name discipline:

- Copy names **verbatim**, including Unicode arrows (`↔`), parentheses
  and spaces.
- The name comes from `jobs.<id>.name:`, not from the top-level `name:`.
- On any mismatch, the check-run name that GitHub actually created wins;
  see the verification checklist in §3.

## §2 — Operator activation recipe

Changing branch protection is an operator-hand step. Agent sandboxes do
not hold a token with `administration:write`.

### §2.1 — gh api path (recommended)

```bash
# Snapshot before the change
gh api repos/wakir-labs/wakir-runtime/branches/main/protection/required_status_checks \
  --jq '.contexts' > /tmp/required-checks-before.json

# Replace the contexts array (PATCH replaces the whole list; include every
# context that must remain)
gh api -X PATCH repos/wakir-labs/wakir-runtime/branches/main/protection/required_status_checks \
  --input - <<'JSON'
{
  "strict": false,
  "contexts": [
    "License-Hygiene Gate (ADR-0061)",
    "wirelang suite with rfc8785 + jsonschema",
    "cross-repo compatibility (protocol ↔ runtime ↔ verify)",
    "production-vs-sandbox drift envelope",
    "wirelang suite without rfc8785 / jsonschema (shadow)",
    "verify-containerfile-base-image-digest-pins",
    "cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)",
    "wirelang spec v0.4.3 freeze-seal probe",
    "cosign verify SPIRE images",
    "Cosign-Keyless-OIDC-Drift-Probe (daily)",
    "runtime acceptance gates",
    "proof-path",
    "secret-scan"
  ]
}
JSON

# Snapshot after the change and diff
gh api repos/wakir-labs/wakir-runtime/branches/main/protection/required_status_checks \
  --jq '.contexts' > /tmp/required-checks-after.json
diff /tmp/required-checks-before.json /tmp/required-checks-after.json
```

The PATCH overwrites the complete list. The pre-change snapshot is the
source for everything that has to stay.

### §2.2 — Web UI path

`Settings → Branches → Branch protection rules → main → Edit → Require
status checks to pass before merging`. Search each display name
verbatim, add it, save. Re-read the list via gh api afterwards (§3.2).

### §2.3 — Context swap for the W4 merge (operator-hand) — DONE 2026-09

Historical record; the swap has been carried out and row 5 is ACTIVE.

The W4 PR deletes `cross-repo-drift-audit.yml`, so the old context
`cross-repo drift (wakir-runtime ↔ wakir-protocol)` never reports on that PR and
the PR shows `BLOCKED` until the context is swapped. This is expected.
Order of operations:

1. Confirm the other ten contexts are green on the PR and that the new
   job `cross-repo compatibility (protocol ↔ runtime ↔ verify)` reports `success`
   (`gh pr checks <n>`).
2. PATCH the required set: remove the old context, add the new one
   (the list below is the post-swap state; `runtime acceptance gates`
   stays on the list only if it was already required).

```bash
gh api -X PATCH repos/wakir-labs/wakir-runtime/branches/main/protection/required_status_checks \
  --input - <<'JSON'
{
  "strict": false,
  "contexts": [
    "License-Hygiene Gate (ADR-0061)",
    "wirelang suite with rfc8785 + jsonschema",
    "cross-repo compatibility (protocol ↔ runtime ↔ verify)",
    "production-vs-sandbox drift envelope",
    "wirelang suite without rfc8785 / jsonschema (shadow)",
    "verify-containerfile-base-image-digest-pins",
    "cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)",
    "wirelang spec v0.4.3 freeze-seal probe",
    "cosign verify SPIRE images",
    "Cosign-Keyless-OIDC-Drift-Probe (daily)"
  ]
}
JSON
```

3. Merge the W4 PR. The first `main` run of `cross-repo-compat.yml`
   happens on the merge commit; `push: main` is in its trigger set.
4. Flip the row-5 status above from `PENDING-OPERATOR` to `ACTIVE` in a
   follow-up commit and re-read the protection snapshot (§3.2).

## §3 — Pre-activation verification checklist

Run before adding a context:

1. **Job display name exists.** `grep -rn 'name: <display name>'
   .github/workflows/` returns exactly one job.
2. **Check run reports under that name.** `gh api
   repos/wakir-labs/wakir-runtime/commits/main/check-runs --jq
   '.check_runs[].name'` lists the name for the latest `main` commit.
3. **Trigger reach.** The workflow fires on `pull_request` for the PRs
   that should be blocked. A narrow `paths:` filter combined with a
   required context produces forever-pending PRs on non-matching diffs;
   the aggregator pattern in `docs/ci/aggregator-workflow.md` exists
   for that reason.
4. **Green on main.** At least one completed green run on `main` before
   the context becomes required.
5. **Open PRs.** `gh pr list --state open` and check that no open PR
   would be blocked unexpectedly by the new context.

## §4 — Activation order and risk map

When several contexts are added in one session, add the most isolated
ones first.

| Order | Context | Coupling failure mode | Risk |
|---|---|---|---|
| 1 | `verify-containerfile-base-image-digest-pins` | isolated, Containerfile pattern match only | low |
| 2 | `wirelang spec v0.4.3 freeze-seal probe` | isolated, spec directory + freeze marker | low |
| 3 | `runtime acceptance gates` | hermetic pytest suite, broad path filter | low |
| 4 | `cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)` | three-way parity across policy, quadlet and engine | medium |
| 5 | `cross-repo compatibility (protocol ↔ runtime ↔ verify)` | clones `wakir-protocol` + `wakir-verify`, runs `make demo-proof`; network flake blocks merges | high |
| 6 | `proof-path` | `pip install` from PyPI + `git+https` clone of `wakir-verify` at a pinned commit; network flake blocks merges; a verify-side API break at the pin surfaces here | medium |

Pause between steps: one smoke PR (§5) per context before the next
activation.

## §5 — Post-activation smoke

```bash
git checkout -b operator/smoke-required-check-$(date +%Y%m%d)
date -Iseconds > docs/ci/.smoke-touch.txt
git add docs/ci/.smoke-touch.txt
git commit -m "smoke(operator): trigger required checks"
git push -u origin HEAD
gh pr create --title "smoke(operator): required-check verification" \
             --body "Operator smoke test for required checks. Close after green." \
             --base main
sleep 30
gh pr checks --json name,state | grep -F '<display name>'
gh pr close --delete-branch
```

Pass criteria: the context appears in `gh pr checks` with the exact
display name, state is `pending` or `success` (never `skipped` or
missing), and the merge button is disabled while the check is pending.

Triage: `skipped` means the workflow's path filter excluded the smoke
touch; missing means a display-name mismatch (§3.1).

## §6 — Sandbox boundary

| Step | Agent sandbox | Operator-Hand |
|---|---|---|
| Editing this document | yes | no |
| `gh api` PATCH on branch protection | no | yes (ADR-0020 §10) |
| Web UI settings save | no | yes |
| Smoke-PR creation | yes (with push approval) | optional |
| `gh pr checks` read-back | yes (read-only) | optional |
| Protection snapshot read-back | yes (read-only) | optional |

Agent sandboxes never hold repository-administration tokens. Any
change to the required set is an operator-hand action recorded in the
PR that changes this document.
