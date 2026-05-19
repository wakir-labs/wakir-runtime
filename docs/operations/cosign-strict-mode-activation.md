<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Cosign — Strict-Mode Activation Readiness

**Status:** Living operations document (read by humans + parsed by tests).
**Scope:** `wakir-labs/wakir-runtime` cosign substrate — the 15-binary
Phase-3b carrier-image inventory pinned in
`policies/cosign-policy-phase-3b.yaml` and verified by the workflows
`.github/workflows/cosign-verify-images.yml` (audit-only,
workflow_dispatch) and `.github/workflows/cosign-keyless-oidc-drift-probe.yml`
(daily, audit-only).
**Authored:** 2026-05-19 (Kai, Tag-54 RE-DISPATCH).
**Sibling-doc:** `docs/operations/cross-repo-drift-enforce-flip-readiness.md`
(Cross-Repo-Drift `ENFORCE=true` readiness — same shape).

---

## 1. Why this document exists

Today the cosign substrate runs in **audit-only** posture:

* `cosign-verify-images.yml` is `workflow_dispatch` only — Operator-Hand
  recipe per pin refresh; never gates a PR.
* `cosign-keyless-oidc-drift-probe.yml` is scheduled daily but is NOT
  a required-status-check — verdict surfaces via Job-Summary +
  artefact + notify-event on non-GREEN.
* The 15-binary inventory still carries the
  `DIGEST_PENDING_KAI_CROSS_REVIEW` placeholder in
  `carrier_image.expected_image_digest` for entries pending
  Operator-Hand resolution.
* The pinned-trust-root JSON still carries
  `PENDING_OPERATOR_HAND_REFRESH` for `fulcio_root_ca_sha256` and
  `rekor_log_shard_id`.

Flipping cosign into **strict mode** today would either red the
runtime `main` on every PR (carrier digest placeholder) or pass
trivially (trust-root values never compared because the snapshot
falls back to baseline). Neither outcome is the strict-mode
substrate we want.

The Strict-Flip is therefore gated on a controlled substrate-cleanup
sequence. This document is the operator's checklist for that sequence
and the single source of truth for *which* substrate-side artefact
still needs which resolution, *how* the readiness-check evaluates it,
and *what* gate-thresholds the inventory must cross before the flip
is safe.

The companion hermetic test
`tests/observability/test_cosign_strict_mode_readiness_check.py` pins
the six-gate evaluation logic, the canonical 15-binary inventory, and
the required-status-check display names into CI so a future drift in
*this* document is also caught by the tripwire it describes.

---

## 2. Substrate inventory — readiness status (2026-05-19)

The cosign substrate consists of four files the readiness-check reads
from disk:

