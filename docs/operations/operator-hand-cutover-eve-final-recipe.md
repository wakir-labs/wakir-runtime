---
title: "Operator-Hand Cutover-Eve Final-Recipe Konsolidat (Tag-66)"
status: "active"
owner: "kai"
audience: "operator,ar,engineering"
created: "2026-05-19"
tag: "tag-66"
predecessors:
  - "docs/operations/strict-flip-readiness-map-tag58.md"
  - "docs/operations/bulk-activation-pre-walk-recipe.md"
  - "docs/operations/branch-protection-required-checks-tag64-companion.md"
  - "docs/operations/open-k3-v907-baseline-metadata-carry-forward.md"
related_adrs:
  - "ADR-0020"
  - "ADR-0036"
  - "ADR-0061"
  - "ADR-0065"
  - "ADR-0066"
related_docs:
  - "docs/operations/phase-3c-cutover-runbook.md"
  - "docs/operations/strict-flip-readiness-map-tag58.md"
  - "docs/operations/bulk-activation-pre-walk-recipe.md"
  - "docs/operations/bulk-activation-subsumption-check-8-coordination.md"
  - "docs/operations/branch-protection-required-checks-tag59.md"
  - "docs/operations/branch-protection-required-checks-tag61-addendum.md"
  - "docs/operations/branch-protection-required-checks-tag64-companion.md"
  - "docs/operations/cosign-g1-g2-operator-setup.md"
  - "docs/operations/cosign-strict-mode-activation.md"
  - "docs/operations/open-k3-v907-baseline-metadata-carry-forward.md"
  - "docs/operations/phase-3c-welle-1-runbook.md"
  - "docs/operations/phase-3c-welle-2-runbook.md"
  - "docs/operations/phase-3c-welle-3-runbook.md"
  - "docs/operations/phase-3c-welle-4-runbook.md"
  - "docs/operations/phase-3c-welle-5-runbook.md"
  - "docs/operations/phase-3c-welle-6-runbook.md"
  - "docs/operations/phase-3c-welle-7-runbook.md"
  - "docs/operations/g1-g2-last-mile-operator-checklist.md"
related_prs:
  - "#367"
  - "#375"
  - "#389"
  - "#396"
  - "#400"
  - "#401"
  - "#404"
  - "#407"
  - "#408"
  - "#411"
  - "#412"
related_memory:
  - "feedback_sandbox_host_trennung.md"
  - "feedback_live_bringup_sandbox_gap.md"
  - "feedback_continuous_mode_keine_push_frage.md"
  - "feedback_branch_protection_check_names.md"
  - "feedback_anti_eskalations_drift.md"
related_zones:
  - "Zone-J/CI (Kai, Branch-Protection + Cosign-Strict + Bulk-Activation)"
  - "Zone-K (Tomás, REUSE-Wrap + OPEN-K3 Baseline-Metadata)"
  - "Zone-Engine (Selin, 0.5.3 Production-Readiness)"
  - "Zone-Audit (Amara, E2E-Smoke + Final-Acceptance)"
---

# Operator-Hand Cutover-Eve Final-Recipe Konsolidat (Tag-66)

