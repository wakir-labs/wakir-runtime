<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors -->

# wakir-protocol Cross-Review-Zone-3 Hand-off Plan (Tag-62)

**Owner:** Reza Tehrani (Wirelang / Spec)
**Date authored:** 2026-05-19 (Tag-62 marathon)
**Anchor PRs:** Tag-59 PR #376 (Reza mirror-seed seed-tree), Tag-60 PR #382
(Noa cross-repo-drift-allowlist audit substrate), Tag-61 PR #388 (Reza
trajectory-re-sync seed extension, ENFORCE-READY post-resync score 92).
**ADR-Anker:** ADR-0023a (Sandbox-Boundary), ADR-0062 (Cross-Repo-Drift
Cut-2 / Cut-3), Cross-Review-Zone-3 (OTS-Schema-Anker-Kompatibilität).

> **Form discipline.** This document is *plan-only*. It does **not**
> mutate `wakir-protocol`. The actual hand-off mirror PR against
> `wakir-labs/wakir-protocol` is **Operator-Hand** (Tomás
> Engineering-Lead, Mira-Hand authorisation). The plan exists so the
> Operator-Hand step is mechanical: copy paths, run recipe, verify
> ENFORCE-Flip.

---

## §1 Scope

This plan covers exactly one substance:

* **Cross-Review-Zone-3** — OTS-Schema-Anker-Kompatibilität. Reza
  owns the Wirelang schema-side spec definitions; Tomás owns the
  WAT-Layer-4 OTS-anchor format. The hand-off mirror PR is the path
  that lands the Reza-side canonical content in `wakir-protocol`
  at the **canonical mirror paths** the Tag-31 BASELINE_INVENTORY
  pins.
* **Purpose:** flip the locked Tag-31 baseline `score=76 /
  ENFORCE-CAUTION` to `score=92 / ENFORCE-READY` on **actual**
  protocol-side state (not just `--post-resync` projection from
  runtime-side seed-presence). Without the mirror PR landing, the
  audit's `--post-resync` flag is a projection; the real verdict
  stays `ENFORCE-CAUTION` because the protocol-side files have not
  been edited.
* **ENFORCE-Flip-Voraussetzung.** Three conditions must hold
  *together* before `CROSS_REPO_DRIFT_ENFORCE=true` is flipped on
  the runtime workflow:
  1. **Seed-tree completeness on runtime-side `main`.** All 8 seed
     files present at their canonical sub-paths (see §2). Pinned by
     `tests/audit/test_cut_3_protocol_mirror_seed_tag59.py` (13
     tests, Tag-59) and `tests/audit/test_trajectory_resync_tag61.py`
     (26 tests, Tag-61).
  2. **Mirror PR landed on `wakir-protocol` `main`.** The
     Operator-Hand hand-off PR (recipe in §4) has been merged and
     the protocol-side `main` carries the 8 canonical files at the
     mirror paths in §3.
  3. **Drift-audit verdict re-measured against post-merge state.**
     `audit_cross_repo_drift_allowlist.py` re-run on the freshly
     merged combination yields `score >= 90` without `--post-resync`
     (real measurement, not projection). See §5.

* **Out of scope.** This plan does not relicense, does not change
  layer-3-capability-token mirror (already `clean`), does not
  touch SPDX-header-only-drift rows (pairs 8/9, Tomás
  `allowlist-spdx-header-only` strategy), and does not pre-empt
  ADR-0062 Cut-4 (post-flip cleanup).

---

## §2 Source-state — runtime-side seed inventory

The runtime-side seed tree at `wirelang/specs/protocol-mirror-seed/`
is the single source of truth for the protocol-side canonical
content. All 8 files in this table are on runtime `main` as of
**Tag-61 PR #388 merge (2026-05-19)**.

