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
**Authored:** 2026-05-19 (infrastructure engineering RE-DISPATCH).
**Sibling-doc:** `docs/operations/cross-repo-drift-enforce-flip-readiness.md`
(Cross-Repo-Drift `ENFORCE=true` readiness — same shape).

---

## 1. Why this document exists

**Corrected 2026-09-21.** The three bullets that opened this section
described an audit-only posture and all three were false when
measured. They are kept below, struck through, because the pattern is
the point: this paragraph, the identical paragraph in
`scripts/observability/cosign-strict-mode-readiness-check.py`, and
§S1 further down all restated a remembered state instead of reading
the tree, and the readiness check then judged six gates from it for
124 daily runs.

Measured against `main` @ `67a62fc`, 2026-09-21 (live branch-protection
read + file read):

* ~~`cosign-verify-images.yml` is `workflow_dispatch` only~~ — false
  since PR #503. It runs on `workflow_dispatch` + `push: main` +
  `pull_request`, and since 2026-09-21 additionally on `schedule`.
* ~~`cosign-keyless-oidc-drift-probe.yml` ... is NOT a
  required-status-check~~ — false. `Cosign-Keyless-OIDC-Drift-Probe
  (daily)` is one of the 13 required contexts on `main`, it reports on
  every pull request, and on `pull_request` it passes
  `--exit-non-zero-on-drift`, i.e. it reds the PR on drift.
* ~~The 15-binary inventory still carries the
  `DIGEST_PENDING_KAI_CROSS_REVIEW` placeholder~~ — false. Gate G1
  measures zero placeholders on every run.

Gate G6 of the readiness check now measures the required-context
surface from disk instead of restating it, so this class of drift
fails a gate rather than sitting in prose.
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

## 2. Substrate inventory — readiness status (2026-05-19 closeout)

The cosign substrate consists of four file-sets the readiness-check
reads from disk:

| # | Path | Purpose | status |
|---|---|---|---|
| 1 | `policies/cosign-policy-phase-3b.yaml` | 15-binary inventory + carrier-image pin | Inventory complete (15/15); carrier digest = placeholder pending Operator-Hand (**G1 BLOCKED — operator-hand only**) |
| 2 | `tooling/baselines/cosign-drift/pinned-trust-root.json` | Fulcio CA SHA + Rekor shard ID pin | Both fields = `PENDING_OPERATOR_HAND_REFRESH` (**G2 BLOCKED — operator-hand only**) |
| 3 | `tooling/baselines/cosign-drift/last-probe-envelope.json` | Most-recent drift-probe verdict | **closeout: baseline-mode envelope committed; aggregate_verdict = GREEN (G3 GREEN)** |
| 4 | `quadlet/wakir-rust-cli*.container` GLOB | Carrier-image + wave-4..7 dedicated-image install-path inventory | **closeout: 4 wave-N Quadlets added (`-welle4..-welle7`); glob union = canonical 15/15 (G5 GREEN)** |

### 2.2 substanz-vollendung — gate verdict map

| Gate | baseline | closeout | Delta path |
|---|---|---|---|
| G1 placeholder_digest | BLOCKED (15 placeholders) | BLOCKED (15 placeholders) | Operator-Hand only — `resolve-image-pins-ci` workflow on a host with `ghcr.io` push permissions (sandbox-block per `feedback_sandbox_host_trennung.md`). |
| G2 trust_root_pin | BLOCKED (both PENDING) | BLOCKED (both PENDING) | Operator-Hand only — `pinned-trust-root.json` refresh on a host with Sigstore-network egress (recipe in `cosign-keyless-oidc-drift-probe.md` §6; engineering-hand + Zone-C dev engineering cross-review). |
| G3 last_probe_verdict | NOT-CHECKED (envelope absent) | **GREEN** (baseline-mode envelope committed) | closeout — `python3 scripts/observability/cosign-keyless-oidc-drift-probe.py --mode baseline --out-json tooling/baselines/cosign-drift/last-probe-envelope.json` (hermetic baseline-mode, no network egress). |
| G4 policy_inventory_size | GREEN | GREEN | (no change) |
| G5 cross_substrate_parity | BLOCKED (4 in policy not in quadlet) | **GREEN** (glob now unions to 15/15) | closeout — 4 wave-N Quadlets added (`quadlet/wakir-rust-cli-welle4.container` .. `wakir-rust-cli-welle7.container`) + readiness-check extended from single-file to glob loader (`load_quadlet_installer_glob`). |
| G6 required_check_names | GREEN | GREEN | (no change) |

