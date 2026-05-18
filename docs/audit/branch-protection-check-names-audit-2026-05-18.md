# Branch-Protection Required-Status-Check-Names Audit

**Date:** 2026-05-18
**Auditor:** Tomás Reinhart (Dev-Engineering, Matrix-Lead)
**Scope:** wakir-runtime (primary), wakir-verify + wakir-protocol (secondary)
**Trigger:** Tag-34 RCA of PR #227 — PR #71 (Kai, 2026-05-15) merged with a
red E2E lane because the E2E job display-name was not in the
Required-Status-Checks set. Memory parallel: PR #102 forever-pending
2026-05-16.

---

## 1. Executive Summary

- **wakir-runtime current Required-Status-Checks set is dangerously thin:**
  only 3 jobs (`License-Hygiene Gate (ADR-0061)`,
  `wirelang suite with rfc8785 + jsonschema`,
  `cross-repo drift (wakir-runtime ↔ wakir-protocol)`).
- **PRs trigger 11 jobs** in 5 PR-firing workflows; 8 of them are
  not protected.
- **No drift** between the 3 currently-required names and the actual
  job display-names in wakir-runtime (i.e. the protected checks do
  match — there is no orphaned forever-pending name on `main`
  today).
- **Significant under-coverage gaps:** Phase-2-validation 6 sub-gates,
  `sandbox-suite-shadow`, `production-vs-sandbox drift envelope`,
  and 7 paths-filtered workflows (E2E, hermetic, parity, hash-drift,
  external-verifier-drift) are not on the required set.