| # | Source path (runtime-side) | Origin PR | SPDX (in-file) | Size | Notes |
|---|---|---|---|---|---|
| 1 | `wirelang/specs/protocol-mirror-seed/docs/observability/pre-mortem-failure-mode-notify-catalog.md` | Tag-59 PR #376 | Apache-2.0 | 372 lines | Tag-59 alert-routing mirror, Cut-3 hand-off |
| 2 | `wirelang/specs/protocol-mirror-seed/dashboards/phase-3-marathon-alerts.yaml` | Tag-59 PR #376 | Apache-2.0 | 1260 lines | Tag-59 alert-routing mirror, Cut-3 hand-off |
| 3 | `wirelang/specs/protocol-mirror-seed/dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml` | Tag-59 PR #376 | Apache-2.0 | 524 lines | Tag-59 alert-routing mirror, Cut-3 hand-off |
| 4 | `wirelang/specs/protocol-mirror-seed/scripts/observability/alert-rule-to-mira-notify-bridge.py` | Tag-59 PR #376 | Apache-2.0 | 829 lines | Tag-59 alert-routing mirror, Cut-3 hand-off |
| 5 | `wirelang/specs/protocol-mirror-seed/schemas/layer-0-transport.json` | Tag-61 PR #388 | Apache-2.0 (`x-spdx-license-identifier`) | 112 lines | Tag-61 schema mirror, trajectory-re-sync |
| 6 | `wirelang/specs/protocol-mirror-seed/schemas/layer-1-wire.json` | Tag-61 PR #388 | Apache-2.0 (`x-spdx-license-identifier`) | 121 lines | Tag-61 schema mirror, trajectory-re-sync |
| 7 | `wirelang/specs/protocol-mirror-seed/schemas/layer-2-semantic.json` | Tag-61 PR #388 | Apache-2.0 (`x-spdx-license-identifier`) | 104 lines | Tag-61 schema mirror, trajectory-re-sync |
| 8 | `wirelang/specs/protocol-mirror-seed/schemas/aip-document.json` | Tag-61 PR #388 | Apache-2.0 (`x-spdx-license-identifier`) | 177 lines | Tag-61 schema mirror, trajectory-re-sync; `re-sync-runtime-from-protocol` strategy (semantic note in §6) |

**Total:** 8 files, ~3499 lines. SPDX posture for every file is
**`Apache-2.0`** — already correct for the protocol-side. No
relicensing step needed during the hand-off.

The seed README at `wirelang/specs/protocol-mirror-seed/README.md`
documents the seed-tree convention but is **not** mirrored into
`wakir-protocol`. The README is a runtime-internal reference; the
protocol-side has its own existing top-level README.

---

## §3 Target-state — protocol-side canonical paths

Each seed file maps 1:1 to a canonical path in `wakir-protocol`.
The mapping is **literal**: no path-rewrite beyond stripping the
`wirelang/specs/protocol-mirror-seed/` prefix and adding the
protocol-side path prefix shown below. The 4 alert-routing files
map under `wakir_protocol/observability/` and `wakir_protocol/
dashboards/` (Tag-59 mirror-audit canonical layout). The 4 schema
files map under `wakir_protocol/schemas/` (Tag-31 BASELINE_INVENTORY
canonical layout).

| # | Runtime-side seed path | Protocol-side canonical path |
|---|---|---|
| 1 | `wirelang/specs/protocol-mirror-seed/docs/observability/pre-mortem-failure-mode-notify-catalog.md` | `wakir_protocol/docs/observability/pre-mortem-failure-mode-notify-catalog.md` |
| 2 | `wirelang/specs/protocol-mirror-seed/dashboards/phase-3-marathon-alerts.yaml` | `wakir_protocol/dashboards/phase-3-marathon-alerts.yaml` |
| 3 | `wirelang/specs/protocol-mirror-seed/dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml` | `wakir_protocol/dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml` |
| 4 | `wirelang/specs/protocol-mirror-seed/scripts/observability/alert-rule-to-mira-notify-bridge.py` | `wakir_protocol/scripts/observability/alert-rule-to-mira-notify-bridge.py` |
| 5 | `wirelang/specs/protocol-mirror-seed/schemas/layer-0-transport.json` | `wakir_protocol/schemas/layer-0-transport.json` |
| 6 | `wirelang/specs/protocol-mirror-seed/schemas/layer-1-wire.json` | `wakir_protocol/schemas/layer-1-wire.json` |
| 7 | `wirelang/specs/protocol-mirror-seed/schemas/layer-2-semantic.json` | `wakir_protocol/schemas/layer-2-semantic.json` |
| 8 | `wirelang/specs/protocol-mirror-seed/schemas/aip-document.json` | `wakir_protocol/schemas/aip-document.json` |

