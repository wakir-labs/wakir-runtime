<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Cross-Repo-Drift — Enforce-Flip Readiness

**Status:** Living operations document (read by humans + parsed by tests).
**Scope:** `wakir-labs/wakir-runtime` ↔ `wakir-labs/wakir-protocol`,
mirror-pair inventory shipped by `.github/workflows/cross-repo-drift-audit.yml`
(PR #105) and extended by PR #111.
**Authored:** 2026-05-16 (Tomás, Sprint-Cross-Repo-Drift-Enforce-Flip-
Readiness-MINI).
**ADR-Anker:** ADR-0062 Cut-2 / Cut-3.

---

## 1. Why this document exists

PR #105 introduced the cross-repo drift audit in **audit-only mode**
because Reza measured a Day-1 drift baseline of `6/10` mirror-pairs.
Flipping `CROSS_REPO_DRIFT_ENFORCE=true` *today* would red the runtime
`main` on every push that touches a mirrored substance file — a false
positive against the schema-contract surface, since the drift is
known-tolerated SPDX-header drift plus in-flight version-bump rows.

The Enforce-Flip is therefore gated on a controlled drift-cleanup
sequence. This document is the operator's checklist for that sequence
and the single source of truth for *which* drift each mirror-pair
currently carries, *how* to resolve it, and *what* gate-thresholds the
inventory must cross before the flip is safe.

The companion hermetic test
`tests/infra/test_cross_repo_drift_enforce_readiness.py` pins the
mirror-pair inventory, the resolution-strategy logic, the allowlist-
entry validator, and the acceptance-gate thresholds into CI so a future
drift in *this* document is also caught by the tripwire it describes.

---

## 2. Mirror-pair inventory — drift status (2026-05-16)

The ten pairs are the literal `pairs=( ... )` array from
`.github/workflows/cross-repo-drift-audit.yml` (PR #105). The status
column reflects Reza's Day-1 measurement (PR #105 + #111).

| # | Runtime path | Protocol path | Status | Resolution-Strategy | Owner |
|---|---|---|---|---|---|
| 1 | `wirelang/schemas/layer-0-transport.json` | `wakir_protocol/schemas/layer-0-transport.json` | `drift` | `re-sync-protocol-from-runtime` | Reza |
| 2 | `wirelang/schemas/layer-1-wire.json` | `wakir_protocol/schemas/layer-1-wire.json` | `drift` | `re-sync-protocol-from-runtime` | Reza |
| 3 | `wirelang/schemas/layer-2-semantic.json` | `wakir_protocol/schemas/layer-2-semantic.json` | `drift` | `re-sync-protocol-from-runtime` | Reza |
| 4 | `wirelang/schemas/layer-3-capability-token.json` | `wakir_protocol/schemas/layer-3-capability-token.json` | `clean` | — | — |
| 5 | `wirelang/schemas/aip-document.json` | `wakir_protocol/schemas/aip-document.json` | `drift` | `re-sync-runtime-from-protocol` | Reza |
| 6 | `wirelang/schemas/datalog-caveat.json` | `wakir_protocol/schemas/datalog-caveat.json` | `clean` | — | — |
| 7 | `wirelang/schemas/federation-trust-document.json` | `wakir_protocol/schemas/federation-trust-document.json` | `clean` | — | — |
| 8 | `wirelang/canonical/caveat_set.py` | `wakir_protocol/canonical/caveat_set.py` | `drift` | `allowlist-spdx-header-only` | Tomás |
| 9 | `wirelang/identity/aip_document.py` | `wakir_protocol/identity_substrate/aip_document.py` | `drift` | `allowlist-spdx-header-only` | Tomás |
| 10 | `wirelang/identity/dns_anchor.py` | `wakir_protocol/identity_substrate/dns_anchor.py` | `clean` | — | — |

Tally: `clean=4`, `drift=6`, `missing=0`. Matches Reza's `6/10`.

### 2.1 Status legend

| Status | Meaning |
|---|---|
| `clean` | Both files exist, SHA-256 identical. No action. |
| `drift` | Both files exist, SHA-256 differ, not on allowlist. |
| `missing-runtime` | Runtime-side file absent. Mirror is broken on runtime. |
| `missing-protocol` | Protocol-side file absent. Mirror is broken on protocol. |
| `missing-both` | Neither side has it; either delete the pair or seed it. |
| `drift-allowed` | Drift exists but `(runtime, protocol)` pair is allowlisted. |

---

## 3. Resolution strategies

A driftem pair must be resolved by exactly **one** of the following
strategies before the Enforce-Flip. The strategy choice is binding
once recorded: re-flipping strategies mid-cleanup invalidates the
gate.

### 3.1 `re-sync-protocol-from-runtime` — 1-way migration (R → P)

The runtime file is authoritative; the protocol file is stale. Use
this when the substance evolved in the BUSL-runtime branch first and
the Apache-published protocol reference simply lagged behind.

Operator steps:

1. Open the runtime file in the worktree, copy verbatim bytes.
2. Open a PR against `wakir-protocol` that overwrites the protocol
   file with the runtime bytes. SPDX header on the protocol side must
   remain `Apache-2.0` (NOT `BUSL-1.1`); update only the substance
   block beneath the SPDX header.
3. Wait for `wakir-protocol/main` merge.
4. Re-run `cross-repo-drift-audit` on `wakir-runtime`; the pair must
   flip to `clean` (or `drift-allowed` if only the SPDX header
   differs after the substance sync).

### 3.2 `re-sync-runtime-from-protocol` — 1-way migration (P → R)

The protocol file is authoritative; the runtime file is stale. Use
this when the published contract surface is the one external adopters
already validate against and the runtime simply has not picked up the
contract update yet.

Operator steps:

1. Open the protocol file, copy verbatim bytes (excluding the
   `Apache-2.0` SPDX header).
2. Open a PR against `wakir-runtime` that overwrites the runtime
   file with the protocol bytes. SPDX header on the runtime side must
   remain `BUSL-1.1`; update only the substance block.
3. Wait for `wakir-runtime/main` merge.
4. Re-run `cross-repo-drift-audit` on `wakir-runtime`; the pair must
   flip to `clean` (or `drift-allowed` if only the SPDX header
   differs after the substance sync).

### 3.3 `allowlist-spdx-header-only` — drift admitted as waiver

The drift is structurally tolerated SPDX-header-only drift between
`Apache-2.0` (protocol) and `BUSL-1.1` (runtime). The substance bytes
beneath the headers are identical; the entire delta is the license
identifier line. Use this **only** when the byte-diff is verifiably
header-only (operator runs a side-by-side diff and confirms).

Operator steps:

1. Side-by-side diff the two files. Confirm: only the SPDX header
   line differs.
2. Append an `allow:` entry to `.cross-repo-drift-allowlist.yaml`
   on the runtime side. Required keys: `runtime`, `protocol`,
   `reason`. Optional but recommended: `follow_up`. See §5 for
   the exact schema.
3. Re-run `cross-repo-drift-audit`; the pair must flip from `DRIFT`
   to `drift-allowed`.

### 3.4 `allowlist-divergent-variant` — bewusst divergent

The two files are *intentionally* allowed to differ because the
runtime carries a BUSL-only optimization (e.g. a faster code path,
a runtime-only telemetry hook) that the published protocol contract
does not mandate. Use sparingly — each entry weakens the cross-repo
invariant.

Operator steps:

1. Document the substantive reason for divergence in the
   `reason` field; reference the ADR that approved the variant.
2. Append an `allow:` entry to `.cross-repo-drift-allowlist.yaml`
   with `follow_up: permanent` or an ADR reference.
3. Cross-Review-Zone-3 (Reza + Tomás) must counter-sign by
   review-approval on the allowlist PR.
4. Re-run `cross-repo-drift-audit`; the pair must flip from
   `DRIFT` to `drift-allowed`.

### 3.5 Resolution-strategy decision table

This table is the *normative* mapping consumed by the hermetic test
suite (TV-RES-04). The audit workflow uses status names; the
resolution-strategy mapper recommends a default strategy per status,
which the operator may override with documented reason.

| Drift type | Default resolution-strategy | Override allowed? |
|---|---|---|
| `drift` (substance differs, runtime newer) | `re-sync-protocol-from-runtime` | yes (→ allowlist-divergent-variant w/ ADR ref) |
| `drift` (substance differs, protocol newer) | `re-sync-runtime-from-protocol` | yes (→ allowlist-divergent-variant w/ ADR ref) |
| `drift` (SPDX-header only) | `allowlist-spdx-header-only` | no |
| `drift` (bewusst divergent) | `allowlist-divergent-variant` | no |
| `missing-runtime` | `re-sync-runtime-from-protocol` (seed) | no |
| `missing-protocol` | `re-sync-protocol-from-runtime` (seed) | no |
| `missing-both` | delete the mirror-pair from the workflow inventory | yes (→ seed-both) |
| `clean` | — | — |
| `drift-allowed` | — | — |

---

## 4. Operator drift-cleanup sequence

The cleanup sequence is **strict-order**: each step depends on the
prior one having merged into the respective `main` branch and the
audit having re-confirmed the expected status flip. Skipping ahead
risks an Enforce-Flip with stale drift counts.

### Step 1 — Snapshot baseline

Run `gh workflow run cross-repo-drift-audit -R wakir-labs/wakir-runtime`
on the current `main`. Confirm the tally matches §2 (drift=6). Save
the workflow run-id as the *baseline run* for the rollback story.

### Step 2 — SPDX-header-only allowlist seed

For pairs `8` and `9` (rows in §2), file PR #N1 against
`wakir-runtime` that appends two allowlist entries with
`reason: SPDX-header-only`. Re-run the audit, confirm `drift=4` and
`drift-allowed=2`.

### Step 3 — Re-sync `re-sync-protocol-from-runtime` (rows 1,2,3)

For pairs `1`, `2`, `3` (Layer-0 / Layer-1 / Layer-2 schemas), file
PR #N2 against `wakir-protocol` that copies the runtime bytes (see
§3.1). Wait for merge. Re-run the runtime audit. Confirm `drift=1`
and `drift-allowed=2`.

### Step 4 — Re-sync `re-sync-runtime-from-protocol` (row 5)

For pair `5` (AIP document), file PR #N3 against `wakir-runtime`
that copies the protocol bytes (see §3.2). Wait for merge. Re-run
the audit. Confirm `drift=0`, `drift-allowed=2`, `clean=8`.

### Step 5 — Cross-Review-Zone-3 sign-off

Reza + Tomás review the post-Step-4 audit run. Both leave a
sign-off comment on the run referencing this document. The sign-off
comment is the audit-trail entry; no separate ADR.

### Step 6 — Mira-Hand Enforce-Flip

Mira-Hand operator changes the default in
`.github/workflows/cross-repo-drift-audit.yml`:

```yaml
env:
  CROSS_REPO_DRIFT_ENFORCE: ${{ github.event.inputs.enforce || 'true' }}
```

(literal one-character flip: `'false'` → `'true'`). PR #N4 against
`wakir-runtime`. The PR description references this document by
heading anchor.

### Step 7 — Branch-Protection required-status update

After the Enforce-Flip merges, add the audit job's display-name to
`wakir-runtime` branch-protection required-status-checks per
`docs/operations/branch-protection-required-status-checks.md`. This
is what makes the audit a *hard gate* on every PR going forward.

### Step 8 — Rollback path

If a post-flip PR is unjustly red'd by drift the cleanup missed,
Mira-Hand may temporarily set `CROSS_REPO_DRIFT_ENFORCE: 'false'`
via `workflow_dispatch.inputs.enforce` for that one PR's required
re-run, while the new drift is resolved per §3. Reverting the env
default itself requires a separate PR.

---

## 5. Allowlist-entry schema (consumed by §3.3 / §3.4)

The `.cross-repo-drift-allowlist.yaml` schema is the same shape that
PR #105 already documents. The Enforce-Flip readiness contract adds
*validation* on top of the existing permissive loader: an allowlist
entry that does **not** satisfy the rules below is rejected by the
hermetic test `test_tv_acc_03_allowlist_entry_validation`.

Required keys:

* `runtime`: string, must equal the runtime-side path of one of the
  mirror-pairs in the workflow's `pairs=( ... )` array (literal
  match).