| # | Path | Purpose | Today's status |
|---|---|---|---|
| 1 | `policies/cosign-policy-phase-3b.yaml` | 15-binary inventory + carrier-image pin | Inventory complete (15/15); carrier digest = placeholder pending Operator-Hand |
| 2 | `state/cosign-drift/pinned-trust-root.json` | Fulcio CA SHA + Rekor shard ID pin | Both fields = `PENDING_OPERATOR_HAND_REFRESH` |
| 3 | `state/cosign-drift/last-probe-envelope.json` | Most-recent drift-probe verdict | File absent; operator must run probe + capture |
| 4 | `quadlet/wakir-rust-cli.container` | Carrier-image-install path inventory | 15-binary parity with policy (per Tag-45 PR #294) |

### 2.1 Readiness verdict legend

| Verdict | Meaning |
|---|---|
| `GREEN` | All six gates pass. Strict-flip-ready. |
| `BLOCKED` | One or more gates failed. Operator must resolve before flip. |
| `NOT-CHECKED` | One or more gates returned NOT-CHECKED. Operator must capture the missing data. Treated as blocking. |

---

## 3. Strict-Flip — what changes when activated

The flip applies three substrate changes in lock-step. None of them
land before the readiness-check reports GREEN.

### S1. `cosign-verify-images.yml` — promote to PR-gate

* Add `pull_request:` and `push: branches: [main]` triggers with a
  path filter on:
  * `policies/cosign-policy-phase-3b.yaml`
  * `infra/persona-engine/Containerfile.real`
  * `quadlet/wakir-rust-cli.container`
  * `infra/spire/federation/compose/spire-federation.yaml`
  * `infra/spire/agent/compose/spire-agent-federation.yaml`
  * `infra/spire/federation/provisioner/Containerfile`
* Keep `workflow_dispatch` as the manual fallback path.
* The three jobs (`cosign-verify-spire`, `digest-verify-python`,
  `cosign-verify-wakir-provisioner`) now run on every PR that
  touches the listed paths.

### S2. `cosign-keyless-oidc-drift-probe.yml` — strict on PR

* Promote the `pull_request:` trigger to pass the workflow input
  `exit_non_zero_on_drift=true` so any drift verdict reds the job.
* The scheduled `cron "30 6 * * *"` daily run stays as the
  calendar-window signal (still `exit_non_zero_on_drift=false` on
  schedule — daily-monitoring posture; CI-gate posture on PR only).

### S3. Branch-protection — add required-status-checks

Per `feedback_branch_protection_check_names.md` the two job
display-names must be added EXACTLY to the
`wakir-runtime` branch-protection required-status-check rule:

* `cosign verify SPIRE images` (job name in `cosign-verify-images.yml`)
* `Cosign-Keyless-OIDC-Drift-Probe (daily)` (job name in
  `cosign-keyless-oidc-drift-probe.yml`)

The readiness-check gate G6 self-verifies that this script holds
these two names byte-for-byte; if upstream renames a job, the test
TV-SM-16 catches it before the flip.

---

## 4. Acceptance gates G1..G6

The readiness-check evaluates six gates. All six must report GREEN
for the run to be strict-flip-ready.

| Gate | Threshold | Rationale |
|---|---|---|
| **G1** `placeholder_digest_count == 0` | All 15 binaries carry a real `sha256:[hex64]` digest | Strict-mode would red every PR otherwise — the placeholder is what audit-only tolerates. |
| **G2** `pinned_trust_root_completeness` | Both `fulcio_root_ca_sha256` and `rekor_log_shard_id` are real (not `PENDING_OPERATOR_HAND_REFRESH`) | Drift-detection has no anchor without the real values; strict-mode passes trivially. |
| **G3** `last_drift_probe_verdict == GREEN` | The most recent `state/cosign-drift/last-probe-envelope.json` carries `aggregate_verdict: GREEN` | Strict-flip on top of a drifted substrate red-flips immediately. |
| **G4** `policy_inventory_size == 15` | The policy carries the Tag-45 canonical 15 binaries in canonical order | Drift here means PRs against a wrong inventory size red. |
| **G5** `cross_substrate_parity == 0` | Quadlet installer and policy iterate the same 15 binaries | Strict-flip on a split substrate reds PRs that legitimately update one side first. |
| **G6** `required_status_check_displaynames_known` | The two required-status-check display names are non-empty and exactly as listed in §3 | Per `feedback_branch_protection_check_names.md` — the strict-flip PR must use the exact names. |

A run that meets all six gates is **flip-ready**. A run that misses
any of them blocks the flip and the operator returns to §5 at the
failing gate.

---

## 5. Operator substrate-cleanup sequence

The cleanup sequence is **strict-order**: each step depends on the
prior one having merged into `main` and the readiness-check having
re-confirmed the expected gate flip. Skipping ahead risks a
strict-flip on top of a stale baseline.

### Step 1 — Snapshot baseline

Run the readiness-check workflow on the current `main`:

```bash
gh workflow run cosign-strict-mode-readiness-check -R wakir-labs/wakir-runtime
```

Confirm the run completes and produces an envelope artefact. Save
the workflow run-id as the *baseline run* for the rollback story.
Expected initial state: G1 BLOCKED (placeholder digest),
G2 BLOCKED (PENDING trust-root), G3 NOT-CHECKED (no envelope), G4
GREEN (Tag-45 lock-step), G5 GREEN (quadlet parity), G6 GREEN
(names known).

### Step 2a — Resolve G5 cross-substrate parity drift

The Tag-54 baseline run reports G5 BLOCKED with the four Welle-4..7
binaries (`state-backing-welle4`, `fsm-welle5`, `subscribe-loop-welle6`,
`recovery-welle7`) present in the policy but absent from
`quadlet/wakir-rust-cli.container`. The Tag-33 Mini-Welle landed the
four entries in the policy as *first-class single-binary-image* slots;
the Quadlet installer was not yet extended in the same wave.

Two valid resolution paths:

* **Resolution-A (extend Quadlet):** PR #N0a adds the four binaries
  to `quadlet/wakir-rust-cli.container` mirroring the per-binary path
  convention. After merge, G5 flips to GREEN.
* **Resolution-B (separate per-Welle Quadlet substrate):** the four
  Welle-binaries are intentionally hosted in dedicated per-Welle
  Quadlet files (not yet authored). PR #N0b adds the
  `--quadlet-installer` option to accept a glob over multiple Quadlet
  files; the readiness-check then iterates ALL of them and unions the
  binary-name set.

Resolution-A is the recommended path (smaller substrate footprint,
single installer file matching the single carrier image). Resolution-B
is the future-proof path if the per-Welle deployment model later
demands dedicated install paths.

Cross-Review-Zone-C: Tomás chooses the path before this step lands.

### Step 2 — Operator-Hand carrier-image digest resolution

This is the same resolution path the `cosign-verify-images.yml`
workflow already documents:

1. Operator-Hand on a host with GHCR-network egress runs
   `infra/persona-engine/scripts/resolve-image-pins-ci.sh` (or the
   Tag-20 equivalent recipe), producing the byte-for-byte real
   sha256 digest for `ghcr.io/wakir-labs/wakir-persona-engine:0.5.0-pilot`.
2. PR #N1 against `wakir-runtime` replaces the
   `DIGEST_PENDING_KAI_CROSS_REVIEW` placeholder in
   `policies/cosign-policy-phase-3b.yaml` with the real digest.
3. Re-run the readiness check; G1 flips from BLOCKED to GREEN.

### Step 3 — Operator-Hand pinned-trust-root refresh

1. Operator-Hand on a host with Sigstore-network egress reads the
   current Fulcio root CA cert via
   `cosign verify-blob --certificate-chain ...` (recipe in
   `docs/operations/cosign-keyless-oidc-drift-probe.md`) and
   computes the SHA-256 of the root CA cert.
2. Same operator-host reads the current Rekor transparency-log
   shard ID via the Rekor public API.
3. PR #N2 against `wakir-runtime` replaces the two
   `PENDING_OPERATOR_HAND_REFRESH` values in
   `state/cosign-drift/pinned-trust-root.json` with the real values.
4. Re-run the readiness check; G2 flips from BLOCKED to GREEN.

### Step 4 — Capture the last-probe envelope

1. Run the cosign-keyless-OIDC-drift-probe workflow:
   ```bash
   gh workflow run cosign-keyless-oidc-drift-probe -R wakir-labs/wakir-runtime
   ```
2. Wait for the run to complete. Confirm the aggregate verdict is
   GREEN (if not, the operator returns to §3 of the
   cosign-keyless-OIDC-drift-probe runbook).
3. Operator-Hand downloads the envelope artefact and commits it as
   `state/cosign-drift/last-probe-envelope.json` via PR #N3. The
   file is the byte-for-byte content of `envelope.json` from the
   workflow artefact.
4. Re-run the readiness check; G3 flips from NOT-CHECKED to GREEN.

### Step 5 — Cross-Review-Zone-C sign-off

Per the Container-Image-Pipeline × OTS-Anchoring cross-review zone
(ADR-0020 Zone C, Tomás moderator): Tomás reviews the post-Step-4
readiness-check run and leaves a sign-off comment referencing this
document. The sign-off comment is the audit-trail entry; no
separate ADR.

### Step 6 — Strict-Flip workflow + branch-protection PR

PR #N4 against `wakir-runtime` lands all three substrate changes
in a single atomic PR:

* S1 — `.github/workflows/cosign-verify-images.yml` adds the
  `pull_request:` / `push:` triggers with the path filter from §3.
* S2 — `.github/workflows/cosign-keyless-oidc-drift-probe.yml`
  workflow input `exit_non_zero_on_drift` defaults to `'true'` on
  `pull_request:` (the schedule keeps `'false'`).
* S3 — branch-protection update applied via
  `gh api repos/wakir-labs/wakir-runtime/branches/main/protection`
  (Operator-Hand, post-merge — the GitHub-API call cannot be in
  the workflow file itself).

The PR description references this document by heading anchor.

### Step 7 — Rollback path

If a post-flip PR is unjustly red'd by a drift the cleanup missed,
Mira-Hand may temporarily revert S2's `pull_request:`
`exit_non_zero_on_drift` default to `'false'` for that one PR's
required re-run, while the new substrate drift is resolved per the
appropriate runbook. Reverting S3 (the branch-protection rule)
requires a separate Operator-Hand GitHub-API call; the env-default
revert alone does NOT remove the required-status-check.

A full Strict-Mode rollback (return to audit-only) requires reverting
all three S1+S2+S3 substrate changes; the strict-flip-flag is the
combined state of all three, not a single switch.

---

## 6. Acceptance-gate thresholds for the Strict-Flip

The thresholds below are the *normative* contract for "ready to
flip strict". The hermetic test
`test_tv_sm_16_g6_green_on_known_required_check_names`
(combined with TV-SM-08..TV-SM-15) pins them into CI.

| Metric | Threshold | Rationale |
|---|---|---|
| `placeholder_digest_count` | `== 0` | Zero placeholders. Strict-mode would red every PR otherwise. |
| `pending_trust_root_field_count` | `== 0` | Zero `PENDING_OPERATOR_HAND_REFRESH`. Drift-detection needs anchors. |
| `last_probe_aggregate_verdict` | `== "GREEN"` | No pre-existing drift carrying into the flip. |
| `policy_inventory_size` | `== 15` | Tag-45 canonical inventory lock-step. |
| `cross_substrate_parity_diff_count` | `== 0` | Quadlet ↔ policy parity. |
| Cross-Review-Zone-C sign-off | Tomás | Procedural gate (Container-Image-Pipeline × OTS-Anchoring zone). |
| Baseline run ID recorded | non-empty | For rollback per Step 7. |

A run that meets all seven thresholds is **flip-ready**. A run that
misses any of them blocks the flip and the operator returns to §5
at the failing step.

---

## 7. Audit-trail and traceability

The audit-trail for the Strict-Flip consists of:

* The baseline run-id (Step 1) and its `head_sha` for `main`.
* The PR numbers from Steps 2 / 3 / 4 / 6.
* Tomás's Cross-Review-Zone-C sign-off comment from Step 5.
* The post-flip readiness-check run from Step 6 (must be GREEN).
* The branch-protection change record from Step 6
  (via `gh api repos/wakir-labs/wakir-runtime/branches/main/protection`
  snapshot pre + post).

All five items are captured in the operator's task-archive entry
under the heading "Cosign-Strict-Mode Activation — completion log".

---

— Kai