**Apache-2.0 SPDX banner discipline.** Each protocol-side file
**must** carry the file's existing in-file SPDX banner unchanged.
Do not strip the banner; do not re-author it; do not add a second
banner. The seed canonicaliser already strips SPDX/copyright on
both sides before SHA-256 (see Tag-58 mirror-audit), so the banners
are protected against drift-verdict false-positives. For JSON
schemas, the banner is the `x-spdx-license-identifier` /
`x-spdx-file-copyright-text` pair embedded in the schema body (a
JSON object cannot carry a comment header).

**Existing protocol-side state assumption.** Files 1..4 are
**absent** on `wakir-protocol` `main` today (Tag-58 audit verdict
was 4 × `missing-protocol`). Files 5..7 **exist with drift**
(strategy `re-sync-protocol-from-runtime` — runtime is source of
truth, protocol-side overwrite). File 8 **exists with drift**
(strategy `re-sync-runtime-from-protocol` — see §6 special note).

---

## §4 Operator-Hand-PR-Recipe

The recipe assumes the operator has `gh` CLI authenticated against
`wakir-labs` and a clean working directory.

### §4.1 Clone protocol-side repo

```
git clone --depth=50 git@github.com:wakir-labs/wakir-protocol.git
cd wakir-protocol
git checkout main
git pull --ff-only origin main
```

A shallow clone is sufficient; the hand-off PR only touches the 8
mirror paths.

### §4.2 Branch naming

```
git checkout -b reza/tag-62-cross-review-zone-3-handoff
```

Branch name discipline: lowercase, persona/tag/topic, no spaces,
no underscores. Slug `reza/tag-62-cross-review-zone-3-handoff`
matches the runtime-side plan-doc branch `reza/tag-62-protocol-
handoff-plan` semantically (different repos, same anchor).

### §4.3 Copy seed files

Source path: a sibling clone of `wakir-runtime` at
`../wakir-runtime/wirelang/specs/protocol-mirror-seed/`. The
operator runs **eight literal `cp` invocations** (no globs, no
recursive copy) to keep the mirror set explicit and auditable:

```
SRC=../wakir-runtime/wirelang/specs/protocol-mirror-seed
mkdir -p wakir_protocol/docs/observability
mkdir -p wakir_protocol/dashboards
mkdir -p wakir_protocol/scripts/observability
mkdir -p wakir_protocol/schemas

cp "$SRC/docs/observability/pre-mortem-failure-mode-notify-catalog.md" \
   wakir_protocol/docs/observability/pre-mortem-failure-mode-notify-catalog.md
cp "$SRC/dashboards/phase-3-marathon-alerts.yaml" \
   wakir_protocol/dashboards/phase-3-marathon-alerts.yaml
cp "$SRC/dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml" \
   wakir_protocol/dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml
cp "$SRC/scripts/observability/alert-rule-to-mira-notify-bridge.py" \
   wakir_protocol/scripts/observability/alert-rule-to-mira-notify-bridge.py
cp "$SRC/schemas/layer-0-transport.json" \
   wakir_protocol/schemas/layer-0-transport.json
cp "$SRC/schemas/layer-1-wire.json" \
   wakir_protocol/schemas/layer-1-wire.json
cp "$SRC/schemas/layer-2-semantic.json" \
   wakir_protocol/schemas/layer-2-semantic.json
cp "$SRC/schemas/aip-document.json" \
   wakir_protocol/schemas/aip-document.json
```

**Why eight literal `cp` calls?** Glob copying obscures the
mirror-set boundary. The audit-trail prefers explicit one-line-per-
file evidence in the PR diff. Reviewer can scan the recipe and the
diff in parallel.

### §4.4 Commit style

