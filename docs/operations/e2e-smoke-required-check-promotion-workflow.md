<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->
---
title: "E2E-Smoke Required-Status-Check Promotion Workflow (Tag-69)"
status: "active"
owner: "amara"
audience: "operator,ar"
created: "2026-05-19"
tag: "tag-69"
predecessor: "docs/operations/branch-protection-required-checks-tag64-companion.md"
related_adrs:
  - "ADR-0020"
  - "ADR-0036"
  - "ADR-0044"
  - "ADR-0066"
related_docs:
  - "docs/operations/branch-protection-required-checks-tag59.md"
  - "docs/operations/branch-protection-required-checks-tag61-addendum.md"
  - "docs/operations/branch-protection-required-checks-tag64-companion.md"
  - "docs/operations/branch-protection-required-status-checks.md"
  - "docs/operations/bulk-activation-pre-walk-recipe.md"
related_prs:
  - "#389"
  - "#396"
  - "#400"
  - "#404"
  - "#411"
  - "#416"
  - "#434"
related_memory:
  - "feedback_branch_protection_check_names.md"
  - "feedback_sandbox_host_trennung.md"
  - "feedback_live_bringup_sandbox_gap.md"
  - "feedback_anti_eskalations_drift.md"
  - "feedback_high_tempo_spawn_collision.md"
cross_review_markers:
  - "Zone-M: QA × Tomas (E2E-Smoke verdict-shape lineage, REUSE-Wrap Stability-Window-Anchor)"
  - "Zone-M: QA × Kai (Bulk-Activation-Helper, branch-protection PUT-Recipe lineage)"
  - "Zone-N: QA × Henrik (Audit-evidence-input for Required-Check-Promotion-Claim)"
---

# E2E-Smoke Required-Status-Check Promotion Workflow (Tag-69)