Two BLOCKED gates remain — both **Operator-Hand-only** per
`feedback_sandbox_host_trennung.md` (registry-egress + Sigstore-network
egress required). The substrate-side closeout is complete; the
remaining work is the two Operator-Hand actions per §5 Step 2 and
Step 3 below.

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

### S1. `cosign-verify-images.yml` — already on the PR surface

**This step is done, and it did not land as written here.** The
paragraph below described a path-filtered promotion that never
existed; PR #503 added `pull_request:` and `push: branches: [main]`
**without** a path filter, deliberately and with the reason recorded
in the workflow file: `cosign verify SPIRE images` is a required
status context, and a required context that does not report on every
pull request leaves the PR forever-pending
(`feedback_branch_protection_check_names.md`). The stale description
stood here from 2026-05-19 until 2026-09-21.

Current state, measured against `.github/workflows/cosign-verify-images.yml`
on 2026-09-21:

| Trigger | Present | Path filter |
|---|---|---|
| `workflow_dispatch` | yes | — |
| `push: branches: [main]` | yes | none |
| `pull_request` | yes | none |

All three jobs run on every pull request:

| Job display name | Required context | Asks |
|---|---|---|
| `cosign verify SPIRE images` | **yes** | live — Sigstore signature + registry digest |
| `digest-verify python:3.13-slim` | no | live — registry digest of the committed pin |
| `cosign verify wakir-provisioner` | no | live — Sigstore signature of the committed pin |

**The trigger cut — decided 2026-09-21, one job moved of the two
proposed.** Zone-C cross-review (Tomás Reinhart,
`agents-workspaces/dev-engineering/outbox/2026-09-21-tomas-zone-c-review-trigger-schnitt.md`)
gave the cut for `digest-verify python:3.13-slim` under two
conditions and **refused** it for `cosign verify wakir-provisioner`.

The test the cut follows is **not** *"can a pull request influence
this?"* — that question is one-part and too blunt. The test already
written into `containerfile-digest-pin-gate.yml` is four-part:
structural, hermetic, decidable from disk, **and always satisfiable
by the pull request that breaks it**. Applied job by job:

| Job | Follows a third party's calendar? | Outcome |
|---|---|---|
| `cosign verify SPIRE images` | yes, but it is a **required context** — moving it needs an Operator-Hand branch-protection change first, and `test_branch_protection_required_checks_doc.py` pins this file as its home | **stays**, unchanged |
| `digest-verify python:3.13-slim` | yes — DockerHub rebuilds the tag on its own schedule; no pull request can cause or cure that | **moved** to the schedule axis via `if: github.event_name != 'pull_request'` |
| `cosign verify wakir-provisioner` | **no** — our image, our registry, our workflow, our Quadlet pin | **stays**; cross-review refused |

The refusal for job 3 rests on an argument written in this house
before the job went red: *a dangling pin is not a calendar — the
remedy lies entirely with us, and it does not recur in cadence.* The
job is red right now for a true reason (the pinned digest 404s in
ghcr). Being red is not an argument for belonging somewhere else; a
procedure in which every finding justifies its own invisibility is
worse than the finding. The remedy is the provisioner rebuild plus
pin refresh, and it is Operator-Hand.