```
git add wakir_protocol/docs/observability/pre-mortem-failure-mode-notify-catalog.md \
        wakir_protocol/dashboards/phase-3-marathon-alerts.yaml \
        wakir_protocol/dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml \
        wakir_protocol/scripts/observability/alert-rule-to-mira-notify-bridge.py \
        wakir_protocol/schemas/layer-0-transport.json \
        wakir_protocol/schemas/layer-1-wire.json \
        wakir_protocol/schemas/layer-2-semantic.json \
        wakir_protocol/schemas/aip-document.json

git commit -m "feat(mirror): Tag-62 Cross-Review-Zone-3 hand-off (Reza seed -> protocol)"
```

Single-commit hand-off keeps the rollback story simple. No file
edits — pure byte-identical copy from the runtime-side seed.

### §4.5 PR open

```
gh pr create \
  --repo wakir-labs/wakir-protocol \
  --base main \
  --head reza/tag-62-cross-review-zone-3-handoff \
  --title "Tag-62 Cross-Review-Zone-3 hand-off (8 mirror files, runtime seed -> protocol)" \
  --body-file PR_BODY.md
```

The PR body must include: (a) anchor PRs `wakir-runtime#376`,
`wakir-runtime#382`, `wakir-runtime#388`; (b) the 8-row mirror
table from §3; (c) the verification-steps stanza from §5; (d) the
Sandbox-Boundary stanza from §7.

### §4.6 Merge

```
gh pr review --repo wakir-labs/wakir-protocol <N> --approve
gh pr merge --repo wakir-labs/wakir-protocol <N> --squash --delete-branch
```

Mira-Hand authorisation required pre-merge per ADR-0023a.
Force-push not needed (mirror PR has no rebase conflicts: the
target paths are either missing or fully overwritten by the seed
content).

---

## §5 Verification — post-Operator-Hand ENFORCE-Flip

Three checks must pass **after** the mirror PR merges on
`wakir-protocol` `main`. The runtime-side enforce-flip-flag flip
is gated on all three.

### §5.1 Runtime-side seed audit still green

```
cd wakir-runtime
python3 tooling/ci/audit_cross_repo_drift_allowlist.py \
        --repo-root . \
        --post-resync \
        --fail-on caution
```

Expected: exit 0, `post_resync_score=92`, verdict `ENFORCE-READY`.
This re-confirms the seed tree is intact on runtime-side; the
mirror PR did not require any runtime-side change.

### §5.2 Cross-repo drift audit measured on real protocol state

```
cd wakir-runtime
.github/workflows/cross-repo-drift-audit.yml  # via workflow_dispatch
```

The workflow clones `wakir-protocol` `main`, runs the 10-pair
SHA-256 comparison, and reports a fresh verdict. **Expected
verdict-shape:**

| Pair | Before (Tag-31 baseline) | After mirror PR |
|---|---|---|
| 1 | layer-0-transport.json | `drift` | `clean` |
| 2 | layer-1-wire.json | `drift` | `clean` |
| 3 | layer-2-semantic.json | `drift` | `clean` |
| 4 | layer-3-capability-token.json | `clean` | `clean` |
| 5 | aip-document.json | `drift` | `clean` |
| 6 | datalog-caveat.json | `clean` | `clean` |
| 7 | federation-trust-document.json | `clean` | `clean` |
| 8 | canonical/caveat_set.py | `drift` (SPDX-only, allowlisted) | `drift-allowed` |
| 9 | identity/aip_document.py | `drift` (SPDX-only, allowlisted) | `drift-allowed` |
| 10 | identity/dns_anchor.py | `clean` | `clean` |