This document is the **consolidated Operator-Hand Final-Recipe**
for the Cutover-Day-Eve (KW-23 Fr, 2026-05-29) plus the seven
operational days that follow (T0 → T0+6, KW-24 Mo–Mo). It folds
every prior Operator-Hand recipe substrate (Tag-58 Strict-Flip
Readiness Map, Tag-62 Bulk-Activation Pre-Walk Recipe, Tag-63
Walking-Skeleton, Tag-64 J3/K3 Carry-Forward, Tag-64 Subsumption-
Check-#8 Coordination, Tag-65 Walking-Skeleton Post-Verify) into
a single day-by-day plan that the Operator can read top-to-bottom
on Cutover-Eve.

This is **doc-form-only**. No workflow mutation, no `gh api PUT`,
no quadlet-service-file write, no branch-protection settings
change. Every active operation in this document is **Operator-
Hand-Sandbox-Gap** per ADR-0020 §10 and the Mira-Sandbox-vs-Host-
Operations rule (Memory `feedback_sandbox_host_trennung`). The
Mira-Sandbox produces this consolidated plan; the Operator (Fred
plus AR pair) executes it on the operator workstation.

This is also the **last consolidation surface before Cutover-Day**.
Tag-67..Tag-72 may add late-arrival probes or rollback-pin
refinements; the Eve-Doc here is the canonical day-by-day plan
the Operator opens at 06:00 CEST on 2026-05-29 (KW-23 Fr) and
re-opens at every T0..T0+6 morning.

AR-Vorzeichen "Halt vor Phase 4" (Tag-65 AR-Signal): explicitly
pinned in §9. No Phase-4 substrate (post-cutover stabilisation,
production-readiness review, brand-publication pulse) starts
without explicit AR-Hand re-arm. See §9.4.

---

## §1 — Scope

### §1.1 — Time window

This recipe spans **eight Operator-Touch-Days** running from
Cutover-Eve through T0+6:

| Tag-Anker | Calendar | Operator-Touch-Window | Role |
|---|---|---|---|
| Eve | 2026-05-29 (KW-23 Fr) | 14:00–18:00 CEST | Eve-Checklist + final freeze-confirm |
| T0 | 2026-06-08 (KW-24 Mo) | 06:00–14:00 CEST | Strict-Flip-PR-Merge + Welle-1 cutover-PR |
| T0+1 | 2026-06-09 (KW-24 Di) | 06:00–12:00 CEST | Welle-2 cutover-PR + OPEN-J3 LABEL-Patch |
| T0+2 | 2026-06-10 (KW-24 Mi) | 06:00–12:00 CEST | Welle-3 cutover-PR |
| T0+3 | 2026-06-11 (KW-24 Do) | 06:00–12:00 CEST | Welle-4 cutover-PR + Welle-1/2 stability-check |
| T0+4 | 2026-06-12 (KW-24 Fr) | 06:00–12:00 CEST | Welle-5 cutover-PR |
| T0+5 | 2026-06-15 (KW-25 Mo) | 06:00–12:00 CEST | Welle-6 cutover-PR |
| T0+6 | 2026-06-16 (KW-25 Di) | 06:00–14:00 CEST | Welle-7 cutover-PR + Marathon-Final-Bilanz |

Total Operator-Hand-Time budget: **≤ 48 h cumulative wall-clock
across eight days**, of which **≤ 24 h are merge-mutating windows**
(Strict-Flip-PR + 7 Welle-PRs). The remaining hours are dry-run
verifications, snapshot pulls, and AR-Hand-touchpoints.

### §1.2 — What is in scope

- The Operator-Hand sequence for the Strict-Flip-PR merge at T0.
- The Operator-Hand sequence for the seven Welle-Cutover-PRs at
  T0..T0+6.
- The Bulk-Activation walk for the 8-Required-Status-Check pool
  (post-Strict-Flip stabilisation window only).
- The OPEN-J3 Containerfile `image.version` LABEL-Patch sub-
  sequence (T0+1).
- The Walking-Skeleton Post-Activate-Verify gate that the
  Operator runs against the live snapshot after the bulk-walk.
- Rollback triggers, decision gates, and AR-Hand touchpoints.
- A Phase-4 freeze pin: **no Phase-4 work starts** until the AR
  explicitly re-arms.

### §1.3 — What is out of scope

- Live-VM rotation drills (Tag-60 substrate, completed pre-Eve).
- Wirelang-Spec freeze-seal probe (Tag-58 substrate, hold-steady).
- Cross-Substrate-Parity-Gate operations (Tag-57 substrate, hold-
  steady).
- OPEN-K3 V-907 baseline-metadata refresh (intentional carry-
  forward per Tag-64 doc; **not** touched in this recipe).
- Persona-Engine 0.5.3 → 0.5.4 work (Phase-4 scope, freeze pin).
- Site/quartz/frontend changes (Tomás-owned, not in this recipe).

### §1.4 — Cross-references

All seven Welle-PRs follow the per-Welle runbooks in
`docs/operations/phase-3c-welle-N-runbook.md` for N ∈ {1..7}.
The Eve-Doc here is the **dispatcher** — the per-Welle runbooks
remain the substantive recipe for each cutover-PR. See §7 for
the cross-reference matrix.

---

## §2 — Pre-Cutover-Eve-Checklist (KW-23 Fr, 2026-05-29)

The Operator opens this section on Cutover-Eve at 14:00 CEST and
works through the 12 checks below. Total time budget: **≤ 4 h
Operator-Hand-Time**, with the longest single block being the
final Strict-Flip-PR review (≤ 90 min).

### §2.1 — Eve-Check E1: CI-Surface Green-Status Confirmation

- **Owner**: Operator.
- **Action**: Open the wakir-runtime main-branch CI dashboard.
  Confirm all eight Required-Status-Checks are GREEN on the
  current main-tip commit:
  1. `pre-cutover-marathon-aggregate-verdict (READY / DRIFT)` — Tag-49 source.
  2. `cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)` — Tag-57 source.
  3. `pyramide layer-dependency DAG verify (6 layers, 16 edges)` — Tag-58 source.
  4. `verify-containerfile-base-image-digest-pins` — Tag-58 source.
  5. `wirelang spec v0.4.3 freeze-seal probe` — Tag-53 source.
  6. `ots pre-anchor activation probe` — Tag-59 source.
  7. `pre-cutover-final-sanity-gate verdict (READY / DEGRADED / DEFECT)` — Tag-55 source.
  8. `E2E verdict (READY / DRIFT / DEFECT)` — Tag-63 source (PR #400).
- **Stop-on-Fail**: Yes. Any AMBER/RED on any of the 8 → push
  Eve-Checklist into HOLD-PATTERN; AR escalation immediately.
- **Sandbox-OK**: Read-only dashboard inspection. **Sandbox-OK**.
- **Verdict-Marker**: `EVE-E1-READY` / `EVE-E1-HOLD`.

### §2.2 — Eve-Check E2: Branch-Protection Snapshot Pull

- **Owner**: Operator.
- **Action**: Pull the current branch-protection snapshot for
  `main` and verify the 8-context pool is wired exactly per Tag-
  64-Companion §1. Use the Walking-Skeleton verifier in
  `--post-activate-verify` mode against the live snapshot.
- **Stop-on-Fail**: Yes. Any deviation from the 8-context pool
  (missing, extra, wrong-order, strict=false) → HOLD-PATTERN.
- **Sandbox-OK**: The `gh api` snapshot pull is **Operator-Hand-
  Sandbox-Gap**; the verifier run against the pulled JSON is
  Sandbox-OK.
- **Verdict-Marker**: `EVE-E2-POST-ACTIVATE-CLEAN` / `EVE-E2-DEFECT`.

### §2.3 — Eve-Check E3: Trust-Root Snapshot Freshness

- **Owner**: Operator.
- **Action**: Verify the Tag-58 G2 Trust-Root-Snapshot is fresh
  (`cosign-root.json`, `fulcio.pub`, `rekor.pub` last-modified
  date within 7 days). If stale: re-pull per Tag-58 §4.
- **Stop-on-Fail**: Yes. Stale trust-root → HOLD-PATTERN until
  G2 re-armed.
- **Sandbox-OK**: Read-only inspection Sandbox-OK; re-pull is
  Operator-Hand-Sandbox-Gap.
- **Verdict-Marker**: `EVE-E3-TRUST-ROOT-FRESH` / `EVE-E3-STALE`.

### §2.4 — Eve-Check E4: Strict-Flip-PR Review

- **Owner**: Operator + AR pair.
- **Action**: Final review of the Strict-Flip-PR (G1 wiring
  across 4 Wellen + Pilot-Persona; G2 trust-root pin). Confirm
  the PR description references all five G1 targets (G1.1..G1.5)
  per Tag-58 §3 and the three G2 phases (G2.1..G2.3) per Tag-58
  §4.
- **Stop-on-Fail**: Yes. PR substance drift from Tag-58 spec →
  AR-Hand-touchpoint, no merge tonight, push T0 by one day.
- **Sandbox-OK**: Read-only review Sandbox-OK; merge is at T0.
- **Verdict-Marker**: `EVE-E4-STRICT-FLIP-READY` / `EVE-E4-HOLD`.

### §2.5 — Eve-Check E5: OPEN-J3 Carry-Forward Confirmation

- **Owner**: Operator.
- **Action**: Confirm the Containerfile-LABEL
  `org.opencontainers.image.version="0.5.2-final-pre-cutover"`
  is **unchanged** on main-tip (`infra/persona-engine/Containerfile.real`
  line 150). This is intentional per Tag-64-Carry-Forward §9.4;
  the refresh happens at T0+1 (J3-A..J3-G).
- **Stop-on-Fail**: Yes. If the LABEL has drifted pre-T0, this
  is a pre-cutover-byte-stability violation → AR escalation.
- **Sandbox-OK**: Read-only inspection. **Sandbox-OK**.
- **Verdict-Marker**: `EVE-E5-LABEL-BYTE-STABLE` / `EVE-E5-DRIFT`.

### §2.6 — Eve-Check E6: OPEN-K3 Carry-Forward Confirmation

- **Owner**: Operator.
- **Action**: Confirm the V-907 hash-baseline file
  `wirelang/persona_engine/v907-hash-baseline.json` is unchanged
  on main-tip per Tag-59 seal contract. This is intentional per
  Tag-64-Carry-Forward (Tomás-owned, Zone-K).
- **Stop-on-Fail**: Yes. Any baseline-file mutation → AR
  escalation (would violate the seal contract).
- **Sandbox-OK**: Read-only inspection. **Sandbox-OK**.
- **Verdict-Marker**: `EVE-E6-BASELINE-SEALED` / `EVE-E6-DEFECT`.

### §2.7 — Eve-Check E7: Welle-1 Pre-Cutover-PR Drafted

- **Owner**: Operator + AR pair.
- **Action**: Confirm the Welle-1 (`v907_verify`) cutover-PR is
  drafted with the env-var flip per `docs/operations/phase-3c-
  welle-1-runbook.md` §3. The PR must be **drafted, not merged**
  on Eve; merge happens at T0+0.5 after Strict-Flip-PR.
- **Stop-on-Fail**: Yes. PR not drafted → push T0 by one day.
- **Sandbox-OK**: PR drafting is Operator-Hand-Sandbox-Gap; doc-
  review is Sandbox-OK.
- **Verdict-Marker**: `EVE-E7-WELLE-1-DRAFTED` / `EVE-E7-HOLD`.

### §2.8 — Eve-Check E8: Rollback-Plan-Anker

- **Owner**: Operator.
- **Action**: Open `docs/operations/phase-3c-cutover-runbook.md`
  §Rollback and confirm the rollback-toggle env-var pattern
  (`WAKIR_<COMPONENT>_BACKEND=python`) is documented for all 7
  Wellen. Confirm KW-25 fallback-cutover-window is held free per
  Tag-58 §7 Decision-A/B.
- **Stop-on-Fail**: No. Rollback-plan gap → flag for AR-Hand
  but proceed; rollback path is per-component env-var revert,
  intrinsically simple.
- **Sandbox-OK**: Read-only doc-inspection. **Sandbox-OK**.
- **Verdict-Marker**: `EVE-E8-ROLLBACK-DOC-READY`.

### §2.9 — Eve-Check E9: AR-Hand-Touchpoint Schedule Confirmation

- **Owner**: Operator + AR pair.
- **Action**: Confirm AR availability windows for T0 (06:00–14:00
  CEST), T0+1 (06:00–12:00), T0+6 (06:00–14:00). Mid-week
  windows (T0+2..T0+5) have AR-On-Call mode, not pair-mode.
- **Stop-on-Fail**: Yes. AR not available at T0 → push T0 by
  one day.
- **Sandbox-OK**: Calendar inspection. **Sandbox-OK**.
- **Verdict-Marker**: `EVE-E9-AR-AVAILABLE` / `EVE-E9-RESCHEDULE`.

### §2.10 — Eve-Check E10: Final-Acceptance E2E-Smoke Last-Run

- **Owner**: Operator.
- **Action**: Confirm the Tag-63 Pre-Cutover-Final-Acceptance
  E2E-Smoke last-run on main is `READY` and within 24 h. If
  staler than 24 h: trigger a manual workflow_dispatch run.
- **Stop-on-Fail**: Yes. `DRIFT` or `DEFECT` → HOLD-PATTERN.
- **Sandbox-OK**: Read-only run-list inspection is Sandbox-OK;
  manual workflow_dispatch is Operator-Hand-Sandbox-Gap.
- **Verdict-Marker**: `EVE-E10-E2E-READY` / `EVE-E10-DRIFT`.

### §2.11 — Eve-Check E11: Marathon-Dashboard Snapshot

- **Owner**: Operator.
- **Action**: Pull the Tag-50 Marathon-Dashboard snapshot. All 7
  Welle-Tiles must be GREEN; all 7 Probe-Tiles must be GREEN; the
  E2E-Tile (Tag-63) must be GREEN; the AR-Hand-Override-Flag
  (Tag-65) must be `unset`.
- **Stop-on-Fail**: Yes. Any non-GREEN tile → HOLD-PATTERN.
- **Sandbox-OK**: Read-only dashboard inspection. **Sandbox-OK**.
- **Verdict-Marker**: `EVE-E11-DASHBOARD-ALL-GREEN`.

### §2.12 — Eve-Check E12: Final Eve-Verdict Roll-Up

- **Owner**: Operator + AR pair.
- **Action**: Aggregate E1..E11 verdicts. If all 11 are GREEN
  / READY / CLEAN: emit `EVE-VERDICT-GO`. If any HOLD or DRIFT:
  emit `EVE-VERDICT-HOLD` and escalate to AR for T0 push or
  rollback-rehearsal.
- **Stop-on-Fail**: Aggregate verdict gates T0 start.
- **Sandbox-OK**: Aggregation is Sandbox-OK; the GO-emit-marker
  is Operator-Hand documented in the AR-pair log.
- **Verdict-Marker**: `EVE-VERDICT-GO` / `EVE-VERDICT-HOLD`.

---

## §3 — Cutover-T0-Sequence (KW-24 Mo, 2026-06-08)

T0 is **the single most consequential merge-window** in the
Phase-3c-Marathon. The Operator opens this section at 06:00 CEST
on 2026-06-08 (KW-24 Mo). The full T0 sequence is **T0.0 → T0.9**,
mirroring the Tag-58 §6 cutover-sequence and extending it with the
Walking-Skeleton Post-Verify gate.

### §3.1 — T0 Pre-Window-Stand-up (T0.0)

- **Time**: 06:00–06:30 CEST.
- **Owner**: Operator + AR pair.
- **Action**: Re-run Eve-Checks E1, E2, E10 on the morning-of.
  Confirm no overnight drift. Open the AR-pair voice channel.
  Sign off final GO.
- **Stop-on-Fail**: Yes. Overnight drift → rollback to Eve-HOLD
  and push T0 by 24 h (now T0 = T0+1 of original plan).
- **Sandbox-OK**: Stand-up is doc + voice + dashboard. **Sandbox-OK**.

### §3.2 — T0.1: Strict-Flip-PR Merge

- **Time**: 06:30–07:30 CEST.
- **Owner**: Operator.
- **Action**: Merge the Strict-Flip-PR. This wires `cosign verify
  --strict` into all 4 Welle-Quadlet-services plus the Pilot-
  Persona and pins the trust-root snapshot from G2. Required-
  Status-Checks must auto-pass on merge (already-green main-tip).
- **Stop-on-Fail**: Yes. Merge-failure → rollback rehearsal,
  push T0 by 24 h.
- **Sandbox-OK**: PR-merge is **Operator-Hand-Sandbox-Gap**.

### §3.3 — T0.2: Strict-Flip Post-Merge Verification

- **Time**: 07:30–08:00 CEST.
- **Owner**: Operator + Kai (CI hold-pattern).
- **Action**: Confirm the Cosign-Strict-Mode-Readiness-Check job
  posts `STRICT-MODE-ACTIVE` on the merge-commit. Confirm all
  five G1.1..G1.5 quadlet-services show `cosign verify --strict`
  in the wired form (per Tag-58 §3).
- **Stop-on-Fail**: Yes. STRICT-MODE not active → execute
  rollback per §5.1.
- **Sandbox-OK**: Read-only CI-job inspection. **Sandbox-OK**.

### §3.4 — T0.3: Bulk-Activation Walk (8-Pool Wiring)

- **Time**: 08:00–09:00 CEST.
- **Owner**: Operator.
- **Action**: Execute the Tag-62 Bulk-Activation-Walk per
  `docs/operations/bulk-activation-pre-walk-recipe.md` §1, in
  `--enforce` mode with `BULK_ACTIVATE_OPERATOR_HAND=1`. This
  wires all 8 Required-Status-Checks into Branch-Protection
  for main.
- **Stop-on-Fail**: Yes. `--enforce` refusal or `gh api` PUT
  failure → rollback path per §5.2.
- **Sandbox-OK**: **Operator-Hand-Sandbox-Gap**.

### §3.5 — T0.4: Walking-Skeleton Post-Activate-Verify

- **Time**: 09:00–09:30 CEST.
- **Owner**: Operator + Kai (CI verify).
- **Action**: Pull the post-activation branch-protection snapshot
  via `gh api`. Run the Walking-Skeleton verifier
  (`tooling/ops/_bulk_activate_required_checks.py
  --post-activate-verify`) against the snapshot. Expect
  `POST-ACTIVATE-CLEAN`. This is the Tag-65 PR #412 substrate.
- **Stop-on-Fail**: Yes. `POST-ACTIVATE-DEFECT` → diagnose
  context-missing / extra / order-mismatch / strict-false; if
  recoverable in ≤ 30 min, fix forward; else rollback per §5.2.
- **Sandbox-OK**: Snapshot-pull is **Operator-Hand-Sandbox-Gap**;
  verifier-run is Sandbox-OK.

### §3.6 — T0.5: Welle-1 Cutover-PR Merge (`v907_verify`)

- **Time**: 09:30–11:00 CEST.
- **Owner**: Operator + Selin (Persona-Engine hold-pattern).
- **Action**: Merge the Welle-1 cutover-PR per
  `docs/operations/phase-3c-welle-1-runbook.md` §3. This flips
  `WAKIR_V907_VERIFY_BACKEND=rust` for production.
- **Stop-on-Fail**: Yes. Welle-1 failure → rollback Welle-1 env-
  var; **but** the Strict-Flip stays in place (it survives Welle-1
  rollback). Re-attempt at T0+1.
- **Sandbox-OK**: **Operator-Hand-Sandbox-Gap**.

### §3.7 — T0.6: Welle-1 Smoke + Telemetry-Window

- **Time**: 11:00–12:00 CEST.
- **Owner**: Operator + Noa (Observability hold-pattern).
- **Action**: Observe the Welle-1 telemetry-window per Tag-50
  Marathon-Dashboard Welle-1-Tile. Confirm Doppelbetrieb-
  Regression-Comparison stays within tolerance per the Tag-48
  baseline.
- **Stop-on-Fail**: Yes. Out-of-tolerance → rollback Welle-1.
- **Sandbox-OK**: Read-only dashboard. **Sandbox-OK**.

### §3.8 — T0.7: Marathon-Dashboard Roll-Forward

- **Time**: 12:00–13:00 CEST.
- **Owner**: Operator + Noa.
- **Action**: Update the Marathon-Dashboard to reflect Welle-1
  as `CUTOVER-DONE`. Welle-2..7 remain `PRE-CUTOVER`. AR-Hand-
  Cutover-Day-Morgen-Override-Flag (Tag-65) remains `unset`.
- **Stop-on-Fail**: No. Dashboard update is informational.
- **Sandbox-OK**: Dashboard write is Kai-Hand (CI bot); Sandbox-OK
  as automated workflow.

### §3.9 — T0.8: AR-Hand-Touchpoint Sign-off

- **Time**: 13:00–13:30 CEST.
- **Owner**: AR pair.
- **Action**: AR signs off T0 as `T0-DONE` in the AR-pair log.
  Confirms no `Halt vor Phase 4` trigger fired today.
- **Stop-on-Fail**: AR may signal `T0-HOLD` if a residual
  concern is flagged; this defers T0+1 by 24 h but does not
  rollback T0.
- **Sandbox-OK**: AR-log entry. **Sandbox-OK**.

### §3.10 — T0.9: T0+1 Stand-up Pre-Schedule

- **Time**: 13:30–14:00 CEST.
- **Owner**: Operator.
- **Action**: Schedule T0+1 stand-up for 06:00 CEST on KW-24 Di.
  Confirm Selin + Operator availability. Open the OPEN-J3
  LABEL-Patch-PR draft per Tag-58 §9.3 J3-A.
- **Stop-on-Fail**: No.
- **Sandbox-OK**: Scheduling + draft-PR. PR-draft itself is
  Sandbox-OK (no merge yet); merge happens at T0+1.

---

## §4 — Welle-1..7 Day-by-Day (T0+1..T0+6)

Each Welle-Day follows the same five-phase pattern: stand-up,
draft-PR-finalisation, PR-merge, smoke-window, dashboard-update.
The Welle-specific substance is in
`docs/operations/phase-3c-welle-N-runbook.md` for each N.

### §4.1 — T0+1 (KW-24 Di, 2026-06-09): Welle-2 + OPEN-J3

- **Stand-up**: 06:00–06:30 CEST. Re-confirm Welle-1 still GREEN.
- **Welle-2 (`svid_workload_identity`)**: 06:30–08:30 CEST. Per
  `docs/operations/phase-3c-welle-2-runbook.md` §3. Env-var flip:
  `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND=rust`.
- **OPEN-J3 LABEL-Patch**: 08:30–10:00 CEST. Per Tag-58 §9.3
  J3-A..J3-G. Patches Containerfile line 150 from
  `0.5.2-final-pre-cutover` → `0.5.3`. Image-rebuild + re-sign +
  quadlet-image-tag-bump.
- **Welle-2 Smoke**: 10:00–11:00 CEST.
- **Dashboard-Update**: 11:00–11:30 CEST.
- **AR Sign-off**: 11:30–12:00 CEST.

### §4.2 — T0+2 (KW-24 Mi, 2026-06-10): Welle-3

- **Stand-up**: 06:00–06:30 CEST.
- **Welle-3**: 06:30–09:00 CEST. Per
  `docs/operations/phase-3c-welle-3-runbook.md` §3.
- **Welle-1/2 Stability-Check**: 09:00–10:00 CEST.
- **Welle-3 Smoke**: 10:00–11:00 CEST.
- **Dashboard-Update**: 11:00–11:30 CEST.
- **AR Sign-off** (On-Call mode, not pair): 11:30–12:00 CEST.

### §4.3 — T0+3 (KW-24 Do, 2026-06-11): Welle-4

- **Stand-up**: 06:00–06:30 CEST.
- **Welle-4**: 06:30–09:00 CEST. Per
  `docs/operations/phase-3c-welle-4-runbook.md` §3.
- **Welle-1/2/3 Stability-Check**: 09:00–10:00 CEST.
- **Welle-4 Smoke**: 10:00–11:00 CEST.
- **Dashboard-Update**: 11:00–11:30 CEST.
- **AR Sign-off** (On-Call mode): 11:30–12:00 CEST.

### §4.4 — T0+4 (KW-24 Fr, 2026-06-12): Welle-5

- **Stand-up**: 06:00–06:30 CEST.
- **Welle-5**: 06:30–09:00 CEST. Per
  `docs/operations/phase-3c-welle-5-runbook.md` §3.
- **Welle-1..4 Stability-Check**: 09:00–10:00 CEST.
- **Welle-5 Smoke**: 10:00–11:00 CEST.
- **Dashboard-Update**: 11:00–11:30 CEST.
- **AR Sign-off** (On-Call mode): 11:30–12:00 CEST.
- **Weekend-Hold**: KW-24 Sa/So is **no-deploy weekend**; Welle-1..
  5 stay in production. Marathon-Dashboard auto-monitors.

### §4.5 — T0+5 (KW-25 Mo, 2026-06-15): Welle-6

- **Stand-up**: 06:00–06:30 CEST. Re-arm AR-pair mode.
- **Welle-6**: 06:30–09:00 CEST. Per
  `docs/operations/phase-3c-welle-6-runbook.md` §3.
- **Welle-1..5 Stability-Check** (over-weekend): 09:00–10:00 CEST.
- **Welle-6 Smoke**: 10:00–11:00 CEST.
- **Dashboard-Update**: 11:00–11:30 CEST.
- **AR Sign-off** (pair-mode): 11:30–12:00 CEST.

### §4.6 — T0+6 (KW-25 Di, 2026-06-16): Welle-7 + Marathon-Final-Bilanz

- **Stand-up**: 06:00–06:30 CEST.
- **Welle-7**: 06:30–09:00 CEST. Per
  `docs/operations/phase-3c-welle-7-runbook.md` §3.
- **Welle-1..6 Stability-Check**: 09:00–10:00 CEST.
- **Welle-7 Smoke**: 10:00–11:00 CEST.
- **Marathon-Final-Bilanz Pull**: 11:00–12:00 CEST. Per the
  Tag-51 Final-Bilanz workflow integration.
- **Dashboard-Update**: 12:00–12:30 CEST. All 7 Welle-Tiles
  show `CUTOVER-DONE`. E2E-Tile stays GREEN.
- **AR Final Sign-off**: 12:30–14:00 CEST. AR signs `MARATHON-
  CUTOVER-COMPLETE`. **The `Halt vor Phase 4` pin (§9) holds**;
  no Phase-4 work begins.

---

## §5 — Rollback-Trigger-Pfade

Five distinct rollback paths exist. Each has a trigger condition,
an owner, a recovery time-budget, and a fall-back-pin. The
Operator opens this section whenever an Eve-Check or T-step
returns a non-GREEN verdict.

### §5.1 — Rollback-Path R1: Strict-Flip-PR Post-Merge Defect

- **Trigger**: T0.3 `STRICT-MODE-ACTIVE` job posts `STRICT-MODE-
  DEFECT` after T0.2 merge.
- **Owner**: Operator + Kai.
- **Recovery**: Revert the Strict-Flip-PR via `gh pr revert` plus
  re-apply the previous-known-good cosign-policy-snapshot.
- **Time-budget**: ≤ 60 min.
- **Fall-back-pin**: KW-25 cutover-window (per Tag-58 §7 Decision-A).

### §5.2 — Rollback-Path R2: Bulk-Activation Walk Defect

- **Trigger**: T0.4 `POST-ACTIVATE-DEFECT` from Walking-Skeleton
  verifier OR T0.3 `gh api` PUT failure.
- **Owner**: Operator.
- **Recovery**: Revert branch-protection settings via `gh api PUT`
  with the pre-activation snapshot. The Walking-Skeleton verifier
  doubles as the diff-source for revert.
- **Time-budget**: ≤ 30 min.
- **Fall-back-pin**: T0+1 retry of Bulk-Activation; **does not**
  push the full Marathon by one day. Welle-1 still merges at T0+1
  morning per §3.6 schedule.

### §5.3 — Rollback-Path R3: Welle-N Post-Cutover Defect

- **Trigger**: Welle-N smoke-window shows out-of-tolerance
  Doppelbetrieb-Regression OR Marathon-Dashboard Welle-N-Tile
  flips RED.
- **Owner**: Operator + Selin.
- **Recovery**: Revert the Welle-N env-var flip
  (`WAKIR_<COMPONENT>_BACKEND=python`). Re-deploy quadlet-services
  with the python-default. Welle-(N-1)..Welle-1 stay on rust.
- **Time-budget**: ≤ 45 min.
- **Fall-back-pin**: Re-attempt Welle-N at T0+1 of original
  schedule (one-day slip); other Wellen continue if Welle-N is
  not a hard-dependency.

### §5.4 — Rollback-Path R4: OPEN-J3 LABEL-Patch Defect

- **Trigger**: T0+1 J3-D image-rebuild + re-sign fails OR J3-E
  quadlet-image-tag-bump fails OR J3-F cross-substrate-parity-
  gate fails.
- **Owner**: Kai + Operator.
- **Recovery**: Roll back to previous image-digest. The
  `image.version` label stays at `0.5.2-final-pre-cutover`; the
  carry-forward continues to T0+2 or later.
- **Time-budget**: ≤ 60 min.
- **Fall-back-pin**: Re-attempt at T0+2 (KW-24 Mi) before
  Welle-3 stand-up.

### §5.5 — Rollback-Path R5: Multi-Welle Marathon-Hold

- **Trigger**: Any two consecutive Welle-N failures OR AR signals
  `Marathon-Hold`.
- **Owner**: AR pair + Operator.
- **Recovery**: Halt Welle-(N+1)..Welle-7 entirely. Run a
  full-roll-back to the last-known-good Welle. Push the
  Marathon-tail into KW-25 / KW-26.
- **Time-budget**: ≤ 4 h (single Operator-Hand-Day).
- **Fall-back-pin**: KW-25 / KW-26 Marathon-Tail-Window. AR
  decision required.

---

## §6 — AR-Hand-Touchpoint-Checklist

Six AR-Hand-Touchpoints punctuate the eight-day arc. Each has a
preferred time, an owner, a substantive question the AR is asked,
and a Stop-on-Fail consequence. AR signs off in the AR-pair log.

### §6.1 — TP1: Eve-Verdict (2026-05-29, 17:30 CEST)

- **Question**: "Does the aggregated EVE-VERDICT support T0
  start at 06:00 CEST on 2026-06-08?"
- **Stop-on-Fail**: `EVE-VERDICT-HOLD` → T0 deferred to KW-25.
- **AR-Hand**: Mandatory pair-mode.

### §6.2 — TP2: T0 Final-GO (2026-06-08, 06:15 CEST)

- **Question**: "Confirm GO for Strict-Flip-PR merge at 06:30?"
- **Stop-on-Fail**: T0-HOLD → 24 h push.
- **AR-Hand**: Mandatory pair-mode.

### §6.3 — TP3: T0 Post-Bulk-Walk-Sign-off (2026-06-08, 09:45 CEST)

- **Question**: "Confirm `POST-ACTIVATE-CLEAN`, proceed to
  Welle-1?"
- **Stop-on-Fail**: T0-Pause → diagnose Walking-Skeleton-verifier
  defect; rollback R2 if needed.
- **AR-Hand**: Mandatory pair-mode.

### §6.4 — TP4: T0+1 Welle-2 + J3 Sign-off (2026-06-09, 12:00 CEST)

- **Question**: "Confirm Welle-1 + Welle-2 both GREEN, OPEN-J3
  LABEL-Patch landed cleanly?"
- **Stop-on-Fail**: Welle-3..7 defer by 24 h.
- **AR-Hand**: Mandatory pair-mode.

### §6.5 — TP5: T0+4 Weekend-Hold-Sign-off (2026-06-12, 12:00 CEST)

- **Question**: "Confirm Welle-1..5 stable, weekend-hold
  policy intact, no-deploy weekend confirmed?"
- **Stop-on-Fail**: Convert weekend to On-Call-Watch with
  Welle-1..5 monitoring.
- **AR-Hand**: Mandatory pair-mode (last AR pair before T0+5).

### §6.6 — TP6: T0+6 Marathon-Final Sign-off (2026-06-16, 13:30 CEST)

- **Question**: "Confirm all 7 Wellen `CUTOVER-DONE`, Marathon-
  Final-Bilanz READY, `Halt vor Phase 4` pin held?"
- **Stop-on-Fail**: If pin breached (Phase-4 work started),
  AR escalation; Phase-4 work paused.
- **AR-Hand**: Mandatory pair-mode. This is the closing AR-
  Touchpoint for Phase-3-Marathon.

---

## §7 — Cross-References zu Tag-58 + Tag-62 + Tag-64-Recipes

This section is the **canonical cross-reference matrix** linking
every Eve-Check, T0-step, Welle-Day-step, and Rollback-Path to
its source-substrate document. The Eve-Doc here is the
**dispatcher**; the source docs remain the substantive recipes.

### §7.1 — Eve-Check → Source Mapping

| Eve-Check | Source-Doc | Source-§ |
|---|---|---|
| E1 (CI Surface) | `docs/operations/branch-protection-required-checks-tag64-companion.md` | §1 |
| E2 (BP Snapshot Pull) | `docs/operations/bulk-activation-pre-walk-recipe.md` | §1 |
| E3 (Trust-Root) | `docs/operations/strict-flip-readiness-map-tag58.md` | §4 |
| E4 (Strict-Flip Review) | `docs/operations/strict-flip-readiness-map-tag58.md` | §3 + §4 |
| E5 (OPEN-J3) | `docs/operations/strict-flip-readiness-map-tag58.md` | §9.4 |
| E6 (OPEN-K3) | `docs/operations/open-k3-v907-baseline-metadata-carry-forward.md` | §1 + §2 |
| E7 (Welle-1 Draft) | `docs/operations/phase-3c-welle-1-runbook.md` | §3 |
| E8 (Rollback-Anker) | `docs/operations/phase-3c-cutover-runbook.md` | Rollback-§ |
| E9 (AR Schedule) | Eve-Doc only | §2.9 |
| E10 (E2E Smoke) | `docs/operations/branch-protection-required-checks-tag64-companion.md` | §1 row-#8 |
| E11 (Dashboard) | `docs/operations/phase-3c-welle-status-dashboard-runbook.md` | full doc |
| E12 (Verdict Roll-Up) | Eve-Doc only | §2.12 |

### §7.2 — T0-Step → Source Mapping

| T0-Step | Source-Doc | Source-§ |
|---|---|---|
| T0.0 | Eve-Doc only | §3.1 |
| T0.1 | `docs/operations/strict-flip-readiness-map-tag58.md` | §6 T2..T4 |
| T0.2 | `docs/operations/cosign-strict-mode-activation.md` | full doc |
| T0.3 | `docs/operations/bulk-activation-pre-walk-recipe.md` | §1 |
| T0.4 | `docs/operations/bulk-activation-subsumption-check-8-coordination.md` | §1 + §2 |
| T0.5 | `docs/operations/phase-3c-welle-1-runbook.md` | §3 |
| T0.6 | `docs/operations/welle-1-2-doppel-telemetry-runbook.md` | §1 |
| T0.7 | `docs/operations/phase-3c-welle-status-dashboard-runbook.md` | full doc |
| T0.8 | Eve-Doc only | §3.9 |
| T0.9 | Eve-Doc + Tag-58 §9.3 | J3-A |

### §7.3 — Welle-Day → Source Mapping

| T0+N | Welle | Source-Doc |
|---|---|---|
| T0+1 | 2 | `docs/operations/phase-3c-welle-2-runbook.md` |
| T0+2 | 3 | `docs/operations/phase-3c-welle-3-runbook.md` |
| T0+3 | 4 | `docs/operations/phase-3c-welle-4-runbook.md` |
| T0+4 | 5 | `docs/operations/phase-3c-welle-5-runbook.md` |
| T0+5 | 6 | `docs/operations/phase-3c-welle-6-runbook.md` |
| T0+6 | 7 | `docs/operations/phase-3c-welle-7-runbook.md` |

### §7.4 — Rollback-Path → Source Mapping

| Rollback | Source-Doc | Source-§ |
|---|---|---|
| R1 | `docs/operations/strict-flip-readiness-map-tag58.md` | §7 Decision-A |
| R2 | `docs/operations/bulk-activation-pre-walk-recipe.md` | §2 dry-run path |
| R3 | `docs/operations/phase-3c-cutover-runbook.md` | Rollback-§ |
| R4 | `docs/operations/strict-flip-readiness-map-tag58.md` | §9.3 J3-fallback |
| R5 | `docs/operations/phase-3c-cutover-runbook.md` | Rollback-§ multi-welle |

---

## §8 — Operator-Hand-Sandbox-Boundary

This is the **explicit sandbox-boundary declaration** for Tag-66.
The Mira-Sandbox produces the Eve-Doc; the Operator-Workstation
executes the active operations.

### §8.1 — Sandbox-Scope (Mira-Sandbox-OK)

The following operations are Sandbox-OK and may be run from
within the Mira-Sandbox during preparation or audit:

- Reading any wakir-runtime doc, including this Eve-Doc.
- Reading the wakir-runtime CI dashboard via `gh run list` /
  `gh run view`.
- Running the Walking-Skeleton verifier against a **fixture**
  snapshot (Tag-65 PR #412 substrate).
- Running the Bulk-Activation Pre-Walk planner in `--dry-run`
  mode (Tag-62 substrate).
- Aggregating verdicts, drafting Eve-Verdict-Roll-Ups.
- Inspecting Containerfile-LABEL values via repo-tree reads.
- Inspecting V-907 baseline-metadata files via repo-tree reads.

### §8.2 — Out-of-Sandbox-Scope (Operator-Hand-Sandbox-Gap)

The following operations are **explicitly out-of-scope** for the
Mira-Sandbox and require Operator-Hand-Workstation execution:

- `gh api PUT` mutating branch-protection settings.
- `gh pr merge` of the Strict-Flip-PR or any Welle-N-Cutover-PR.
- `cosign initialize` / `cosign sign` against the production
  trust-root.
- Pulling live branch-protection snapshots from production main
  (the snapshot itself is a non-secret artefact; the **pull** is
  Operator-Hand for env-isolation reasons).
- Manual workflow_dispatch on production CI.
- Editing or mutating Containerfile `image.version` labels in
  the production-image-build pipeline (J3-B..J3-G).
- Re-publishing OCI image digests post-LABEL-Patch.
- All env-var flips: `WAKIR_<COMPONENT>_BACKEND=rust`.
- All quadlet-service-file reloads on the Pilot-VM or production
  hosts.
- Trust-Root-Snapshot file mutations in the trust-snapshot dir.
- Issuing the EVE-VERDICT-GO marker into the AR-pair log.

### §8.3 — Sandbox-Boundary Enforcement Reminders

- The Bulk-Activation script (Tag-62) refuses `--enforce` mode
  unless `BULK_ACTIVATE_OPERATOR_HAND=1` is set and CI env-vars
  are absent. The Mira-Sandbox does not set this env-var.
- The Tag-65 Walking-Skeleton verifier accepts `--post-activate-
  snapshot <path>` as input but does **not** itself pull the
  snapshot from `gh api`. The pull step is explicitly Operator-
  Hand-Sandbox-Gap.
- The phase-3c-cutover-dry-run script never invokes the real
  Rust binary, never connects to NATS, and never calls the
  Anthropic API — it is by-construction Sandbox-OK.
- All ADR-0020 §10 + Memory `feedback_sandbox_host_trennung` +
  Memory `feedback_live_bringup_sandbox_gap` directives apply
  in full and override any apparent shortcut in this Eve-Doc.

---

## §9 — Post-Cutover Phase-4-Vorbereitungs-Anker

This section is the **explicit Phase-4 freeze-pin** per the
Tag-65 AR-Vorzeichen "Halt vor Phase 4" signal. **Phase-4 work
does not begin until the AR explicitly re-arms.** The pin holds
through T0+6 and beyond.

### §9.1 — AR-Vorzeichen "Halt vor Phase 4" — Verbatim-Anker

The Tag-65 AR-Vorzeichen reads, in operative form:

> "Phase-3-Marathon ends at Welle-7 cutover and Marathon-Final-
> Bilanz READY. The transition to Phase-4 (post-cutover
> stabilisation, production-readiness review, brand-publication
> pulse) requires an explicit AR-Hand re-arm signal. Until that
> signal is issued, no Phase-4 substrate enters the planning
> backlog and no Phase-4-prep work spawns from the Marathon-
> closing sessions."

This is pinned as `PHASE-4-HOLD-VOR-RE-ARM` and is the canonical
state at T0+6 close-of-business.

### §9.2 — What "Halt vor Phase 4" Means Operationally

- **Spawn-Filter**: No persona-spawn between T0+6 and AR-re-arm
  may carry a Phase-4 brief. Any Mira-Hand auto-spawn that drifts
  into Phase-4 scope is a violation of this pin.
- **Roadmap-Freeze**: `projects/roadmap.md` Phase-4 section
  stays at its T0+6 state. No additions, no re-ordering, no
  status-bump on Phase-4 items.
- **ADR-Freeze**: No new ADRs that establish Phase-4 substrate.
  ADRs that **close** Phase-3 substrate (final-bilanz, lessons-
  learned, post-mortem) are permitted.
- **Brand-/Publication-Freeze**: No `wakir-labs/site` push for
  Phase-4 launch-prep content. The Phase-3-Marathon-completion
  announce is itself a Phase-3-close artefact and is permitted
  per Tomás scope.
- **Engineering-Freeze**: No 0.5.4 / 0.6.0 / 0.6.x persona-engine
  bumps. Hot-fix patches for production stability are permitted
  (they close Phase-3, do not open Phase-4).

### §9.3 — Phase-3-Close Items Permitted Under the Pin

Three substantive items **are** permitted before AR-re-arm
because they close Phase-3, not open Phase-4:

1. **Marathon-Final-Bilanz Lieferbericht** — Tag-67 or later,
   per Tag-51 substrate.
2. **Phase-3-Post-Mortem** — Tag-67 or later, audit-owned,
   Amara/Henrik scope.
3. **OPEN-J3 / OPEN-K3 Closure-Records** — once J3 is patched at
   T0+1 and K3 stays sealed through T0+6, both carry-forwards
   close as `RESOLVED-INTENTIONAL` per Tag-64 substrate.

### §9.4 — AR-Re-Arm Trigger

The AR re-arms Phase-4 work via an explicit AR-Hand signal in
the AR-pair log carrying the marker `PHASE-4-RE-ARMED`. Until
that marker appears, **no agent — Kai, Reza, Tomás, Amara,
Selin, Noa, Mira — initiates Phase-4 substrate**.

Mira-Hand-Spawn-Filter: any spawn-brief between T0+6 and the
re-arm signal **must** include `PHASE-4-HOLD-VOR-RE-ARM` as a
substrate-marker and **must not** carry Phase-4 task-content.

### §9.5 — Phase-4-Prep Anchor (Inert)

For the AR's convenience, the following Phase-4 substrate
topics are **inert anchors** (named, not actioned):

- Production-Readiness-Review (audit-scope, Amara/Henrik).
- Brand-Publication-Pulse (Tomás-scope, site/quartz).
- Persona-Engine 0.6.x roadmap (Selin-scope).
- Inter-Agent-Protocol Phase-3-Lessons feedback (Reza-scope).
- Container-Orchestrator Phase-4 Substrate-Bridge (Kai-scope).
- Federation-Substrate Operations Phase-4 (Kai-scope).

These topics are **named here so they are not forgotten** at
T0+6, but they remain **untouched** until AR-re-arm.

### §9.6 — Sandbox-Boundary Reaffirmation

The Phase-4-freeze does not change the sandbox-boundary in §8.
Operations that are Sandbox-OK before the pin remain Sandbox-OK
after. Operations that are Operator-Hand-Sandbox-Gap before the
pin remain Operator-Hand-Sandbox-Gap after. The pin governs
**substrate-scope**, not **sandbox-scope**.

---

— Kai (Tag-66, 2026-05-19)