* `protocol`: string, must equal the protocol-side path of the same
  mirror-pair (literal match, paired with `runtime`).
* `reason`: string, non-empty. Free-text justification.

Optional keys:

* `follow_up`: string. Either an ADR reference (`ADR-NNNN`), a
  sprint reference (`sprint-<slug>`), or the literal `permanent`.

Forbidden:

* `runtime` and `protocol` keys that do not pair to one of the
  workflow's known mirror-pairs. (An allowlist that admits an
  unknown pair is a silent way to expand the contract surface
  without review.)
* Empty or missing `reason`. ("`drift-allowed` without a stated
  reason" is exactly the audit failure mode we want to prevent.)

---

## 6. Acceptance-gate thresholds for the Enforce-Flip

The thresholds below are the *normative* contract for "ready to
flip enforce". The hermetic test
`test_tv_acc_05_acceptance_thresholds` pins them into CI.

| Metric | Threshold | Rationale |
|---|---|---|
| `drift_count` | `== 0` | Zero un-allowlisted drift. The whole point. |
| `missing_count` | `== 0` | No half-mirrored pair. Either delete the row or seed it. |
| `allowed_drift_count` | `≤ 3` | Soft cap — each waiver weakens the invariant; >3 means we are admitting too much. |
| `ok_count + allowed_drift_count` | `== len(pairs)` | Every pair must have a definite verdict; no `__MALFORMED__` allowlist. |
| Cross-Review-Zone-3 sign-off | both Reza + Tomás | Procedural gate. |
| Baseline run ID recorded | non-empty | For rollback per Step 8. |

A run that meets all six thresholds is **flip-ready**. A run that
misses any of them blocks the flip and the operator returns to
§4 at the failing step.

---

## 7. Audit-trail and traceability

The audit-trail for the Enforce-Flip consists of:

* The baseline run-id (Step 1) and its `head_sha` for the
  `wakir-protocol` ref.
* The PR numbers from Steps 2 / 3 / 4 / 6.
* Reza + Tomás sign-off comments from Step 5.
* The post-flip audit run from Step 6 (must be green).
* The branch-protection change record from Step 7
  (via `gh api repos/wakir-labs/wakir-runtime/branches/main/protection`
   snapshot).

All seven items are captured in the operator's task-archive entry
under the heading "Cross-Repo-Drift Enforce-Flip — completion log".

---

— Tomás