- **Paths-filtered workflows cannot be unconditionally required** —
  doing so would forever-pend any PR that does not touch their paths.
  The recommended pattern is a **status-aggregator job** (always
  fires on every PR, evaluates "did the required-conditional job
  run AND pass IF its paths were touched") — out of scope for this
  audit, dropped as AR-touch follow-up.
- **wakir-verify + wakir-protocol drift confirmed:** Required name
  `pytest (3.13)` does not match actual job name `pytest (py3.13)`.
  Latent forever-pending bug; volume too low to have surfaced (2-3
  PRs each).

**Top-3 critical gaps (Forever-Pending Risk: medium-high):**

1. `pytest (3.13)` vs `pytest (py3.13)` mismatch in BOTH wakir-verify
   AND wakir-protocol branch-protection — silent latent bug.
2. `phase-2-validation-gate` 6 sub-gates not required → can land red
   on `main` (Doppelbetrieb-Score is the public stability promise).
3. `tests` workflow has 3 jobs but only one is required (`wirelang
   suite with rfc8785 + jsonschema`); `production-vs-sandbox drift
   envelope` and shadow-suite are not required → drift can land
   silently.

---

## 2. wakir-runtime Workflow Inventory

### 2.1 Full workflow list (28 workflows)

| # | Workflow file | Workflow `name:` | Triggered on | Jobs (display-name) | Currently Required? |
|---|---|---|---|---|---|
| 1 | build-rust-cli-bridge-audit-writer.yml | build-rust-cli-bridge-audit-writer | push, dispatch | `build wakir-persona-engine-bridge-audit-writer image` | no |
| 2 | build-rust-cli-lifecycle-state-machine.yml | build-rust-cli-lifecycle-state-machine | push, dispatch | `build wakir-persona-engine-fsm image` | no |
| 3 | build-rust-cli-recovery-workflow.yml | build-rust-cli-recovery-workflow | push, dispatch | `build wakir-persona-engine-recovery image` | no |
| 4 | build-rust-cli-state-backing.yml | build-rust-cli-state-backing | push, dispatch | `build wakir-persona-engine-state-backing image` | no |
| 5 | build-rust-cli-subscribe-loop.yml | build-rust-cli-subscribe-loop | push, dispatch | `build wakir-persona-engine-subscribe-loop image` | no |
| 6 | build-rust-cli-svid-workload-identity.yml | build-rust-cli-svid-workload-identity | push, dispatch | `build wakir-persona-engine-svid-workload-identity image` | no |
| 7 | build-rust-cli-v907-verify.yml | build-rust-cli-v907-verify | push, dispatch | `build wakir-v907-verify image` | no |
| 8 | build-wakir-persona-engine.yml | build-wakir-persona-engine | dispatch | `build wakir-persona-engine image` | no |
| 9 | build-wakir-provisioner.yml | build-wakir-provisioner | dispatch | `build wakir-provisioner image` | no |
| 10 | cosign-verify-images.yml | cosign-verify-images | dispatch | `cosign verify SPIRE images`, `digest-verify python:3.13-slim`, `cosign verify wakir-provisioner` | no |
| 11 | cross-repo-drift-audit.yml | cross-repo-drift-audit | push, **PR**, dispatch | `cross-repo drift (wakir-runtime ↔ wakir-protocol)` | **YES** |
| 12 | cross-substrate-parity-gate.yml | cross-substrate-parity-gate | push, **PR (paths-filtered)** | `cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)` | no |
| 13 | e2e-bringup-ci.yml | e2e-bringup-ci | push, **PR (paths-filtered)** | `Substance — source-shape + bootstrap-logic`, `Quadlet-Lint — podman quadlet --dryrun gate (Bug-23)`, `E2E — bootstrap against containerized Fedora substrate` | no (RCA: PR #71 incident root) |
| 14 | e2e-vm-acceptance-gate.yml | e2e-vm-acceptance-gate | push, **PR (paths-filtered)**, dispatch | `Harness-logic — hermetic gate grading`, `Real-VM — disposable Fedora-CoreOS acceptance-gate` | no |
| 15 | external-verifier-drift.yml | external-verifier-drift | push, **PR (paths-filtered)** | `python-bitcoinlib 0.11.2 on py3.12`, `python-bitcoinlib 0.12.1 on py3.12`, `python-bitcoinlib 0.12.2 on py3.12` (matrix-expanded) | no |
| 16 | hash-derivate-gate.yml | hash-derivate-gate | push, **PR (paths-filtered)** | `Hash-Derivate-Drift Gate (Sprint-Stability Tag-3)` | no |
| 17 | license-gate.yml | license-gate | push, **PR** | `License-Hygiene Gate (ADR-0061)` | **YES** |
| 18 | live-vm-acceptance.yml | live-vm-acceptance | dispatch | `Live-VM acceptance (...)`, `Live-VM acceptance Phase-3b (...)`, `Live-VM acceptance Phase-3b — aggregate` | no |
| 19 | phase-2-acceptance-gate.yml | phase-2-acceptance-gate | schedule, dispatch, push (NOT PR) | `Phase-2 Acceptance Gate (Doppelbetrieb-Score)` | no (push-only) |
| 20 | phase-2-validation-gate.yml | phase-2-validation-gate | push, **PR** | `Gate-2-1 Bridge-Forward-Symmetry`, `Gate-2-2 Konsistenz-Score Threshold`, `Gate-2-3 V907-Hash-Stability-Marker`, `Gate-2-4 Recovery-R1..R4-Mock-Drill`, `Gate-2-5 Subscribe-Loop-Lag-Mock`, `Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)` | no |
| 21 | phase-3c-observability-daily-snapshot.yml | phase-3c-observability-daily-snapshot | schedule, dispatch, push, **PR (paths-filtered)** | `Phase-3c Observability Baseline — Daily Snapshot` | no |
| 22 | phase-3c-welle-1-validation.yml | phase-3c-welle-1-validation | schedule, dispatch | `Phase-3c Welle-1 Validation (v907_verify)` | no (scheduled) |
| 23 | phase-3c-welle-2-validation.yml | phase-3c-welle-2-validation | schedule, dispatch | `Phase-3c Welle-2 Validation (svid_workload_identity)` | no (scheduled) |
| 24 | phase-3c-welle-3-validation.yml | phase-3c-welle-3-validation | schedule, dispatch | `Phase-3c Welle-3 Validation (bridge_audit_writer)` | no (scheduled) |
| 25 | phase-3c-welle-4-validation.yml | phase-3c-welle-4-validation | schedule, dispatch | `Phase-3c Welle-4 Validation (state_backing)` | no (scheduled) |
| 26 | phase-3c-welle-5-validation.yml | phase-3c-welle-5-validation | schedule, dispatch | `Phase-3c Welle-5 Validation (lifecycle_state_machine)` | no (scheduled) |
| 27 | phase-3c-welle-6-validation.yml | phase-3c-welle-6-validation | schedule, dispatch | `Phase-3c Welle-6 Validation (subscribe_loop)` | no (scheduled) |
| 28 | phase-3c-welle-7-validation.yml | phase-3c-welle-7-validation | schedule, dispatch | `Phase-3c Welle-7 Validation (recovery_workflow)` | no (scheduled) |
| 29 | resolve-image-pins-ci.yml | resolve-image-pins-ci | dispatch | `idempotent image-pin resolver` | no |
| 30 | sandbox-ci.yml | sandbox-ci | push, **PR** | `wirelang suite without rfc8785 / jsonschema` | no (not required, despite firing) |
| 31 | selinux-hermetic-lane.yml | selinux-hermetic-lane | push, **PR (paths-filtered)** | `Static-discipline — :Z sweep across bootstrap + Quadlets`, `Mutation-equivalence — Amara Zone-X automation` | no |
| 32 | tests.yml | tests | push, **PR** | `wirelang suite with rfc8785 + jsonschema`, `wirelang suite without rfc8785 / jsonschema (shadow)`, `production-vs-sandbox drift envelope` | partial — only `wirelang suite with rfc8785 + jsonschema` |

### 2.2 Current Required-Status-Checks set (from
`gh api repos/wakir-labs/wakir-runtime/branches/main/protection`)

```
1. License-Hygiene Gate (ADR-0061)
2. wirelang suite with rfc8785 + jsonschema
3. cross-repo drift (wakir-runtime ↔ wakir-protocol)
```

`strict: true` (branch must be up-to-date), `enforce_admins: false`.

### 2.3 Display-Name Match Audit (wakir-runtime)

| Required name | Actual job (in workflow) | Status |
|---|---|---|
| License-Hygiene Gate (ADR-0061) | license-gate.yml → `License-Hygiene Gate (ADR-0061)` | MATCH |
| wirelang suite with rfc8785 + jsonschema | tests.yml → `wirelang suite with rfc8785 + jsonschema` | MATCH |
| cross-repo drift (wakir-runtime ↔ wakir-protocol) | cross-repo-drift-audit.yml → `cross-repo drift (wakir-runtime ↔ wakir-protocol)` | MATCH |

No orphaned forever-pending names in wakir-runtime today. (PR #102
mismatch from 2026-05-16 was a name typo that has since been
reconciled per repo memory.)

---

## 3. wakir-verify + wakir-protocol Inventory

### 3.1 Workflows (identical sets, both repos)

| Workflow | Triggered on | Job display-names |
|---|---|---|
| ci.yml (`name: ci`) | push, **PR** | `pytest (py3.10)`, `pytest (py3.11)`, `pytest (py3.12)`, `pytest (py3.13)` (matrix-expanded with `py` prefix) |
| codeql.yml (`name: codeql`) | push, PR, schedule | `Analyze (python)` (matrix: `language: [python]`) |
| license-check.yml (`name: license-check`) | push, PR | `REUSE lint` |
| release.yml (`name: release`) | release, dispatch | `Build sdist + wheel`, `Publish to PyPI`, `Sign artifacts with Sigstore` |

### 3.2 Current Required-Status-Checks set (both repos, identical)

```
1. pytest (3.13)
2. REUSE lint
3. Analyze (python)
```

### 3.3 Display-Name Match Audit (verify + protocol)

| Required name | Actual job | Status |
|---|---|---|
| pytest (3.13) | ci.yml → `pytest (py3.13)` | **DRIFT — forever-pending latent** |
| REUSE lint | license-check.yml → `REUSE lint` | MATCH |
| Analyze (python) | codeql.yml → `Analyze (python)` | MATCH |

**Latent bug:** Any PR that depends on `pytest (3.13)` being a green
required-check will hang in "expected — waiting for status to be
reported". Volume in these repos is currently 2-3 PRs total — the
bug has not surfaced operationally, but will when PR throughput
ramps in Phase-3c.

---

## 4. Gap Analysis (wakir-runtime focus)

### 4.1 Class A — Critical jobs missing from Required-Status-Checks (HIGH)

These jobs DO fire on every PR (no paths-filter) but are not
required. They can land RED on `main` today.

| Job display-name | Workflow | Why critical |
|---|---|---|
| `wirelang suite without rfc8785 / jsonschema` | sandbox-ci.yml | Sandbox-lane parity. Diff vs production catches lib-pinning bugs (ADR-0027). |
| `wirelang suite without rfc8785 / jsonschema (shadow)` | tests.yml | Sister job to above; runs as part of `tests` workflow. Diff alone is OK if drift-envelope green. |
| `production-vs-sandbox drift envelope` | tests.yml | THE Mira-promise: "sandbox = production". A red here = product-spec violation. |
| `Gate-2-1 Bridge-Forward-Symmetry` | phase-2-validation-gate.yml | Phase-2 Doppelbetrieb invariant. |
| `Gate-2-2 Konsistenz-Score Threshold` | phase-2-validation-gate.yml | Phase-2 Doppelbetrieb invariant. |
| `Gate-2-3 V907-Hash-Stability-Marker` | phase-2-validation-gate.yml | Phase-2 Doppelbetrieb invariant. |
| `Gate-2-4 Recovery-R1..R4-Mock-Drill` | phase-2-validation-gate.yml | Phase-2 Doppelbetrieb invariant. |
| `Gate-2-5 Subscribe-Loop-Lag-Mock` | phase-2-validation-gate.yml | Phase-2 Doppelbetrieb invariant. |
| `Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)` | phase-2-validation-gate.yml | Aggregator alone is sufficient if it `needs:` all 5 gates AND fails on any red. Verified in workflow file: yes — `needs: [...]` lists all 5. Adding ONLY the aggregator is sufficient. |

**Recommendation:** Add 4 names to Required:
- `wirelang suite without rfc8785 / jsonschema (shadow)` (shadow lane inside `tests`)
- `production-vs-sandbox drift envelope`
- `Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)`
- Optional: `wirelang suite without rfc8785 / jsonschema` (separate sandbox-ci workflow — same display-name as shadow inside tests.yml WITHOUT the `(shadow)` suffix — these are DIFFERENT jobs, see Section 4.5)

### 4.2 Class B — Paths-filtered workflows (DO NOT BLINDLY REQUIRE)

These workflows have `paths:` filters on `pull_request`. If added
to Required-Status-Checks, **every PR not touching those paths
will forever-pend**. This is the exact failure pattern from PR
#102 and the broader forever-pending memory.

| Job | Filter | Recommended action |
|---|---|---|
| `Substance — source-shape + bootstrap-logic` (e2e-bringup-ci) | bootstrap.sh, quadlet/**, infra/spire/federation/quadlet/** | Status-aggregator pattern (see Class D) |
| `Quadlet-Lint — podman quadlet --dryrun gate (Bug-23)` | same | Status-aggregator |
| `E2E — bootstrap against containerized Fedora substrate` | same | Status-aggregator |
| `Harness-logic — hermetic gate grading` (e2e-vm) | bootstrap.sh, quadlet/**, harness/** | Status-aggregator |
| `Real-VM — disposable Fedora-CoreOS acceptance-gate` | same | Status-aggregator (note: self-hosted runner gated) |
| `Static-discipline — :Z sweep across bootstrap + Quadlets` (selinux) | bootstrap.sh, quadlet/** | Status-aggregator |
| `Mutation-equivalence — Amara Zone-X automation` | same | Status-aggregator |
| `Hash-Derivate-Drift Gate (Sprint-Stability Tag-3)` | wirelang/schemas/**, schema-registry/** | Status-aggregator |
| `cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)` | cosign-policy, quadlet rust-cli, backend-switch | Status-aggregator |
| `python-bitcoinlib X.Y.Z on py3.12` (matrix-expanded) | external_verifier/**, drift test, pyproject.toml | Status-aggregator |
| `Phase-3c Observability Baseline — Daily Snapshot` | observability-baseline-tracker, trigger-gate-aggregator | Status-aggregator |

**Pattern recommendation:** introduce a single workflow
`required-aggregator.yml` that fires on EVERY pull_request (no
paths filter) and evaluates the conditional gates. This is the
GitHub-Actions canonical solution for paths-filtered required
checks. **Out-of-scope for this audit (AR-touch follow-up).**

### 4.3 Class C — Display-name drift (wakir-runtime)

None on `main` today. Earlier incident with PR #102 has been
resolved (no orphaned name remains in the protection set).

### 4.4 Class D — Cross-repo drift (verify + protocol)

| Repo | Required name | Actual name | Class |
|---|---|---|---|
| wakir-verify | `pytest (3.13)` | `pytest (py3.13)` | DRIFT |
| wakir-protocol | `pytest (3.13)` | `pytest (py3.13)` | DRIFT |

**Fix-Klasse:** Either (a) AR-touches branch-protection to update
required name to `pytest (py3.13)`, OR (b) workflow PR edits the
ci.yml job name to drop the `py` prefix. Recommendation: **option
(b) — drop `py` prefix in ci.yml** because it is the change that
keeps the public matrix label stable across repos (and matches
common GitHub-pytest convention of bare version numbers in matrix
displays). This avoids AR-touch.

NOTE: this audit covers only display-name drift; it does NOT
re-author the verify/protocol workflows in this PR. A separate
PR per repo is recommended, owned by a Tag-36 spawn or hand-off.

### 4.5 sandbox-ci vs tests.yml shadow-suite double-naming

Observation: BOTH `sandbox-ci.yml` and `tests.yml` have a job
that produces the display-name `wirelang suite without rfc8785 /
jsonschema` (tests.yml suffixes it with ` (shadow)`).

Status: **not a drift** but a "two-workflows-one-near-name" smell.
The check-runs API confirms BOTH show up on PRs (different `name:`
display strings); GitHub deduplicates by check_run_id, not by
display-name, so this is operationally safe.

Recommendation: leave as-is (operationally safe), or rename the
`sandbox-ci` job to `wirelang sandbox suite (standalone lane)` in
a future hygiene pass. **Not in scope for this PR.**

---

## 5. Forever-Pending Risk Matrix

| Risk source | Probability | Impact | Mitigation |
|---|---|---|---|
| New required-check name typo (added without grep-match against live check-runs) | medium | high (PRs stall, eskaliert über AR) | Pre-flight: `gh api .../check-runs --jq '.check_runs[].name'` MUST be cross-grepped before any branch-protection edit; documented in this audit as a permanent rule. |
| Display-name change in workflow without branch-protection sync | medium | high | Workflow PRs that touch `name:` MUST have a checklist item "branch-protection-name sync done?" |
| Paths-filtered workflow added to required directly | low | high (forever-pending on every untouched PR) | Documented in §4.2: status-aggregator pattern only. |
| Matrix expansion (e.g. python: ['3.12','3.13']) drifts from required name | low | high | Pin matrix in branch-protection or use aggregator. |
| Verify/protocol `pytest (3.13)` drift surfaces at PR-throughput ramp | high (when traffic increases) | medium (PRs stall, easy AR-touch fix once noticed) | Fix workflow `name:` to drop `py` prefix, OR AR-touch protection. |

**Overall Forever-Pending Risk Score: MEDIUM**

Rationale:
- wakir-runtime currently coherent (no orphaned required names).
- wakir-verify + wakir-protocol carry a latent bug that has not
  yet surfaced due to low PR volume.
- The bigger structural risk is the **opposite** direction: too
  FEW required checks, allowing red PRs to merge (PR #71 incident
  class).

---

## 6. Behebungs-Plan

### 6.1 In this PR (Tomás-Hand, Tag-35)

- **No workflow `name:` edits** in this PR. Rationale: a wider
  Tag-36 audit may consolidate the aggregator approach; touching
  workflow names now without that consolidation risks immediate
  protection-drift on the next AR-touch.
- **Audit report only**, with explicit recommendations for AR-touch
  follow-ups and a forward-looking aggregator-pattern note.

### 6.2 AR-touch follow-ups (GitHub-Web-UI, Admin-Settings)

**Phase A — wakir-runtime expand Required-Status-Checks set**

Add the following 4 names to
`wakir-labs/wakir-runtime → Settings → Branches → main → Required
status checks`:

1. `wirelang suite without rfc8785 / jsonschema (shadow)`
2. `production-vs-sandbox drift envelope`
3. `Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)`
4. (optional, hygiene) `wirelang suite without rfc8785 / jsonschema`
   from `sandbox-ci.yml` — verify display-name uniqueness with the
   shadow-suite job before adding.

Effect: closes Class-A gap. Does NOT touch paths-filtered
workflows.

**Phase B — wakir-verify + wakir-protocol drift fix**

Two equivalent options, AR's choice:
- **Option 1 (AR-touch only):** Update required-check name from
  `pytest (3.13)` to `pytest (py3.13)` in both repos' branch
  protection.
- **Option 2 (workflow PR):** Rename ci.yml matrix display from
  `pytest (py${{ matrix.python-version }})` to
  `pytest (${{ matrix.python-version }})` in both repos. Requires
  one PR per repo.

Recommendation: **Option 1** (faster, no PR-merge dependency).

**Phase C — Status-aggregator pattern (Tag-36 spawn or design ADR)**

Out of scope for this PR. Recommendation as memo:
- Introduce `required-aggregator.yml` workflow in wakir-runtime.
- Fires on every PR (no paths filter).
- Calls every paths-filtered workflow via `workflow_call` or
  inspects check-run status via API.
- Single display-name (e.g. `required-aggregator`) added to
  Required-Status-Checks. This name covers all 11 currently
  paths-filtered jobs without forever-pend risk.

This is the GitHub-Actions canonical pattern for conditional
required checks. Worth a separate small ADR.

### 6.3 Permanent rule (introduced by this audit)

**Before any branch-protection edit:**
```
gh api repos/wakir-labs/<repo>/commits/main/check-runs \
  --jq '.check_runs[].name' | sort -u
```
must produce a name that EXACTLY matches the intended required-name.
String drift must be reconciled in workflow `name:` field first.

This rule should be referenced from `feedback_branch_protection_check_names.md`
on the next memory update.

---

## 7. Anhang — Raw artifacts

### 7.1 wakir-runtime branch protection JSON (excerpt)

```json
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "License-Hygiene Gate (ADR-0061)",
      "wirelang suite with rfc8785 + jsonschema",
      "cross-repo drift (wakir-runtime ↔ wakir-protocol)"
    ]
  },
  "enforce_admins": {"enabled": false},
  "allow_force_pushes": {"enabled": false}
}
```

### 7.2 wakir-verify + wakir-protocol branch protection JSON (excerpt; identical)

```json
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "pytest (3.13)",
      "REUSE lint",
      "Analyze (python)"
    ]
  }
}
```

### 7.3 Verified check-runs (wakir-runtime, recent PR #229)

PR-trigger fires 11 check-runs in 5 workflows: `tests` (3),
`sandbox-ci` (1), `cross-repo-drift-audit` (1), `license-gate` (1),
`phase-2-validation-gate` (6).

Paths-filtered workflows did NOT fire on PR #229 because the PR
touched only Python persona-engine code; that is correct behavior.

— Tomás