Operator-Hand-Promotion-Workflow-Doc that bundles the concrete
sequence of actions for promoting the Tag-63 E2E-Smoke
(`E2E verdict (READY / DRIFT / DEFECT)`) from `audit-only` to
`enforced-Required-Status-Check` in the 8-Pool branch-protection-
activation lifecycle. This document is the **single bundle** that
the Operator follows once the Tag-65 E2E-Stability-Window-Probe
(PR #416) has emitted `STABILITY-WINDOW-CONFIRMED` on the current
`main`-tip.

It is the QA-side counterpart to Kai's bulk-activation-pre-walk-
recipe (PR #396) and the Tag-64-Companion-Doc (PR #411). It does
not duplicate them; it composes them into a promotion-procedure
that the Operator can execute end-to-end in one sitting without
re-deriving prerequisites.

## §1 — Scope

This doc defines the **promotion-only** sub-workflow for the
8th Required-Status-Check-Pool-Slot (`E2E verdict (READY /
DRIFT / DEFECT)`, Tag-63 PR #400, Tag-64-Pool-Position #8). It
explicitly excludes:

- The seven other Required-Check-Pool-Slots (Tag-59 1..5,
  Tag-61 6..7). Those follow `docs/operations/
  branch-protection-required-checks-tag61-addendum.md` and the
  Kai-Tag-62 bulk-activation-pre-walk-recipe.
- The initial workflow-dispatch-run that creates the
  `check-runs[*].name` eligibility-surface on `main`. That step
  is described in Tag-64-Companion §3.1 and is a **prerequisite**
  of this doc, not a step of this doc.
- The wakir-protocol mirror of the same check-name. Cross-repo
  promotion-coordination is Noa-Domaene (Zone-M with Amara) and
  is described in `docs/operations/cross-repo-drift-runbook.md`.
- Wirelang-spec-v0.4.4 promotion-sequencing (Reza-Domaene).

The scope-boundary is deliberately narrow: **one check, one
direction (audit-only -> enforced), one PUT, one verification
loop, one rollback-path**. Bundling more would create the same
"omnibus-recipe" anti-pattern that ADR-0066 names in §3 (the
Pre-Cutover-Final-Acceptance lessons learned).

### §1.1 — Operator-Hand-Authority-Boundary

The PUT call against `repos/wakir-labs/wakir-runtime/branches/
main/protection` is irreversible-by-default for the duration of
the PUT-window. It is **strictly Operator-Hand** per ADR-0020
§10 ("Kein Push auf Remote-Repos ohne explizite CEO-Freigabe pro
Push"). The Mira-Sandbox / Amara-Spawn produces this doc, the
helper, and the tests — but **never** executes the PUT. Memory-
cross-ref: `feedback_sandbox_host_trennung`.

### §1.2 — Not a Substitute for Cross-Review

This doc does not bypass Cross-Review (Zone-M / Zone-N). The
Operator confirms (or the AR confirms on Operator's behalf) that
the Tag-65 Stability-Window-Probe verdict has been reviewed by
Henrik (Internal Audit, Zone-N) at least once before the first
promotion. Subsequent re-promotions (after Rollback per §5) use
the same Cross-Review gate.

## §2 — Stability-Window-Confirmed Prerequisite (Tag-65 Pattern)

The promotion **must not** proceed unless the Tag-65 E2E-
Stability-Window-Probe (`tooling/ci/aggregate_e2e_stability_
window.py`, PR #416) has emitted `STABILITY-WINDOW-CONFIRMED` on
the current `main`-tip with all three back-to-back runs returning
`E2E-READY`.

### §2.1 — Confirmation-Capture Recipe

```bash
# Snapshot the current main-tip SHA at the moment of confirmation.
MAIN_TIP=$(gh api repos/wakir-labs/wakir-runtime/git/ref/heads/main \
  --jq '.object.sha')

# Trigger three back-to-back workflow_dispatch runs of the Tag-63
# E2E-Smoke against main and feed their verdicts into the Tag-65
# aggregator. (Operator-Hand-only: workflow_dispatch is push-like.)
for i in 1 2 3; do
  gh workflow run pre-cutover-final-acceptance-e2e-smoke.yml \
    --ref main \
    -f enforce=true
done

# Wait for all three runs to reach a terminal state.
gh run list --workflow=pre-cutover-final-acceptance-e2e-smoke.yml \
  --branch=main --limit=3 \
  --json databaseId,status,conclusion,headSha \
  > /tmp/tag69-promotion-runs.json

# Verify all three completed on the same main-tip SHA.
jq -e --arg sha "$MAIN_TIP" \
  'all(.[]; .headSha == $sha and .conclusion == "success")' \
  /tmp/tag69-promotion-runs.json

# Capture the three per-run verdict-envelopes and run the Tag-65
# aggregator locally to emit the STABILITY-WINDOW verdict-envelope.
# (Per-run envelopes are uploaded as artifacts by the E2E-Smoke
# workflow; download them via `gh run download`.)
python3 tooling/ci/aggregate_e2e_stability_window.py \
  --output /tmp/tag69-stability-window.json
```

The promotion is **eligible** if and only if `/tmp/tag69-
stability-window.json` contains
`"verdict": "STABILITY-WINDOW-CONFIRMED"` and `"main_tip_sha"`
matches `$MAIN_TIP`. Both fields must be present; absence is a
defect, not a not-yet.

### §2.2 — Confirmation-Window Freshness

The confirmation has a **24h freshness window** measured from
the `built_at_utc` timestamp on the verdict-envelope. After 24h
the Operator re-runs §2.1. Rationale: `main` advances continuously
during Phase-3c; a 24h-old confirmation could be against a now-
superseded SHA. Memory-cross-ref: `feedback_high_tempo_spawn_
collision`.

### §2.3 — Multi-Run-Same-SHA Discipline

All three runs must complete against the **same** `main`-tip
SHA. If `main` advances mid-window (e.g. via an emergency
hotfix-merge), the window resets. The Tag-65 aggregator records
the per-run `head_sha` on each per-run envelope; the Promotion-
Workflow-Doc-Helper (§3.2 below) verifies SHA-equivalence
across all three.

## §3 — PUT branch-protection Recipe (Operator-Hand)

Once §2 is satisfied, the Operator executes the PUT-Recipe.

### §3.1 — Pre-PUT Snapshot

```bash
# Snapshot the current required_status_checks.contexts (the 7-pool
# baseline, assumed already-active per Tag-61-Addendum + Tag-64-
# Companion bulk-activation completion). If only some of the 7
# are active, the Operator does NOT proceed with §3.2 — instead
# the Operator first completes the 7-pool activation per
# docs/operations/bulk-activation-pre-walk-recipe.md.
gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
  --jq '.required_status_checks.contexts' \
  > /tmp/tag69-pre-put-contexts.json

# Sanity-check: the 7-pool baseline should already include
# the seven Tag-59 + Tag-61 display-names verbatim.
jq -r '.[]' /tmp/tag69-pre-put-contexts.json | sort \
  > /tmp/tag69-pre-put-contexts-sorted.txt
```

### §3.2 — The 8-Pool PUT

```bash
# The PUT is a complete replacement. The Operator MUST include all
# previously-active checks in the contexts array, then append #8.
# Display-names are verbatim (Tag-59 §3.2, Tag-64-Companion §3.2,
# memory feedback_branch_protection_check_names).
gh api -X PUT repos/wakir-labs/wakir-runtime/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)",
      "pyramide layer-dependency DAG verify (6 layers, 16 edges)",
      "verify-containerfile-base-image-digest-pins",
      "wirelang spec v0.4.3 freeze-seal probe",
      "alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)",
      "pyramide cross-run stability pin (5 fixtures, 3 runs each)",
      "g1-g2 operator-recipe smoke-validation",
      "E2E verdict (READY / DRIFT / DEFECT)"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON
```

The PUT-call carries `enforce_admins: true`. This is intentional:
the 8-Pool is mandatory for **every** merge, including admin-
merges. ADR-0066 §4 names admin-merge-bypass as the failure-mode
that allowed Tag-67 Helper-Surface-Drift to land on `main` with
incomplete CI — and that failure-mode is now closed by `enforce_
admins: true`.

### §3.3 — Idempotency Guard

The PUT is **idempotent** if the `contexts` array already
contains all 8 display-names verbatim. The Operator can re-run
the PUT without side-effect, **provided** the array is byte-
exact. Any drift (lower-case, whitespace, character substitution
in the parenthesised verdict-tokens) creates a "ninth" check
that GitHub treats as pending-forever. Memory-cross-ref:
`feedback_branch_protection_check_names`.

## §4 — Verification-Steps

Immediately after the PUT, the Operator runs the four-step
verification loop. **Each step must pass before the next.**

### §4.1 — Post-PUT Snapshot

```bash
gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
  --jq '.required_status_checks.contexts' \
  > /tmp/tag69-post-put-contexts.json

# Verify the post-PUT array has exactly 8 entries.
test "$(jq -r 'length' /tmp/tag69-post-put-contexts.json)" = "8"

# Verify the 8th entry is verbatim the E2E-verdict display-name.
jq -e 'index("E2E verdict (READY / DRIFT / DEFECT)") == 7' \
  /tmp/tag69-post-put-contexts.json

# Verify the pre/post diff is exactly one added line.
diff /tmp/tag69-pre-put-contexts-sorted.txt \
     <(jq -r '.[]' /tmp/tag69-post-put-contexts.json | sort) \
  | grep -c '^>'
# Expected: 1 (exactly one added line: the E2E-verdict check).
```

### §4.2 — Test-PR-Smoke

Create a one-line Test-PR that touches `tooling/ci/aggregate_
pre_cutover_e2e_smoke_verdict.py` (or any path covered by the
E2E-Smoke workflow's path-filter) and verify the new Required-
Check appears on the PR's check-run-surface.

```bash
git checkout -b operator/tag-69-e2e-required-smoke-test
echo "# tag-69 smoke-test no-op $(date -Iseconds)" \
  >> tooling/ci/aggregate_pre_cutover_e2e_smoke_verdict.py
git commit -am "test(ci): Tag-69 E2E-Required smoke-test no-op"
git push -u origin operator/tag-69-e2e-required-smoke-test
gh pr create --title "test: Tag-69 E2E-Required smoke" \
  --body "Smoke-test for Tag-69 promotion verification. Not for merge."

# Verify the new Required-Check appears.
gh pr checks --watch
```

The PR is **closed-without-merge** after verification. It must
not be merged to `main`. Memory-cross-ref: `feedback_anti_
eskalations_drift` — this is operative-Hygiene, not AR-Sichtung.

### §4.3 — Green-Run Verification

The smoke-test PR's `E2E verdict (READY / DRIFT / DEFECT)`
check-run must reach `conclusion: success` within the workflow's
normal SLA (~25 minutes per the Tag-63 PR #400 Workflow-File). If
it reaches `failure` or `skipped`, the Operator inspects per
§5.1 Diagnostic-Tree and decides Rollback per §5.2.

### §4.4 — AR-Sichtung-Optional

The verification-output bundle (`/tmp/tag69-pre-put-contexts.
json`, `/tmp/tag69-post-put-contexts.json`, the smoke-test PR
URL, the verdict-envelope from §2.1) is forwarded to the AR via
the standard Mira-Inbox-Channel as an Audit-Evidence-Input for
Henrik (Zone-N). The AR may request additional verification
runs at their discretion; this is non-blocking for the Operator
unless the AR explicitly directs a rollback.

## §5 — Rollback bei Post-Promotion-Defect

If a Post-Promotion-Defect is detected (a legitimate PR is
indefinitely-blocked, or `main` itself shows a `failure` on the
new Required-Check), the Operator executes the Rollback. The
Rollback is **a return to the 7-Pool state**, not a deletion of
all branch-protection.

### §5.1 — Diagnostic-Tree (Decision)

Before Rollback, the Operator distinguishes three failure-modes:

| # | Symptom | Likely Cause | Recommended Action |
|---|---------|--------------|--------------------|
| A | New Required-Check is `pending` indefinitely on every PR | Check-name-drift between PUT-payload and workflow-job-display-name | §5.2 Rollback to 7-Pool, then re-verify Tag-64-Companion §3.2 |
| B | New Required-Check fails on PR but passes on workflow_dispatch | Path-filter or trigger-mismatch (PR-trigger missing) | §5.2 Rollback to 7-Pool, then file workflow-substrate-fix |
| C | New Required-Check fails on both PR and dispatch | E2E-Smoke substrate-drift (the real-thing case) | §5.2 Rollback to 7-Pool, then debug as Tag-68-pattern-equivalent |

Symptom A is the most common false-promotion-mode. Memory-cross-
ref: `feedback_branch_protection_check_names`.

### §5.2 — Rollback PUT (Return to 7-Pool)

```bash
# Rollback PUT: identical structure to §3.2 but WITHOUT the 8th
# display-name. Operator-Hand only.
gh api -X PUT repos/wakir-labs/wakir-runtime/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)",
      "pyramide layer-dependency DAG verify (6 layers, 16 edges)",
      "verify-containerfile-base-image-digest-pins",
      "wirelang spec v0.4.3 freeze-seal probe",
      "alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)",
      "pyramide cross-run stability pin (5 fixtures, 3 runs each)",
      "g1-g2 operator-recipe smoke-validation"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON

# Post-rollback verification.
gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
  --jq '.required_status_checks.contexts | length'
# Expected: 7
```

### §5.3 — Re-Promotion Discipline

After Rollback, **a fresh Tag-65 Stability-Window-Confirmation
is required** before the next promotion attempt. The previous
confirmation is invalidated by the Rollback (regardless of
freshness-window). Re-promotion follows §2 -> §3 -> §4 from
scratch. Memory-cross-ref: `feedback_anti_eskalations_drift` —
the Re-Promotion is not "another try at the same gate"; it is
a new attempt under the same gate-discipline.

### §5.4 — Forensic-Capture (Audit-Evidence-Input)

Independent of the Diagnostic-Tree decision in §5.1, the
Operator captures the failed check-run-payload (`gh api
repos/wakir-labs/wakir-runtime/commits/<sha>/check-runs`) into
the AR-Inbox as Audit-Evidence-Input for Henrik (Zone-N). The
forensic-capture is non-blocking for the Rollback itself — the
Rollback proceeds even before the capture is filed, because
unblocking legitimate-PR-flow takes precedence over
forensic-completeness.

## §6 — Cross-Anchor zu Kai-#389 + Kai-#396 + Tomás-#404

This Promotion-Workflow-Doc is the **Tag-69 composition** of
three predecessor anchors. Each anchor contributes a distinct
substrate that this doc reuses (not copies):

### §6.1 — Kai PR #389 (Tag-61 Addendum)

Kai PR #389 introduced the §4 Activation-Order Risk-Map pattern
(seven-pool ordering by `low -> medium -> high` coupling-grade).
This Tag-69 doc inherits the same ordering principle: position
#8 (the E2E-verdict-check) is **last** in the activation-order
because it has the **highest** coupling-grade (Vier-Stage-Fan-
In). Tag-69 §3.2's PUT-payload follows the Tag-64-Companion §4
ordering verbatim.

Anchor: `docs/operations/branch-protection-required-checks-
tag61-addendum.md` §4.

### §6.2 — Kai PR #396 (Tag-62 Bulk-Activation-Pre-Walk-Recipe)

Kai PR #396 introduced the Bulk-Activation-Helper (`tooling/ops/
_bulk_activate_required_checks.py`) and the
Pre-Walk-Recipe-Pattern (`docs/operations/bulk-activation-pre-
walk-recipe.md`). This Tag-69 doc **does not duplicate** that
helper; instead it calls the helper's `--put-payload` mode as
the single source of the §3.2 PUT-payload assembly. The Tag-69
helper (`tooling/ci/verify_e2e_promotion_workflow_doc.py`)
verifies that the §3.2 PUT-payload-array matches what the
Bulk-Activation-Helper would emit for the 8-pool.

Anchor: `docs/operations/bulk-activation-pre-walk-recipe.md`,
Tag-64-Companion §2.2.

### §6.3 — Tomas PR #404 (Tag-63 REUSE-Wrap Stability-Window)

Tomas PR #404 introduced the Stability-Window-Probe-Pattern
(three back-to-back runs with the trinary CONFIRMED / NOT-YET /
DEFECT verdict-shape). This Tag-69 doc adopts the **identical
verdict-shape** via the Tag-65 E2E-Smoke-Stability-Window-Probe
aggregator (`tooling/ci/aggregate_e2e_stability_window.py`,
PR #416). The promotion-eligibility gate in §2 is the
`STABILITY-WINDOW-CONFIRMED` verdict from that aggregator.

Anchor: `.github/workflows/reuse-wrap-enforce-flip-stability-
window-probe.yml`, Tag-65 aggregator-helper.

## §7 — Sandbox-Boundary

The Tag-69 Promotion-Workflow-Doc is itself Mira-Sandbox-output
(Amara-Spawn produces this doc, the verifier-helper, and the
test-suite). Execution of the workflow (the actual PUT-calls,
the workflow-dispatch-runs, the smoke-test-PR creation) is
Operator-Hand only. The boundary follows the Tag-64-Companion
§6 axis verbatim.

| Phase | Mira-Sandbox | Operator-Hand |
|---|---|---|
| Doc-Erstellung (this doc, Tag-69) | **JA** (Mira-Sandbox, Amara-Spawn) | nein |
| Verifier-Helper-Erstellung (`tooling/ci/verify_e2e_promotion_workflow_doc.py`) | **JA** (Mira-Sandbox, Amara-Spawn) | nein |
| Test-Suite (`tests/ci/test_e2e_promotion_workflow_doc_tag69.py`) | **JA** (Mira-Sandbox, Amara-Spawn) | nein |
| Tag-65 Stability-Window-Confirmation-Capture (§2.1) | nein | **JA** (Operator-Workstation, ADR-0020 §10) |
| 8-Pool PUT (§3.2) | nein | **JA** (Operator-Workstation, ADR-0020 §10) |
| Post-PUT Snapshot Verification (§4.1) | **JA** (read-only `gh api`) | optional |
| Smoke-Test-PR creation (§4.2) | **JA** (kann via Amara-Spawn) | optional |
| Rollback PUT (§5.2) | nein | **JA** (Operator-Workstation, ADR-0020 §10) |
| Forensic-Capture (§5.4) | **JA** (read-only `gh api`) | optional |

Memory-cross-refs: `feedback_sandbox_host_trennung` —
claude-dev/Amara-Spawn MUST NOT have Host-Operator-Token-access.
`feedback_live_bringup_sandbox_gap` — Live-substrate-mutation
(PUT-calls) is Operator-Hand only. ADR-0020 §10 — branch-
protection-PUT is inherently Operator-Hand.

### §7.1 — Cross-Review-Markers (Zone-M + Zone-N)

- **Zone-M (QA × Tomas)**: This doc reuses the Tomas-PR-#404
  Stability-Window-Probe-Pattern as the promotion-eligibility
  gate. Drift in the trinary-verdict-shape between the REUSE-
  Wrap-anchor and the E2E-Smoke-anchor is a Zone-M signal.
- **Zone-M (QA × Kai)**: This doc reuses the Kai-Tag-62-Bulk-
  Activation-Helper as the §3.2 PUT-payload assembly source.
  Drift between the helper's emitted payload and the §3.2
  inline-payload is a Zone-M signal.
- **Zone-N (QA × Henrik)**: The §2.1 Stability-Window-verdict-
  envelope, the §4.1 pre/post-PUT snapshots, the §4.2 smoke-
  test-PR URL, and the §5.4 forensic-capture (if any) are
  **Audit-Evidence-Inputs**. Henrik consumes them in the
  Internal-Audit-Sample. Drift in their structure or
  completeness is a Zone-N signal. Memory-cross-ref:
  `feedback_anti_eskalations_drift` — Audit-Evidence-Input
  flows through Mira-Inbox, not via AR-direct-channel.

— Amara (Tag-69, 2026-05-19)
