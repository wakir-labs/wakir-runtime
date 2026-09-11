---
title: "Branch-Protection Required Status Checks (wakir-runtime)"
status: "active"
owner: "kai"
audience: "operator,maintainers"
updated: "2026-09-11"
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

State as of 2026-09-11, read via
`gh api repos/wakir-labs/wakir-runtime/branches/main/protection/required_status_checks`
after the Phase-4 W1 reduction from 16 to 10 contexts (ADR-0072).

| # | Job display name (verbatim) | Workflow file | Trigger reach | Since | Status |
|---|---|---|---|---|---|
| 1 | `License-Hygiene Gate (ADR-0061)` | `.github/workflows/license-gate.yml` | broad path filter | 2026-05 | ACTIVE |
| 2 | `wirelang suite with rfc8785 + jsonschema` | `.github/workflows/tests.yml` | broad path filter | 2026-05 | ACTIVE |
| 3 | `wirelang suite without rfc8785 / jsonschema (shadow)` | `.github/workflows/tests.yml` | broad path filter | 2026-05 | ACTIVE |
| 4 | `production-vs-sandbox drift envelope` | `.github/workflows/tests.yml` | broad path filter | 2026-05 | ACTIVE |
| 5 | `cross-repo drift (wakir-runtime ↔ wakir-protocol)` | `.github/workflows/cross-repo-drift-audit.yml` | code + tests + docs | 2026-05 | ACTIVE (to be replaced by the cross-repo compatibility gate, Phase 4 W4) |
| 6 | `verify-containerfile-base-image-digest-pins` | `.github/workflows/containerfile-digest-pin-gate.yml` | Containerfiles | 2026-05 | ACTIVE |
| 7 | `cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)` | `.github/workflows/cross-substrate-parity-gate.yml` | policies + quadlet + engine | 2026-05 | ACTIVE |
| 8 | `wirelang spec v0.4.3 freeze-seal probe` | `.github/workflows/wirelang-spec-freeze-seal-probe.yml` | spec directory | 2026-05 | ACTIVE |
| 9 | `cosign verify SPIRE images` | `.github/workflows/cosign-verify-images.yml` | image pins | 2026-05 | ACTIVE |
| 10 | `Cosign-Keyless-OIDC-Drift-Probe (daily)` | `.github/workflows/cosign-keyless-oidc-drift-probe.yml` | schedule + trust-root | 2026-05 | ACTIVE |
| 11 | `runtime acceptance gates` | `.github/workflows/runtime-acceptance-gates.yml` | wirelang + tests + docs + workflows | 2026-09 (renamed from the Phase-2 aggregator) | PENDING-OPERATOR (add after first green run on `main`) |

Removed in Phase 4 W1 (workflows deleted, contexts removed from
protection by the operator on 2026-09-11):
`Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)` (renamed,
see row 11), `pyramide layer-dependency DAG verify (6 layers, 16 edges)`,
`pyramide cross-run stability pin (5 fixtures, 3 runs each)`,
`g1-g2 operator-recipe smoke-validation`, `E2E verdict (READY / DRIFT / DEFECT)`,
`alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)`.

Planned additions (Phase 4): `proof-path` (W3, `proof-path.yml`) and
`cross-repo compatibility (protocol ↔ runtime ↔ verify)` (W4, replaces
row 5).

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
    "cross-repo drift (wakir-runtime ↔ wakir-protocol)",
    "production-vs-sandbox drift envelope",
    "wirelang suite without rfc8785 / jsonschema (shadow)",
    "verify-containerfile-base-image-digest-pins",
    "cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)",
    "wirelang spec v0.4.3 freeze-seal probe",
    "cosign verify SPIRE images",
    "Cosign-Keyless-OIDC-Drift-Probe (daily)",
    "runtime acceptance gates"
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
| 5 | `cross-repo drift (wakir-runtime ↔ wakir-protocol)` | clones `wakir-protocol`; network flake blocks merges | high |

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