What the cut does **not** do, stated because the opposite was easy to
claim: it does not take liveness off the pull-request surface. Job 1
is itself a live network check — `cosign verify` against Sigstore
plus a `crane digest` cross-check that exits 2 on drift — and it is
the only one of the three that can block anything. An upstream
`spiffe` tag re-push or a Sigstore outage reds a **required** context
on **every** pull request, which is a repo-wide merge freeze. The cut
removes the two liveness exposures that block nothing and leaves the
one that blocks everything. That residual exposure is tracked
separately.

Coverage lost by the move: none. The structural half — that all pin
sites carry the same digest — lives in the required, hermetic job
`verify-containerfile-base-image-digest-pins` since #546, tree-wide,
through the same module.

The two conditions, and how they were met:

* **C1 — a scheduled run needs a receiver.** Measured: 40 workflow
  files, zero executable notification steps. The schedule axis was a
  place where checks disappear. Met by
  `.github/actions/report-scheduled-failure`
  (`docs/operations/scheduled-workflow-failure-receiver.md`), wired
  into this workflow and the six scheduled ones, and proven by a
  deliberately failing run rather than by review.
* **C2 — the model cited for the move was cited wrongly.**
  `Cosign-Keyless-OIDC-Drift-Probe (daily)` was quoted as the
  precedent for "liveness moves to `schedule`". It is the opposite:
  it runs on `schedule` **and** `workflow_dispatch` **and** `push`
  **and** `pull_request` without a path filter, it **is** one of the
  13 required contexts, and it is **hermetic** (stdlib + pyyaml,
  `--mode=baseline`, no network). Its calendar axis is an
  *addition* to its pull-request axis, never a replacement. It is
  therefore the model for **this** file's shape — `schedule` added to
  the existing `on:` block, nothing removed — and not a precedent for
  moving anything off the pull-request surface. Verified against the
  file and the live branch-protection rule on 2026-09-21.

Form of the change (C3): no new workflow file, no new
branch-protection context name, one `schedule:` entry added to the
existing `on:` block and one `if:` on job 2. A split would have left
`tests/infra/test_cosign_drift_coverage_a6.py` **green while its own
comment turned false** — the exact class this substrate work exists
to remove.

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
| **G3** `last_drift_probe_verdict == GREEN` | The most recent `tooling/baselines/cosign-drift/last-probe-envelope.json` carries `aggregate_verdict: GREEN` | Strict-flip on top of a drifted substrate red-flips immediately. |
| **G4** `policy_inventory_size == 15` | The policy carries the canonical 15 binaries in canonical order | Drift here means PRs against a wrong inventory size red. |
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
GREEN (lock-step), G5 GREEN (quadlet parity), G6 GREEN
(names known).

### Step 2a — Resolve G5 cross-substrate parity drift (CLOSED)

The baseline run reported G5 BLOCKED with the four wave-4..7
binaries (`state-backing-welle4`, `fsm-welle5`, `subscribe-loop-welle6`,
`recovery-welle7`) present in the policy but absent from
`quadlet/wakir-rust-cli.container`.

**Closeout (infrastructure engineering):** Resolution-B chosen and shipped. Four
dedicated per-wave Quadlets landed in lock-step:

* `quadlet/wakir-rust-cli-welle4.container` (state-backing-welle4)
* `quadlet/wakir-rust-cli-welle5.container` (fsm-welle5)
* `quadlet/wakir-rust-cli-welle6.container` (subscribe-loop-welle6)
* `quadlet/wakir-rust-cli-welle7.container` (recovery-welle7)

The readiness-check was extended from a single-file `--quadlet-installer`
arg to a glob-aware `--quadlet-glob` default
(`quadlet/wakir-rust-cli*.container`) that unions binary-names across
ALL matched Quadlets. The hermetic test surface gained four new tests
(TV-SM-20..TV-SM-23, TV-SM-27) plus on-disk substrate pins (TV-SM-24,
TV-SM-25) that catch a future wave-Quadlet drift.