**Real score** (no `--post-resync` flag): `coverage=1.0`,
`trajectory_ratio = 8/10 = 0.80` (pairs 1, 2, 3, 4, 5, 6, 7, 10
all `clean`; pairs 8, 9 `drift-allowed` count as effectively-
resolved against the score formula's allowlist coverage term).

`score = round(60 * 1.0 + 40 * 0.80) = round(60 + 32) = 92 →
ENFORCE-READY`. Identical to the runtime-side `--post-resync`
projection.

### §5.3 ENFORCE-Flip trigger

Once §5.1 and §5.2 are both green, the operator opens a runtime-
side follow-up PR (separate, **not** part of this plan) that flips
`CROSS_REPO_DRIFT_ENFORCE: true` in
`.github/workflows/cross-repo-drift-audit.yml`. That flip-PR is
the final step. It is **not** part of the hand-off plan; this plan
ends at §5.2.

The flip-PR must reference this plan doc and the §5.2 verdict in
its body as the gate-evidence.

---

## §6 Failure-modes

Three failure-modes are pre-mapped. Each carries a Symptom,
Diagnosis, Recovery, and Owner.

### §6.1 Path-Drift

* **Symptom.** §5.2 audit reports `missing-protocol` for one or
  more of the 8 pairs even though the mirror PR claims to have
  copied them.
* **Diagnosis.** A protocol-side canonical path in §3 was
  mistyped during the recipe-run, or the protocol-side directory
  layout has shifted since Tag-31 BASELINE_INVENTORY was locked
  (e.g. `wakir_protocol/observability/` vs.
  `wakir_protocol/docs/observability/`).
* **Recovery.** Operator opens a **path-fix PR** on
  `wakir-protocol`. Do **not** edit this plan doc unless the
  Tag-31 BASELINE_INVENTORY itself moves; that is a separate
  ADR-0062 follow-up. Path-fix PR must reference §3 of this plan
  for the canonical layout-of-record.
* **Owner.** Tomás (Engineering-Lead, Cross-Review-Zone-3).

### §6.2 License-Header-Drift

* **Symptom.** §5.2 audit reports `drift` (not `clean`) for one or
  more of the 8 pairs after the mirror PR lands.
* **Diagnosis.** The canonicaliser strips SPDX/copyright before
  SHA-256. A `drift` verdict therefore means the **content** —
  not just the header — differs. Most likely cause: the operator
  edited a file in transit (e.g. line-ending normalisation, byte-
  order-mark, file editor auto-format).
* **Recovery.** Re-run §4.3 with **raw `cp`** (no editor open in
  the middle). Verify with `sha256sum` on both sides:
  ```
  sha256sum wakir-runtime/wirelang/specs/protocol-mirror-seed/schemas/layer-0-transport.json
  sha256sum wakir-protocol/wakir_protocol/schemas/layer-0-transport.json
  ```
  Hashes must match exactly. If they don't, the file in the
  mirror PR is corrupted; re-copy and amend the PR.
* **Owner.** Reza (seed-tree author) + Tomás (mirror PR author)
  jointly; the canonicaliser test
  `test_seed_files_byte_identical_to_runtime_schemas` is the
  oracle.

### §6.3 Conflict

* **Symptom.** The mirror PR fails to apply because a parallel
  PR on `wakir-protocol` `main` has already mutated one of the 8
  target paths.
* **Diagnosis.** Cross-Repo-Drift Cut-2 has been bypassed by an
  out-of-band protocol-side edit. This is an ADR-0023a violation
  (Reza-content on protocol-side without seed-tree path), or a
  Cut-2 race condition (a non-Reza owner has edited the file
  legitimately for a different reason).
* **Recovery.** Operator does **not** force-overwrite. Operator
  pauses the mirror PR, opens a triage issue on `wakir-protocol`
  citing this plan doc §6.3, and routes to Cross-Review-Zone-3
  weekly session (Tomás moderates, Aisha protocols, Mira
  approves). The hand-off is re-planned only after the conflict
  is resolved; this plan doc is the input to that re-plan.
* **Owner.** Mira (gate-keeper); Tomás (Cross-Review-Zone-3
  moderator); Reza (seed-tree author).

### §6.4 Special note — pair 5 (`aip-document.json`) strategy

Pair 5 is the only re-sync row with strategy
`re-sync-runtime-from-protocol` (not `re-sync-protocol-from-
runtime`). The Tag-31 baseline records that the **protocol-side**
is source-of-truth for `aip-document.json`. Tag-61 seeded the
canonical protocol-side bytes into the runtime-side seed tree
anyway (the seed is a byte-identical mirror — the *direction* of
truth is metadata, not file content). The hand-off PR therefore
copies seed → protocol unchanged; but if §6.2 fires for pair 5
specifically, recovery is **runtime-side update** (runtime
overwrites its own copy with the seed content), not protocol-side
update. Document the deviation in the recovery PR description.

---

## §7 Sandbox-Boundary

> This stanza is the **single most important** stanza in the
> document. Read it twice.

**Sandbox-Scope.** This plan was authored by Reza (Wirelang
agent) inside the Mira sandbox at
`/var/home/fred/AI-Corp/agents-workspaces/reza/tag-62-protocol-
handoff-plan-runtime/`. Reza has zero authority and zero ability
to mutate `wakir-labs/wakir-protocol`. The seed tree at
`wirelang/specs/protocol-mirror-seed/` is the only path through
which Reza-authored content reaches the protocol-side, and that
path passes through this hand-off plan and an Operator-Hand PR
(Tomás Engineering-Lead).

**Out-of-Sandbox-Scope (Operator-Hand).** All §4 steps are
Operator-Hand. Specifically:

* `git clone git@github.com:wakir-labs/wakir-protocol.git` — uses
  operator's authenticated SSH key. Sandbox has no protocol-repo
  credentials.
* `gh pr create --repo wakir-labs/wakir-protocol` — uses
  operator's GitHub token. Sandbox token has no
  `wakir-protocol` write scope.
* `gh pr merge --repo wakir-labs/wakir-protocol --squash` —
  requires Mira-Hand authorisation per ADR-0023a (no automatic
  self-merge across the sandbox boundary).
* Verification §5.2 runs in CI (cross-repo-drift-audit workflow)
  which clones `wakir-protocol` with workflow-scoped credentials,
  not the sandbox's credentials.

The plan-doc itself, the helper script
`tooling/ci/verify_protocol_handoff_plan_doc.py`, and the test
suite `tests/audit/test_protocol_handoff_plan_doc_tag62.py` all
live on the runtime-side. They are within Sandbox-Scope; they pin
the *plan*, they do not execute the hand-off.

**Operator-Hand-Sandbox-Gap.** The gap between §5.1 (runtime-side
projection) and §5.2 (real protocol-side measurement) is the
Operator-Hand-Sandbox-Gap. Sandbox can only project; the operator
must measure. The flip-PR in §5.3 must cite the §5.2 measurement
(real verdict) not §5.1 (projection); otherwise the ENFORCE-Flip
is built on a hypothetical and will reverse the moment the next
push happens.

---

## §8 Cross-Anchor

* **Tag-59 PR #376** — Reza (Wirelang) Cut-3 protocol-side
  alert-routing mirror-seed. Introduced the 4 alert-routing seed
  files (files #1..#4 in §2). 13 tests pin the seed-tree-detect
  stage in the mirror-audit.
  Anchor commit: `208435f` on runtime `main`.
* **Tag-60 PR #382** — Noa (SRE) cross-repo-drift-allowlist-audit
  pre-enforce-flip-readiness substrate. Introduced
  `audit_cross_repo_drift_allowlist.py`, the score formula
  `score = round(60 * coverage + 40 * trajectory)`, and the
  locked Tag-31 BASELINE_INVENTORY (score=76,
  verdict=ENFORCE-CAUTION). 19 tests.
  Anchor commit: `204d787` on runtime `main`.
* **Tag-61 PR #388** — Reza (Wirelang) cross-repo-drift-allowlist
  trajectory-re-sync. Introduced the 4 schema seed files (files
  #5..#8 in §2), `detect_trajectory_resync()`, and
  `compute_post_resync_score()`. Demonstrated post-resync score
  92 / ENFORCE-READY. 26 tests.
  Anchor commit: `a2e6cfd` on runtime `main`.
* **This plan (Tag-62)** — runtime-side plan-doc + helper +
  tests. The Operator-Hand mirror PR against
  `wakir-labs/wakir-protocol` is the deliverable this plan
  prepares. The plan does **not** include the flip-PR (§5.3); the
  flip-PR is a separate runtime-side PR gated on §5.2 evidence.

### §8.1 ADR anchors

* **ADR-0023a** — Sandbox-Boundary discipline. Reza must not
  write `wakir-protocol` directly.
* **ADR-0062** — Cross-Repo-Drift Cut-2 / Cut-3. The
  drift-cleanup sequence this plan operationalises.
* **Cross-Review-Zone-3** — OTS-Schema-Anker-Kompatibilität.
  Tomás moderates, Aisha protocols, Mira approves.

-- Reza