Resolution-B was preferred over Resolution-A because the four
wave-4..7 binaries ship as *dedicated single-binary images*
(`ghcr.io/wakir-labs/wakir-persona-engine-state-backing-welle4` etc.)
per the mini wave inventory — they are NOT in the carrier
image, so the carrier-image installer (`wakir-rust-cli.container`)
cannot install them. The wave-N dedicated installer Quadlets pin
each wave-N image digest independently, enabling per-wave rollback
without touching the carrier-image digest.

G5 verdict on `main` post: **GREEN** (15/15 set-equality).

Cross-Review-Zone-C: dev engineering reviews the per-wave Quadlet substrate
+ the readiness-check glob-loader change at PR review-time.

### Step 2 — Operator-Hand carrier-image digest resolution

This is the same resolution path the `cosign-verify-images.yml`
workflow already documents:

1. Operator-Hand on a host with GHCR-network egress runs
   `infra/persona-engine/scripts/resolve-image-pins-ci.sh` (or the
   equivalent recipe), producing the byte-for-byte real
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
   `tooling/baselines/cosign-drift/pinned-trust-root.json` with the real values.
4. Re-run the readiness check; G2 flips from BLOCKED to GREEN.

### Step 4 — Capture the last-probe envelope (CLOSED for baseline-mode)

**Closeout (infrastructure engineering):** the baseline-mode envelope is now committed
to `tooling/baselines/cosign-drift/last-probe-envelope.json` (aggregate_verdict =
GREEN, generated via `python3 scripts/observability/cosign-keyless-oidc-drift-probe.py --mode baseline`).
G3 GREEN on `main` post.

The full Operator-Hand fixture-mode envelope (which requires a live
Sigstore-network egress snapshot) is still owed at Strict-Flip time
so the trust-root axis verdict is grounded in a live snapshot rather
than the baseline self-consistency. Recipe stays the same as below.

1. Run the cosign-keyless-OIDC-drift-probe workflow:
   ```bash
   gh workflow run cosign-keyless-oidc-drift-probe -R wakir-labs/wakir-runtime
   ```
2. Wait for the run to complete. Confirm the aggregate verdict is
   GREEN (if not, the operator returns to §3 of the
   cosign-keyless-OIDC-drift-probe runbook).
3. Operator-Hand downloads the envelope artefact and commits it as
   `tooling/baselines/cosign-drift/last-probe-envelope.json` via PR #N3. The
   file is the byte-for-byte content of `envelope.json` from the
   workflow artefact.
4. Re-run the readiness check; G3 flips from NOT-CHECKED to GREEN.

### Step 5 — Cross-Review-Zone-C sign-off

Per the Container-Image-Pipeline × OTS-Anchoring cross-review zone
(ADR-0020 Zone C, dev engineering moderator): dev engineering reviews the post-Step-4
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
An operator may temporarily revert S2's `pull_request:`
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
| `policy_inventory_size` | `== 15` | canonical inventory lock-step. |
| `cross_substrate_parity_diff_count` | `== 0` | Quadlet ↔ policy parity. |
| Cross-Review-Zone-C sign-off | dev engineering | Procedural gate (Container-Image-Pipeline × OTS-Anchoring zone). |
| Baseline run ID recorded | non-empty | For rollback per Step 7. |

A run that meets all seven thresholds is **flip-ready**. A run that
misses any of them blocks the flip and the operator returns to §5
at the failing step.

---

## 7. Audit-trail and traceability

The audit-trail for the Strict-Flip consists of:

* The baseline run-id (Step 1) and its `head_sha` for `main`.
* The PR numbers from Steps 2 / 3 / 4 / 6.
* dev engineering's Cross-Review-Zone-C sign-off comment from Step 5.
* The post-flip readiness-check run from Step 6 (must be GREEN).
* The branch-protection change record from Step 6
  (via `gh api repos/wakir-labs/wakir-runtime/branches/main/protection`
  snapshot pre + post).

All five items are captured in the operator's task-archive entry
under the heading "Cosign-Strict-Mode Activation — completion log".

---
